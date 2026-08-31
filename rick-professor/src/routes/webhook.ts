import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { timingSafeEqual } from 'crypto';
import { processMessage } from '../core/processor';
import { config } from '../config';
import { getRedis } from '../lib/redis';

/**
 * Schema Zod para validação do payload do Telegram.
 * Resolve a vulnerabilidade de cast inseguro apontada na auditoria.
 */
const TelegramMessageSchema = z.object({
    message_id: z.number().int(),
    from: z.object({
        id: z.number(),
        is_bot: z.boolean().optional(),
        first_name: z.string().optional(),
        username: z.string().optional(),
        language_code: z.string().optional(),
    }).optional(),
    chat: z.object({
        id: z.number(),
        type: z.string().optional(),
    }),
    date: z.number().int(),
    text: z.string().max(20000).optional(),
});

const TelegramUpdateSchema = z.object({
    update_id: z.number().int().nonnegative(),
    message: TelegramMessageSchema.optional(),
    channel_post: TelegramMessageSchema.optional(),
});

export interface TelegramIdempotencyStore {
    set(
        key: string,
        value: string,
        mode: 'EX',
        ttlSeconds: number,
        condition: 'NX'
    ): Promise<'OK' | null>;
}

export interface WebhookRouteOptions {
    idempotencyStore?: TelegramIdempotencyStore;
    processMessage?: typeof processMessage;
}

export function isTelegramWebhookSecretValid(
    presentedSecret: string | undefined,
    configuredSecret: string | undefined
): boolean {
    if (!presentedSecret || !configuredSecret) return false;

    const presented = Buffer.from(presentedSecret, 'utf8');
    const configured = Buffer.from(configuredSecret, 'utf8');
    return presented.length === configured.length && timingSafeEqual(presented, configured);
}

export async function claimTelegramUpdate(
    updateId: number,
    store: TelegramIdempotencyStore,
    ttlSeconds: number,
    timeoutMs = 3_000
): Promise<boolean> {
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error('telegram_idempotency_timeout')), timeoutMs);
        timeout.unref?.();
    });

    try {
        const result = await Promise.race([
            store.set(
                `professor:telegram:update:${updateId}`,
                'processed',
                'EX',
                ttlSeconds,
                'NX'
            ),
            timeoutPromise,
        ]);
        return result === 'OK';
    } finally {
        if (timeout) clearTimeout(timeout);
    }
}

export default async function webhookRoutes(
    fastify: FastifyInstance,
    options: WebhookRouteOptions = {}
) {
    const processMessageFn = options.processMessage ?? processMessage;
    const configuredIdempotencyStore = options.idempotencyStore;

    /**
     * Endpoint do Webhook do Telegram
     * Implementa o padrão "fire-and-forget" para evitar timeouts no Telegram.
     */
    fastify.post('/webhook/telegram', async (request, reply) => {
        const configuredSecret = config.TELEGRAM_WEBHOOK_SECRET_TOKEN;
        if (!configuredSecret) {
            fastify.log.error({ msg: 'Telegram webhook secret não configurado' });
            return reply.code(503).send({ error: 'Webhook unavailable' });
        }

        const header = request.headers['x-telegram-bot-api-secret-token'];
        const presentedSecret = typeof header === 'string' ? header : undefined;
        if (!isTelegramWebhookSecretValid(presentedSecret, configuredSecret)) {
            return reply.code(401).send({ error: 'Unauthorized' });
        }

        try {
            // Validação do Payload com Zod
            const body = TelegramUpdateSchema.safeParse(request.body);

            if (!body.success) {
                // Log estruturado para falhas de validação
                fastify.log.warn({
                    msg: '[Webhook] Payload Inválido',
                    errors: body.error.format()
                });
                return reply.code(400).send({ error: 'Invalid payload' });
            }

            const update = body.data;
            // Keep liveness independent from Redis and do not open the client
            // until a fully authenticated Telegram update needs deduplication.
            const idempotencyStore = configuredIdempotencyStore ?? getRedis();
            const firstDelivery = await claimTelegramUpdate(
                update.update_id,
                idempotencyStore,
                config.TELEGRAM_UPDATE_TTL_SECONDS,
                config.TELEGRAM_IDEMPOTENCY_TIMEOUT_MS
            );
            if (!firstDelivery) {
                return reply.code(200).send({ received: true, duplicate: true });
            }

            const message = update.message || update.channel_post;

            // Ignora updates que não contenham mensagens de texto
            if (!message || !message.text?.trim()) {
                return reply.code(200).send({ received: true });
            }

            const chatId = message.chat.id;
            const text = message.text;
            const messageId = message.message_id;

            // Log de início de processamento
            fastify.log.info({
                msg: 'Mensagem recebida para processamento',
                chatId,
                messageId
            });

            /**
             * Processamento em Background
             * Orquestra a lógica de RAG (OpenAI + Qdrant + Redis).
             */
            void processMessageFn({
                text,
                chatId: String(chatId),
                messageId,
                raw: update
            }).catch(err => {
                // Log de erro no background para observabilidade
                fastify.log.error({
                    msg: 'Erro no processamento do agente',
                    chatId,
                    error: 'processor_failure'
                });
            });

            return reply.code(200).send({ received: true });

        } catch {
            fastify.log.error({ msg: 'Erro fatal no endpoint de Webhook', error: 'webhook_failure' });
            return reply.code(503).send({ error: 'Webhook unavailable' });
        }
    });

    /**
     * Endpoint de Healthcheck
     * Essencial para o monitoramento de integridade no Easypanel.
     */
    fastify.get('/health', async () => {
        return {
            status: 'ok',
            timestamp: new Date().toISOString(),
            service: 'cvg-agent-professor'
        };
    });
}

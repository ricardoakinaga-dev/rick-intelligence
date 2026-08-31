import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { processMessage } from '../core/processor';

/**
 * Schema Zod para validação do payload do Telegram.
 * Resolve a vulnerabilidade de cast inseguro apontada na auditoria.
 */
const TelegramMessageSchema = z.object({
    message_id: z.number(),
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
    date: z.number(),
    text: z.string().optional(),
});

const TelegramUpdateSchema = z.object({
    update_id: z.number(),
    message: TelegramMessageSchema.optional(),
    channel_post: TelegramMessageSchema.optional(),
});

export default async function webhookRoutes(fastify: FastifyInstance) {
    /**
     * Endpoint do Webhook do Telegram
     * Implementa o padrão "fire-and-forget" para evitar timeouts no Telegram.
     */
    fastify.post('/webhook/telegram', async (request, reply) => {
        // Retorna 200 OK imediatamente para o Telegram não reenviar a mesma mensagem
        reply.status(200).send({ received: true });

        try {
            // Validação do Payload com Zod
            const body = TelegramUpdateSchema.safeParse(request.body);

            if (!body.success) {
                // Log estruturado para falhas de validação
                fastify.log.warn({
                    msg: '[Webhook] Payload Inválido',
                    chatId: (request.body as any)?.message?.chat?.id,
                    errors: body.error.format()
                });
                return;
            }

            const update = body.data;
            const message = update.message || update.channel_post;

            // Ignora updates que não contenham mensagens de texto
            if (!message || !message.text) {
                return;
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
            processMessage({
                text,
                chatId: String(chatId),
                messageId,
                raw: update
            }).catch(err => {
                // Log de erro no background para observabilidade
                fastify.log.error({
                    msg: 'Erro no processamento do agente',
                    chatId,
                    error: err instanceof Error ? err.message : String(err)
                });
            });

        } catch (error) {
            fastify.log.error({ msg: 'Erro fatal no endpoint de Webhook', error });
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
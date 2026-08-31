import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { processMessage } from '../core/processor';
import { config } from '../config';
import { chatCompletion, getEmbedding } from '../lib/openai';
import { searchQdrant } from '../lib/qdrant';
import { acquireLock } from '../lib/redis-lock';
import { getChatHistory, addChatMessage } from '../lib/memory';
import { log } from '../lib/logging';

const ChatMessageSchema = z.object({
    role: z.enum(['system', 'user', 'assistant']).catch('user'),
    content: z.union([z.string(), z.array(z.any())]).optional(),
});

const ChatCompletionsSchema = z.object({
    model: z.string().optional(),
    messages: z.array(ChatMessageSchema).min(1),
    stream: z.boolean().optional().default(false),
    user: z.string().optional(),
    conversation_id: z.string().optional(),
});

function extractTextContent(content: unknown): string {
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
        return content
            .map((item) => {
                if (typeof item === 'string') return item;
                if (item && typeof item === 'object' && 'text' in item) return String((item as any).text || '');
                return '';
            })
            .filter(Boolean)
            .join('\n');
    }
    return '';
}

function buildPrompt(messages: Array<{ role: string; content?: unknown }>): string {
    const systemParts = messages
        .filter((m) => m.role === 'system')
        .map((m) => extractTextContent(m.content))
        .filter(Boolean);

    const userParts = messages
        .filter((m) => m.role !== 'system')
        .map((m) => `${m.role.toUpperCase()}: ${extractTextContent(m.content)}`)
        .filter((s) => s.trim().length > 0);

    if (systemParts.length === 0) return userParts.join('\n\n');
    return `INSTRUÇÕES DE CONTEXTO:\n${systemParts.join('\n\n')}\n\nCONVERSA:\n${userParts.join('\n\n')}`;
}

function authOk(authHeader?: string): boolean {
    if (!config.API_KEY) return true;
    if (!authHeader) return false;
    return authHeader === `Bearer ${config.API_KEY}`;
}

export default async function openAiRoutes(fastify: FastifyInstance) {
    fastify.get('/v1/models', async (request, reply) => {
        if (!authOk(request.headers.authorization)) {
            return reply.code(401).send({ error: { message: 'Unauthorized', type: 'auth_error' } });
        }

        return {
            object: 'list',
            data: [
                {
                    id: config.PUBLIC_MODEL_NAME,
                    object: 'model',
                    created: Math.floor(Date.now() / 1000),
                    owned_by: 'rick-professor',
                },
            ],
        };
    });

    fastify.post('/v1/chat/completions', async (request, reply) => {
        if (!authOk(request.headers.authorization)) {
            return reply.code(401).send({ error: { message: 'Unauthorized', type: 'auth_error' } });
        }

        const parsed = ChatCompletionsSchema.safeParse(request.body);
        if (!parsed.success) {
            return reply.code(400).send({ error: { message: 'Invalid payload', details: parsed.error.format() } });
        }

        const body = parsed.data;

        const prompt = buildPrompt(body.messages);
        const conversationId = body.conversation_id || body.user || `openwebui-${Date.now()}`;
        const captured: string[] = [];

        const result = await processMessage(
            {
                text: prompt,
                chatId: conversationId,
                raw: body,
            },
            {
                chatCompletion,
                getEmbedding,
                searchQdrant,
                acquireLock,
                sendMessage: async (_chatId: string, message: string) => {
                    captured.push(message);
                },
                getChatHistory,
                addChatMessage,
                logger: log,
            }
        );

        const content = result.replyText || captured[captured.length - 1] || 'Não foi possível gerar resposta.';
        const created = Math.floor(Date.now() / 1000);
        const completionId = `chatcmpl-${created}`;

        if (body.stream) {
            reply.raw.writeHead(200, {
                'Content-Type': 'text/event-stream; charset=utf-8',
                'Cache-Control': 'no-cache, no-transform',
                Connection: 'keep-alive',
            });

            const chunkBase = {
                id: completionId,
                object: 'chat.completion.chunk',
                created,
                model: config.PUBLIC_MODEL_NAME,
            };

            reply.raw.write(`data: ${JSON.stringify({
                ...chunkBase,
                choices: [
                    {
                        index: 0,
                        delta: { role: 'assistant' },
                        finish_reason: null,
                    },
                ],
            })}\n\n`);

            reply.raw.write(`data: ${JSON.stringify({
                ...chunkBase,
                choices: [
                    {
                        index: 0,
                        delta: { content },
                        finish_reason: null,
                    },
                ],
            })}\n\n`);

            reply.raw.write(`data: ${JSON.stringify({
                ...chunkBase,
                choices: [
                    {
                        index: 0,
                        delta: {},
                        finish_reason: 'stop',
                    },
                ],
            })}\n\n`);
            reply.raw.write('data: [DONE]\n\n');
            reply.raw.end();
            return reply;
        }

        return {
            id: completionId,
            object: 'chat.completion',
            created,
            model: config.PUBLIC_MODEL_NAME,
            choices: [
                {
                    index: 0,
                    message: {
                        role: 'assistant',
                        content,
                    },
                    finish_reason: 'stop',
                },
            ],
            usage: {
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
            },
            metadata: result.metadata || {},
        };
    });
}

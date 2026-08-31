import { z } from 'zod';
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const envSchema = z.object({
    NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
    PORT: z.coerce.number().default(3000),
    LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),

    OPENAI_API_KEY: z.string().min(1, 'A chave da OpenAI é obrigatória'),
    TELEGRAM_BOT_TOKEN: z.string().optional(),
    API_KEY: z.string().optional(),
    PUBLIC_MODEL_NAME: z.string().default('rick-professor'),

    QDRANT_URL: z.string().default('http://rickvet-rag-qdrant:6333'),
    QDRANT_COLLECTION: z.string().default('rickvet_documents'),
    QDRANT_SCORE_THRESHOLD: z.coerce.number().min(0).max(1).default(0),

    REDIS_URL: z.string().default('redis://rick-professor-redis:6379'),
    REDIS_LOCKER_URL: z.string().default('http://n8n-redis-locker:3000'),

    MODEL_PREPROCESSOR: z.string().default('gpt-4o-mini'),
    MODEL_PLANNER: z.string().default('gpt-4o'),
    MODEL_AGENT: z.string().default('gpt-4o'),
    MODEL_FALLBACK: z.string().default('gpt-4o-mini'),
    EMBEDDING_MODEL: z.string().default('text-embedding-3-small'),
});

const parseEnv = () => {
    const result = envSchema.safeParse(process.env);

    if (!result.success) {
        console.error(
            '❌ Erro de Configuração: variáveis inválidas ou ausentes:\n',
            JSON.stringify(result.error.format(), null, 2)
        );
        process.exit(1);
    }

    return result.data;
};

export const config = parseEnv();

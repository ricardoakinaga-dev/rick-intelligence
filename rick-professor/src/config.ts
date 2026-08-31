import { z } from 'zod';
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const envSchema = z.object({
    NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
    PORT: z.coerce.number().default(3000),
    LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),

    OPENAI_API_KEY: z.string().trim().min(1, 'A chave da OpenAI é obrigatória'),
    OPENAI_BASE_URL: z.string().url().default('https://api.openai.com/v1'),
    OPENAI_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(5_000),
    OPENAI_RETRY_DELAY_MS: z.coerce.number().int().nonnegative().max(10_000).default(1_000),
    TELEGRAM_BOT_TOKEN: z.string().optional(),
    TELEGRAM_WEBHOOK_SECRET_TOKEN: z.string().trim().min(1).max(256).optional(),
    TELEGRAM_UPDATE_TTL_SECONDS: z.coerce.number().int().positive().max(7 * 24 * 60 * 60).default(24 * 60 * 60),
    TELEGRAM_IDEMPOTENCY_TIMEOUT_MS: z.coerce.number().int().positive().max(30_000).default(3_000),
    API_KEY: z.string().trim().min(1).optional(),
    PUBLIC_MODEL_NAME: z.string().default('rick-professor'),

    QDRANT_URL: z.string().default('http://rickvet-rag-qdrant:6333'),
    QDRANT_COLLECTION: z.string().default('rag_phase0'),
    QDRANT_SCORE_THRESHOLD: z.coerce.number().min(0).max(1).default(0),
    QDRANT_WORKSPACE_ID: z.string().trim().min(1).default('default'),
    QDRANT_ALLOWED_COLLECTION_IDS: z.string().default('rag_phase0'),

    LOCK_TTL_MS: z.coerce.number().int().positive().default(45000),
    LOCK_RENEW_INTERVAL_MS: z.coerce.number().int().positive().default(15000),

    EVIDENCE_APPROVED_SCORE_THRESHOLD: z.coerce.number().min(0).max(1).default(0.62),
    EVIDENCE_WEAK_SCORE_THRESHOLD: z.coerce.number().min(0).max(1).default(0.55),
    EVIDENCE_MIN_MUST_COVERAGE: z.coerce.number().min(0).max(1).default(0.5),
    EVIDENCE_MIN_APPROVED_HITS: z.coerce.number().int().positive().default(2),

    REDIS_URL: z.string().default('redis://rick-professor-redis:6379'),
    REDIS_LOCKER_URL: z.string().default('http://n8n-redis-locker:3000'),

    MODEL_PREPROCESSOR: z.string().trim().min(1).default('gpt-4o-mini'),
    MODEL_PLANNER: z.string().trim().min(1).default('gpt-4o'),
    MODEL_AGENT: z.string().trim().min(1).default('gpt-4o'),
    MODEL_FALLBACK: z.string().trim().min(1).default('gpt-4o-mini'),
    EMBEDDING_MODEL: z.string().trim().min(1).default('text-embedding-3-small'),
    EMBEDDING_DIMENSION: z.coerce.number().int().positive().max(16_384).default(1_536),
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

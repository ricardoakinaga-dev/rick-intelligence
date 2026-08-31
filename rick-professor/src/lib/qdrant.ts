import axios, { AxiosInstance } from 'axios';
import { config } from '../config';
import { log } from './logging';

/**
 * Interface exportada para garantir consistência em todo o projeto.
 */
export interface QdrantSearchResult {
    id: string | number;
    score: number;
    payload: any;
}

const qdrantClient: AxiosInstance = axios.create({
    baseURL: config.QDRANT_URL,
    timeout: 7000,
    headers: {
        'Content-Type': 'application/json',
    },
});

function clamp01(n: number): number {
    return Math.max(0, Math.min(1, n));
}

function resolveCollection(): string {
    const fromEnv = process.env.QDRANT_COLLECTION?.trim();
    const fromConfig = (config as any).QDRANT_COLLECTION?.trim();
    return (fromEnv || fromConfig || 'professor').trim() || 'professor';
}

/**
 * Estratégia Enterprise:
 * - Por padrão, NÃO filtra no Qdrant (score_threshold desligado).
 * - Quem decide aprovação é o Evidence Gate no Processor (topScore/mustCoverage).
 *
 * Se você quiser ligar filtro no Qdrant:
 * - defina QDRANT_SCORE_THRESHOLD > 0 (ex: 0.55 ou 0.62)
 * - se QDRANT_SCORE_THRESHOLD <= 0 => não envia score_threshold
 */
function resolveScoreThreshold(): number {
    const rawEnv = process.env.QDRANT_SCORE_THRESHOLD;
    const rawCfg = (config as any).QDRANT_SCORE_THRESHOLD;

    const raw = rawEnv ?? rawCfg;

    // ✅ default: 0 (desliga filtro no Qdrant)
    if (raw === undefined || raw === null || String(raw).trim() === '') return 0;

    const n = Number(raw);
    if (!Number.isFinite(n)) return 0;

    return clamp01(n);
}

/**
 * Busca vetorial no Qdrant
 */
export const searchQdrant = async (
    embedding: number[],
    topK = 8
): Promise<QdrantSearchResult[]> => {
    const collection = resolveCollection();
    const scoreThreshold = resolveScoreThreshold();

    // Só aplica threshold se > 0
    const thresholdApplied = scoreThreshold > 0;

    const body: any = {
        vector: embedding,
        limit: topK,
        with_payload: true,
        with_vector: false,
    };

    if (thresholdApplied) {
        body.score_threshold = scoreThreshold;
    }

    try {
        const response = await qdrantClient.post(
            `/collections/${collection}/points/search`,
            body
        );

        const results = response.data?.result ?? [];

        log('info', '[Qdrant] search success', {
            collection,
            topK,
            scoreThreshold,
            thresholdApplied,
            hits: Array.isArray(results) ? results.length : null,
            topScore: Array.isArray(results) && results[0] ? results[0].score : null,
        });

        return Array.isArray(results) ? results : [];
    } catch (error: any) {
        log('error', '[Qdrant] search failed', {
            message: error?.message,
            code: error?.code,
            collection,
            url: config.QDRANT_URL,
            responseStatus: error?.response?.status,
            responseData: error?.response?.data,
        });

        // Retorna array vazio para o Processor decidir fallback
        return [];
    }
};

/**
 * Healthcheck do Qdrant
 */
export const checkQdrantHealth = async (): Promise<boolean> => {
    try {
        const response = await qdrantClient.get('/healthz');
        return response.status === 200;
    } catch (error: any) {
        log('error', '[Qdrant] healthcheck failed', {
            message: error?.message,
            code: error?.code,
        });
        return false;
    }
};

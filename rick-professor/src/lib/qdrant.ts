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

export interface QdrantSearchOptions {
    workspaceId?: string;
    allowedCollectionIds?: string[];
}

const CANONICAL_COLLECTION_ID = 'rag_phase0';
const COLLECTION_ALIASES: Record<string, string> = {
    cvg_master_rag: CANONICAL_COLLECTION_ID,
    rickvet_documents: CANONICAL_COLLECTION_ID,
    [CANONICAL_COLLECTION_ID]: CANONICAL_COLLECTION_ID,
};

const normalizeCollectionId = (value: string): string => {
    const candidate = value.trim();
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(candidate)) {
        throw new Error('invalid_qdrant_collection');
    }
    return COLLECTION_ALIASES[candidate] || candidate;
};

export interface QdrantSearchRequest {
    vector: number[] | { name: string; vector: number[] };
    limit: number;
    with_payload: boolean;
    with_vector: boolean;
    score_threshold?: number;
    filter?: {
        must?: Array<Record<string, unknown>>;
        should?: Array<Record<string, unknown>>;
        min_should?: number;
    };
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
    return normalizeCollectionId((fromEnv || fromConfig || CANONICAL_COLLECTION_ID).trim() || CANONICAL_COLLECTION_ID);
}

function resolveTrustedWorkspace(options: QdrantSearchOptions): string {
    const configured = process.env.QDRANT_WORKSPACE_ID ?? (config as any).QDRANT_WORKSPACE_ID;
    const workspace = options.workspaceId?.trim() || String(configured || '').trim();
    if (!workspace) throw new Error('missing_qdrant_workspace_scope');
    return workspace;
}

function resolveAllowedCollectionIds(options: QdrantSearchOptions): string[] {
    const configured = process.env.QDRANT_ALLOWED_COLLECTION_IDS ?? (config as any).QDRANT_ALLOWED_COLLECTION_IDS;
    const raw = options.allowedCollectionIds !== undefined
        ? options.allowedCollectionIds
        : String(configured || '').split(',');
    const normalized = raw
        .map((value) => String(value).trim())
        .filter(Boolean)
        .map((value) => value === '*' ? value : normalizeCollectionId(value));
    if (normalized.length === 0) throw new Error('missing_qdrant_collection_scope');
    return normalized;
}

interface TrustedQdrantScope {
    workspaceId: string;
    allowedCollectionIds: string[];
}

const SAFE_PAYLOAD_KEYS = new Set([
    'text',
    'source',
    'doc_key',
    'filename',
    'title',
    'section',
    'document_id',
    'chunk_id',
    'checksum_sha256',
    'document_version',
    'page_start',
    'page_end',
    'workspace_id',
    'collection_id',
]);

function resolveTrustedScope(options: QdrantSearchOptions = {}): TrustedQdrantScope {
    const workspaceId = resolveTrustedWorkspace(options);
    const configuredCollectionIds = resolveAllowedCollectionIds(options);
    const physicalCollectionId = resolveCollection();
    const allowedCollectionIds = configuredCollectionIds.includes('*')
        ? [physicalCollectionId]
        : configuredCollectionIds;

    return { workspaceId, allowedCollectionIds };
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sanitizePayload(payload: Record<string, unknown>, workspaceId: string, collectionId: string): Record<string, unknown> {
    const sanitized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(payload)) {
        if (!SAFE_PAYLOAD_KEYS.has(key)) continue;
        if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) {
            sanitized[key] = value;
        }
    }
    sanitized.workspace_id = workspaceId;
    sanitized.collection_id = collectionId;
    return sanitized;
}

/**
 * Defense in depth for every adapter boundary: a Qdrant filter is not proof
 * that a response obeyed the requested tenant and logical collection scope.
 * Unscoped, malformed, or unknown payloads are discarded before evidence is
 * evaluated or included in a model prompt.
 */
export const filterTrustedQdrantResults = (
    results: unknown,
    options: QdrantSearchOptions = {}
): QdrantSearchResult[] => {
    const scope = resolveTrustedScope(options);
    if (!Array.isArray(results)) return [];

    const trusted: QdrantSearchResult[] = [];
    for (const result of results) {
        if (!isRecord(result)) continue;
        const id = result.id;
        const score = Number(result.score);
        const payload = result.payload;
        if ((typeof id !== 'string' && typeof id !== 'number') || String(id).trim().length === 0) continue;
        if (!Number.isFinite(score) || !isRecord(payload)) continue;

        const workspace = payload.workspace_id;
        const collection = payload.collection_id;
        if (typeof workspace !== 'string' || workspace.trim() !== scope.workspaceId) continue;
        if (typeof collection !== 'string') continue;

        let normalizedCollection: string;
        try {
            normalizedCollection = normalizeCollectionId(collection);
        } catch {
            continue;
        }
        if (!scope.allowedCollectionIds.includes(normalizedCollection)) continue;

        trusted.push({
            id,
            score,
            payload: sanitizePayload(payload, scope.workspaceId, normalizedCollection),
        });
    }
    return trusted;
};

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
export const buildQdrantSearchRequest = (
    embedding: number[],
    topK = 8,
    options: QdrantSearchOptions = {}
): QdrantSearchRequest => {
    const scoreThreshold = resolveScoreThreshold();
    const body: QdrantSearchRequest = {
        // The CVG contract uses named vectors. Keeping the name in the request
        // prevents an adapter from accidentally querying a different vector.
        vector: { name: 'dense', vector: embedding },
        limit: topK,
        with_payload: true,
        with_vector: false,
    };

    if (scoreThreshold > 0) {
        body.score_threshold = scoreThreshold;
    }

    const scope = resolveTrustedScope(options);
    // Both constraints are mandatory. The collection condition is kept as a
    // plain must clause because Qdrant 1.7 rejects nested should/min_should.
    body.filter = {
        must: [
            { key: 'workspace_id', match: { value: scope.workspaceId } },
            { key: 'collection_id', match: { any: scope.allowedCollectionIds } },
        ],
    };

    return body;
};

export const searchQdrant = async (
    embedding: number[],
    topK = 8,
    options: QdrantSearchOptions = {}
): Promise<QdrantSearchResult[]> => {
    const collection = resolveCollection();
    const body = buildQdrantSearchRequest(embedding, topK, options);
    const thresholdApplied = body.score_threshold !== undefined;

    try {
        const response = await qdrantClient.post(
            `/collections/${collection}/points/search`,
            body
        );

        const results = response.data?.result ?? [];
        const trustedResults = filterTrustedQdrantResults(results, options);

        log('info', '[Qdrant] search success', {
            collection,
            topK,
            scoreThreshold: body.score_threshold ?? 0,
            thresholdApplied,
            hits: trustedResults.length,
            rejectedHits: Array.isArray(results) ? results.length - trustedResults.length : null,
            topScore: trustedResults[0] ? trustedResults[0].score : null,
        });

        return trustedResults;
    } catch (error: any) {
        log('error', '[Qdrant] search failed', {
            message: 'qdrant_request_failed',
            code: error?.code,
            collection,
            responseStatus: error?.response?.status,
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
            message: 'qdrant_healthcheck_failed',
            code: error?.code,
        });
        return false;
    }
};

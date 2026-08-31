import OpenAI from 'openai';
import { randomUUID } from 'crypto';
import { config } from '../config';
import { log } from './logging';

export type ProviderErrorCode =
    | 'timeout'
    | 'unavailable'
    | 'rate_limit'
    | 'server_error'
    | 'malformed_response'
    | 'missing_field'
    | 'invalid_json'
    | 'invalid_model'
    | 'embedding_dimension_mismatch'
    | 'model_not_found'
    | 'http_error'
    | 'invalid_configuration'
    | 'internal_error';

export interface ProviderErrorSummary {
    code: ProviderErrorCode;
    operation: string;
    correlationId: string;
    attempts: number;
    retryable: boolean;
    status?: number;
}

interface ProviderErrorInput {
    code: ProviderErrorCode;
    operation: string;
    correlationId: string;
    attempts: number;
    retryable: boolean;
    status?: number;
}

/**
 * Safe, serializable provider failure. Raw response bodies, request URLs,
 * credentials, and causes intentionally never become part of this error.
 */
export class ProviderError extends Error {
    readonly code: ProviderErrorCode;
    readonly operation: string;
    readonly correlationId: string;
    readonly attempts: number;
    readonly retryable: boolean;
    readonly status?: number;

    constructor(input: ProviderErrorInput) {
        super(`provider_${input.code} (${input.correlationId})`);
        this.name = 'ProviderError';
        this.code = input.code;
        this.operation = input.operation;
        this.correlationId = input.correlationId;
        this.attempts = input.attempts;
        this.retryable = input.retryable;
        this.status = input.status;
        Object.setPrototypeOf(this, new.target.prototype);
    }

    toJSON(): ProviderErrorSummary {
        const summary: ProviderErrorSummary = {
            code: this.code,
            operation: this.operation,
            correlationId: this.correlationId,
            attempts: this.attempts,
            retryable: this.retryable,
        };
        if (this.status !== undefined) summary.status = this.status;
        return summary;
    }
}

export const isProviderError = (error: unknown): error is ProviderError =>
    error instanceof ProviderError;

export const summarizeProviderError = (error: unknown): ProviderErrorSummary | null =>
    isProviderError(error) ? error.toJSON() : null;

export const PROVIDER_MAX_ATTEMPTS = 3;
const MAX_RESPONSE_CHARS = 1_000_000;
const RETRYABLE_CODES = new Set<ProviderErrorCode>([
    'timeout',
    'unavailable',
    'rate_limit',
    'server_error',
]);

const openai = new OpenAI({
    apiKey: config.OPENAI_API_KEY,
    baseURL: config.OPENAI_BASE_URL,
    timeout: config.OPENAI_TIMEOUT_MS,
});

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

const providerError = (
    code: ProviderErrorCode,
    operation: string,
    correlationId: string,
    attempts: number,
    status?: number,
): ProviderError => new ProviderError({
    code,
    operation,
    correlationId,
    attempts,
    retryable: RETRYABLE_CODES.has(code),
    status,
});

const withAttempts = (error: ProviderError, attempts: number): ProviderError => new ProviderError({
    code: error.code,
    operation: error.operation,
    correlationId: error.correlationId,
    attempts,
    retryable: error.retryable,
    status: error.status,
});

const resolvePositiveInteger = (
    envName: string,
    configured: number,
    allowZero = false,
): number => {
    const raw = process.env[envName];
    if (raw === undefined) return configured;
    const value = Number(raw);
    const valid = Number.isInteger(value) && (allowZero ? value >= 0 : value > 0);
    return valid ? value : configured;
};

const resolveBaseUrl = (correlationId: string): string => {
    const raw = process.env.OPENAI_BASE_URL?.trim() || config.OPENAI_BASE_URL;
    try {
        const url = new URL(raw);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('unsupported_protocol');
        return raw.replace(/\/+$/, '');
    } catch {
        throw providerError('invalid_configuration', 'provider_request', correlationId, 0);
    }
};

const classifyTransportError = (
    error: unknown,
    operation: string,
    correlationId: string,
    attempts: number,
): ProviderError => {
    const candidate = isRecord(error) ? error : {};
    const cause = isRecord(candidate.cause) ? candidate.cause : {};
    const name = typeof candidate.name === 'string' ? candidate.name : '';
    const code = typeof candidate.code === 'string'
        ? candidate.code
        : typeof cause.code === 'string' ? cause.code : '';

    if (
        name === 'AbortError' ||
        code === 'ETIMEDOUT' ||
        code === 'UND_ERR_CONNECT_TIMEOUT' ||
        code === 'UND_ERR_HEADERS_TIMEOUT'
    ) {
        return providerError('timeout', operation, correlationId, attempts);
    }

    return providerError('unavailable', operation, correlationId, attempts);
};

const errorBodyIndicatesMissingModel = (body: unknown): boolean => {
    if (!isRecord(body)) return false;
    const details = isRecord(body.error) ? body.error : body;
    const code = typeof details.code === 'string' ? details.code.toLowerCase() : '';
    const message = typeof details.message === 'string' ? details.message.toLowerCase() : '';
    return code === 'model_not_found' || /model[\s_-]+.*not[\s_-]+found/.test(message);
};

const classifyHttpError = (
    responseStatus: number,
    responseText: string,
    operation: string,
    correlationId: string,
    attempts: number,
): ProviderError => {
    let body: unknown;
    try {
        body = responseText ? JSON.parse(responseText) : undefined;
    } catch {
        body = undefined;
    }

    if (responseStatus === 404 && errorBodyIndicatesMissingModel(body)) {
        return providerError('model_not_found', operation, correlationId, attempts, responseStatus);
    }
    if (responseStatus === 429) {
        return providerError('rate_limit', operation, correlationId, attempts, responseStatus);
    }
    if (responseStatus >= 500) {
        return providerError('server_error', operation, correlationId, attempts, responseStatus);
    }
    return providerError('http_error', operation, correlationId, attempts, responseStatus);
};

const requestJson = async (
    operation: string,
    endpoint: string,
    body: Record<string, unknown>,
    correlationId: string,
    attempts: number,
): Promise<unknown> => {
    const controller = new AbortController();
    const timeoutMs = resolvePositiveInteger('OPENAI_TIMEOUT_MS', config.OPENAI_TIMEOUT_MS);
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    timer.unref?.();

    try {
        const baseUrl = resolveBaseUrl(correlationId);
        let response: Response;
        try {
            response = await fetch(`${baseUrl}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${config.OPENAI_API_KEY}`,
                    'x-correlation-id': correlationId,
                },
                body: JSON.stringify(body),
                signal: controller.signal,
            });
        } catch (error) {
            throw classifyTransportError(error, operation, correlationId, attempts);
        }

        let responseText: string;
        try {
            responseText = await response.text();
        } catch (error) {
            throw classifyTransportError(error, operation, correlationId, attempts);
        }

        if (!response.ok) {
            throw classifyHttpError(response.status, responseText, operation, correlationId, attempts);
        }
        if (responseText.length > MAX_RESPONSE_CHARS) {
            throw providerError('malformed_response', operation, correlationId, attempts, response.status);
        }

        try {
            return JSON.parse(responseText);
        } catch {
            throw providerError('invalid_json', operation, correlationId, attempts, response.status);
        }
    } finally {
        clearTimeout(timer);
    }
};

const toSafeProviderError = (
    error: unknown,
    operation: string,
    correlationId: string,
    attempts: number,
): ProviderError => {
    if (isProviderError(error)) return withAttempts(error, attempts);
    return providerError('internal_error', operation, correlationId, attempts);
};

async function withRetry<T>(
    operation: string,
    correlationId: string,
    fn: (attempts: number) => Promise<T>,
): Promise<T> {
    let attempts = 0;

    while (attempts < PROVIDER_MAX_ATTEMPTS) {
        attempts++;
        try {
            return await fn(attempts);
        } catch (error) {
            const safeError = toSafeProviderError(error, operation, correlationId, attempts);
            if (!safeError.retryable || attempts >= PROVIDER_MAX_ATTEMPTS) {
                log('error', '[OpenAI] provider request failed', safeError.toJSON());
                throw safeError;
            }

            const delay = resolvePositiveInteger(
                'OPENAI_RETRY_DELAY_MS',
                config.OPENAI_RETRY_DELAY_MS,
                true,
            ) * Math.pow(2, attempts - 1);
            log('warn', '[OpenAI] provider request retry', {
                operation,
                code: safeError.code,
                attempt: attempts,
                maxAttempts: PROVIDER_MAX_ATTEMPTS,
                correlationId,
                delayMs: delay,
            });
            await sleep(delay);
        }
    }

    throw providerError('internal_error', operation, correlationId, attempts);
}

const validateModel = (model: unknown, operation: string, correlationId: string): string => {
    if (typeof model !== 'string' || model.trim().length === 0) {
        throw providerError('invalid_model', operation, correlationId, 0);
    }
    return model.trim();
};

const extractEmbedding = (
    body: unknown,
    correlationId: string,
    attempts: number,
): number[] => {
    if (!isRecord(body)) throw providerError('malformed_response', 'embeddings', correlationId, attempts);
    if (!Object.prototype.hasOwnProperty.call(body, 'data')) {
        throw providerError('missing_field', 'embeddings', correlationId, attempts);
    }
    if (!Array.isArray(body.data)) {
        throw providerError('malformed_response', 'embeddings', correlationId, attempts);
    }
    if (body.data.length === 0 || !isRecord(body.data[0])) {
        throw providerError('missing_field', 'embeddings', correlationId, attempts);
    }

    const item = body.data[0];
    if (!Object.prototype.hasOwnProperty.call(item, 'embedding')) {
        throw providerError('missing_field', 'embeddings', correlationId, attempts);
    }
    if (!Array.isArray(item.embedding) || !item.embedding.every((value) => (
        typeof value === 'number' && Number.isFinite(value)
    ))) {
        throw providerError('malformed_response', 'embeddings', correlationId, attempts);
    }
    if (item.embedding.length !== config.EMBEDDING_DIMENSION) {
        throw providerError('embedding_dimension_mismatch', 'embeddings', correlationId, attempts);
    }
    return item.embedding as number[];
};

const extractChatContent = (
    body: unknown,
    correlationId: string,
    attempts: number,
): string => {
    if (!isRecord(body)) throw providerError('malformed_response', 'chat_completion', correlationId, attempts);
    if (!Object.prototype.hasOwnProperty.call(body, 'choices')) {
        throw providerError('missing_field', 'chat_completion', correlationId, attempts);
    }
    if (!Array.isArray(body.choices)) {
        throw providerError('malformed_response', 'chat_completion', correlationId, attempts);
    }
    if (body.choices.length === 0 || !isRecord(body.choices[0])) {
        throw providerError('missing_field', 'chat_completion', correlationId, attempts);
    }

    const choice = body.choices[0];
    if (!Object.prototype.hasOwnProperty.call(choice, 'message')) {
        throw providerError('missing_field', 'chat_completion', correlationId, attempts);
    }
    if (!isRecord(choice.message)) {
        throw providerError('malformed_response', 'chat_completion', correlationId, attempts);
    }
    if (!Object.prototype.hasOwnProperty.call(choice.message, 'content')) {
        throw providerError('missing_field', 'chat_completion', correlationId, attempts);
    }
    if (typeof choice.message.content !== 'string' || choice.message.content.trim().length === 0) {
        throw providerError('missing_field', 'chat_completion', correlationId, attempts);
    }
    return choice.message.content;
};

export const getEmbedding = async (text: string): Promise<number[]> => {
    const correlationId = randomUUID();
    const model = validateModel(config.EMBEDDING_MODEL, 'embeddings', correlationId);

    return withRetry('embeddings', correlationId, async (attempts) => {
        const body = await requestJson(
            'embeddings',
            '/embeddings',
            { model, input: text },
            correlationId,
            attempts,
        );
        return extractEmbedding(body, correlationId, attempts);
    });
};

export const chatCompletion = async (
    model: string,
    messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[],
    temperature = 0.2,
    responseFormat: OpenAI.Chat.Completions.ChatCompletionCreateParams['response_format'] = { type: 'text' },
): Promise<string> => {
    const correlationId = randomUUID();
    const normalizedModel = validateModel(model, 'chat_completion', correlationId);

    return withRetry('chat_completion', correlationId, async (attempts) => {
        const body = await requestJson(
            'chat_completion',
            '/chat/completions',
            {
                model: normalizedModel,
                messages,
                temperature,
                response_format: responseFormat,
            },
            correlationId,
            attempts,
        );
        return extractChatContent(body, correlationId, attempts);
    });
};

export default openai;

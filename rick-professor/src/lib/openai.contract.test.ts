import assert from 'node:assert/strict';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import test, { type TestContext } from 'node:test';
import type { ProcessorDependencies } from '../core/processor';
import type { QdrantSearchResult } from './qdrant';

const LOOPBACK_HOST = '127.0.0.1';
const SYNTHETIC_API_KEY = 'contract-test-key';
const RAW_SECRET_SENTINEL = 'provider-contract-secret';
const RAW_STACK_SENTINEL = 'Error: synthetic provider stack';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const EMBEDDING_DIMENSION = 1536;

type ProviderModule = typeof import('./openai');
type ProcessorModule = typeof import('../core/processor');

interface RequestRecord {
    path: string;
    kind: string;
    model?: string;
    correlationId: string;
    attempt: number;
    authorizationPresent: boolean;
    messageText?: string;
}

interface CaseObservation {
    code?: string;
    attempts?: number;
    requestCount?: number;
    correlationId?: string;
    assertions?: string[];
}

interface CaseArtifact extends CaseObservation {
    name: string;
    status: 'observed' | 'failed';
    failure?: 'assertion_failed' | 'setup_failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

const readJsonBody = async (request: IncomingMessage): Promise<unknown> => {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(Buffer.from(chunk));
    const raw = Buffer.concat(chunks).toString('utf8');
    try {
        return JSON.parse(raw);
    } catch {
        return undefined;
    }
};

const sendJson = (response: ServerResponse, status: number, body: unknown): void => {
    response.statusCode = status;
    response.setHeader('content-type', 'application/json');
    response.setHeader('connection', 'close');
    response.end(JSON.stringify(body));
};

const chatResponse = (content: string): Record<string, unknown> => ({
    id: 'chatcmpl-contract',
    object: 'chat.completion',
    choices: [
        {
            index: 0,
            message: { role: 'assistant', content },
            finish_reason: 'stop',
        },
    ],
});

const embeddingResponse = (embedding: number[]): Record<string, unknown> => ({
    object: 'list',
    data: [{ object: 'embedding', index: 0, embedding }],
    model: 'contract-embedding',
});

const contractEmbedding = (): number[] => {
    const embedding = new Array<number>(EMBEDDING_DIMENSION).fill(0);
    embedding[0] = 1;
    return embedding;
};

const listenOnLoopback = async (server: Server): Promise<number> => {
    await new Promise<void>((resolveListen, rejectListen) => {
        server.once('error', rejectListen);
        server.listen(0, LOOPBACK_HOST, () => resolveListen());
    });
    const address = server.address();
    assert.ok(address && typeof address === 'object');
    return address.port;
};

const closeServer = async (server: Server): Promise<void> => {
    if (!server.listening) return;
    server.closeAllConnections?.();
    await new Promise<void>((resolveClose, rejectClose) => {
        server.close((error) => error ? rejectClose(error) : resolveClose());
    });
};

const assertSafeProviderError = (
    error: unknown,
    provider: ProviderModule,
    expectedCode: ProviderModule['ProviderError']['prototype']['code'],
): ProviderModule['ProviderError']['prototype'] => {
    assert.ok(error instanceof provider.ProviderError);
    assert.equal(error.code, expectedCode);
    assert.match(error.correlationId, UUID_PATTERN);
    assert.equal(String(error).includes(RAW_SECRET_SENTINEL), false);
    assert.equal(String(error).includes(RAW_STACK_SENTINEL), false);

    const serialized = JSON.stringify(error);
    assert.equal(serialized.includes(RAW_SECRET_SENTINEL), false);
    assert.equal(serialized.includes(RAW_STACK_SENTINEL), false);
    assert.equal(serialized.includes('stack'), false);
    assert.equal(serialized.includes('Bearer '), false);
    return error;
};

const runContractCase = async (
    context: TestContext,
    caseArtifacts: CaseArtifact[],
    name: string,
    execute: () => Promise<CaseObservation>,
): Promise<void> => {
    await context.test(name, async () => {
        try {
            const observation = await execute();
            caseArtifacts.push({ name, status: 'observed', ...observation });
        } catch {
            caseArtifacts.push({ name, status: 'failed', failure: 'assertion_failed' });
            throw new Error(`contract case failed: ${name}`);
        }
    });
};

test('PH06-PROVIDER exercises the real OpenAI-compatible HTTP boundary', async (t) => {
    process.env.NODE_ENV = 'test';
    process.env.OPENAI_API_KEY = SYNTHETIC_API_KEY;
    process.env.OPENAI_TIMEOUT_MS = '1000';
    process.env.OPENAI_RETRY_DELAY_MS = '1';

    const requests: RequestRecord[] = [];
    const attemptByCorrelation = new Map<string, number>();
    const pendingTimeouts = new Set<ReturnType<typeof setTimeout>>();

    const server = createServer((request, response) => {
        void (async () => {
            const body = await readJsonBody(request);
            const path = request.url || '';
            const bodyRecord = isRecord(body) ? body : {};
            const model = typeof bodyRecord.model === 'string' ? bodyRecord.model : undefined;
            const correlationId = typeof request.headers['x-correlation-id'] === 'string'
                ? request.headers['x-correlation-id']
                : '';
            const attempt = (attemptByCorrelation.get(correlationId) || 0) + 1;
            attemptByCorrelation.set(correlationId, attempt);
            const messageText = Array.isArray(bodyRecord.messages)
                ? JSON.stringify(bodyRecord.messages)
                : undefined;
            const input = typeof bodyRecord.input === 'string' ? bodyRecord.input : undefined;

            const record: RequestRecord = {
                path,
                kind: model || 'embedding',
                model,
                correlationId,
                attempt,
                authorizationPresent: typeof request.headers.authorization === 'string'
                    && request.headers.authorization.startsWith('Bearer '),
                messageText,
            };
            requests.push(record);

            if (path === '/v1/embeddings') {
                if (input === 'case-embedding-dimension-mismatch') {
                    sendJson(response, 200, embeddingResponse([0.1, 0.2, 0.3]));
                    return;
                }
                sendJson(response, 200, embeddingResponse(contractEmbedding()));
                return;
            }

            if (path !== '/v1/chat/completions') {
                sendJson(response, 404, { error: { code: 'route_not_found' } });
                return;
            }

            if (model === 'case-timeout') {
                const timeout = setTimeout(() => {
                    pendingTimeouts.delete(timeout);
                    if (!response.writableEnded) sendJson(response, 200, chatResponse('late response'));
                }, 500);
                pendingTimeouts.add(timeout);
                response.on('close', () => {
                    clearTimeout(timeout);
                    pendingTimeouts.delete(timeout);
                });
                return;
            }
            if (model === 'case-unavailable') {
                request.socket.destroy();
                return;
            }
            if (model === 'case-429') {
                sendJson(response, 429, {
                    error: { code: 'rate_limit', message: `${RAW_SECRET_SENTINEL} ${RAW_STACK_SENTINEL}` },
                });
                return;
            }
            if (model === 'case-500' || messageText?.includes('CONTRACT_PROVIDER_FAILURE')) {
                sendJson(response, 500, {
                    error: { code: 'server_error', message: `${RAW_SECRET_SENTINEL} ${RAW_STACK_SENTINEL}` },
                });
                return;
            }
            if (model === 'case-malformed') {
                sendJson(response, 200, { choices: 'not-an-array' });
                return;
            }
            if (model === 'case-missing-field') {
                sendJson(response, 200, { choices: [{ message: { role: 'assistant' } }] });
                return;
            }
            if (model === 'case-invalid-json') {
                response.statusCode = 200;
                response.setHeader('content-type', 'application/json');
                response.setHeader('connection', 'close');
                response.end(`not-json ${RAW_SECRET_SENTINEL} ${RAW_STACK_SENTINEL}`);
                return;
            }
            if (model === 'case-model-not-found') {
                sendJson(response, 404, {
                    error: {
                        code: 'model_not_found',
                        message: `The requested model was not found ${RAW_SECRET_SENTINEL}`,
                    },
                });
                return;
            }
            if (model === 'case-success') {
                sendJson(response, 200, chatResponse('synthetic provider success'));
                return;
            }

            if (messageText?.includes('CONTRACT_PROVIDER_FAILURE')) {
                sendJson(response, 500, {
                    error: { code: 'server_error', message: `${RAW_SECRET_SENTINEL} ${RAW_STACK_SENTINEL}` },
                });
                return;
            }
            if (messageText?.includes('PRÉ-PROCESSADOR')) {
                sendJson(response, 200, chatResponse(JSON.stringify({
                    canonical_question_ptbr: 'O que fazer diante da parvovirose?',
                    primary_focus: 'parvovirose',
                    intent: 'protocolo',
                    expects_numeric: false,
                    must_include_terms: ['parvovirose'],
                    input: 'parvovirose canine protocol',
                })));
                return;
            }
            if (messageText?.includes('PLANNER CLÍNICO')) {
                sendJson(response, 200, chatResponse(JSON.stringify({
                    gate_mode: 'approved',
                    resumo_evidencias: [{
                        id: 'fake-provider-id',
                        payload: { text: 'FABRICATED_PROVIDER_CITATION' },
                    }],
                    response_sections: ['direct_answer', 'warnings'],
                })));
                return;
            }
            if (messageText?.includes('professor universitário')) {
                sendJson(response, 200, chatResponse(
                    'direct_answer: A orientação está fundamentada no documento recuperado [E1].\n'
                    + '📚 Evidências: synthetic-guideline.pdf, p. 7-8',
                ));
                return;
            }

            sendJson(response, 500, { error: { code: 'unexpected_contract_request' } });
        })().catch(() => {
            if (!response.headersSent) sendJson(response, 500, { error: { code: 'harness_failure' } });
            else response.destroy();
        });
    });

    let provider: ProviderModule | undefined;
    let processor: ProcessorModule | undefined;
    const caseArtifacts: CaseArtifact[] = [];
    let port: number | undefined;

    try {
        port = await listenOnLoopback(server);
        process.env.OPENAI_BASE_URL = `http://${LOOPBACK_HOST}:${port}/v1`;
        provider = await import('./openai');
        processor = await import('../core/processor');

        const chatMessages = [{ role: 'user', content: 'synthetic contract request' }] as const;
        const requestCount = (model: string): number => requests.filter((request) => (
            request.path === '/v1/chat/completions' && request.model === model
        )).length;
        const assertStableRetry = (model: string, expectedCorrelationId: string): void => {
            const observed = requests.filter((request) => (
                request.path === '/v1/chat/completions' && request.model === model
            ));
            assert.deepEqual(observed.map((request) => request.attempt), [1, 2, 3]);
            assert.deepEqual([...new Set(observed.map((request) => request.correlationId))], [expectedCorrelationId]);
        };

        await runContractCase(t, caseArtifacts, 'success', async () => {
            const content = await provider!.chatCompletion('case-success', [...chatMessages]);
            assert.equal(content, 'synthetic provider success');
            const observed = requests.find((request) => request.model === 'case-success');
            assert.ok(observed);
            assert.equal(observed.authorizationPresent, true);
            assert.match(observed.correlationId, UUID_PATTERN);
            assert.equal(observed.attempt, 1);
            assert.equal(requestCount('case-success'), 1);
            return {
                code: 'success',
                attempts: 1,
                requestCount: 1,
                correlationId: observed.correlationId,
                assertions: ['real_http', 'authorization_present', 'correlation_header'],
            };
        });

        await runContractCase(t, caseArtifacts, 'timeout', async () => {
            let caught: unknown;
            const normalTimeout = process.env.OPENAI_TIMEOUT_MS;
            process.env.OPENAI_TIMEOUT_MS = '50';
            try {
                await provider!.chatCompletion('case-timeout', [...chatMessages]);
            } catch (error) {
                caught = error;
            } finally {
                if (normalTimeout === undefined) delete process.env.OPENAI_TIMEOUT_MS;
                else process.env.OPENAI_TIMEOUT_MS = normalTimeout;
            }
            const error = assertSafeProviderError(caught, provider!, 'timeout');
            assert.equal(error.attempts, 3);
            assert.equal(requestCount('case-timeout'), 3);
            assertStableRetry('case-timeout', error.correlationId);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-timeout'),
                correlationId: error.correlationId,
                assertions: ['safe_error', 'bounded_retry', 'stable_correlation'],
            };
        });

        await runContractCase(t, caseArtifacts, 'unavailable', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-unavailable', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'unavailable');
            assert.equal(error.attempts, 3);
            assert.equal(requestCount('case-unavailable'), 3);
            assertStableRetry('case-unavailable', error.correlationId);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-unavailable'),
                correlationId: error.correlationId,
                assertions: ['safe_error', 'bounded_retry', 'stable_correlation'],
            };
        });

        await runContractCase(t, caseArtifacts, '429 rate limit', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-429', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'rate_limit');
            assert.equal(error.status, 429);
            assert.equal(error.attempts, 3);
            assert.equal(requestCount('case-429'), 3);
            assertStableRetry('case-429', error.correlationId);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-429'),
                correlationId: error.correlationId,
                assertions: ['status_classification', 'safe_error', 'bounded_retry', 'stable_correlation'],
            };
        });

        await runContractCase(t, caseArtifacts, '500 server error', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-500', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'server_error');
            assert.equal(error.status, 500);
            assert.equal(error.attempts, 3);
            assert.equal(requestCount('case-500'), 3);
            assertStableRetry('case-500', error.correlationId);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-500'),
                correlationId: error.correlationId,
                assertions: ['status_classification', 'safe_error', 'bounded_retry', 'stable_correlation'],
            };
        });

        await runContractCase(t, caseArtifacts, 'malformed response', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-malformed', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'malformed_response');
            assert.equal(error.attempts, 1);
            assert.equal(requestCount('case-malformed'), 1);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-malformed'),
                correlationId: error.correlationId,
                assertions: ['schema_validation', 'no_retry'],
            };
        });

        await runContractCase(t, caseArtifacts, 'missing field', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-missing-field', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'missing_field');
            assert.equal(error.attempts, 1);
            assert.equal(requestCount('case-missing-field'), 1);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-missing-field'),
                correlationId: error.correlationId,
                assertions: ['schema_validation', 'no_retry'],
            };
        });

        await runContractCase(t, caseArtifacts, 'invalid JSON', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-invalid-json', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'invalid_json');
            assert.equal(error.attempts, 1);
            assert.equal(requestCount('case-invalid-json'), 1);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-invalid-json'),
                correlationId: error.correlationId,
                assertions: ['json_validation', 'safe_error', 'no_retry'],
            };
        });

        await runContractCase(t, caseArtifacts, 'empty model', async () => {
            const before = requests.length;
            let caught: unknown;
            try {
                await provider!.chatCompletion('   ', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'invalid_model');
            assert.equal(error.attempts, 0);
            assert.equal(requests.length, before);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: 0,
                correlationId: error.correlationId,
                assertions: ['local_validation', 'no_network_call'],
            };
        });

        await runContractCase(t, caseArtifacts, 'embedding dimension mismatch', async () => {
            let caught: unknown;
            try {
                await provider!.getEmbedding('case-embedding-dimension-mismatch');
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'embedding_dimension_mismatch');
            assert.equal(error.attempts, 1);
            const observed = requests.find((request) => request.path === '/v1/embeddings');
            assert.ok(observed);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: 1,
                correlationId: error.correlationId,
                assertions: ['embedding_schema_validation', 'dimension_validation'],
            };
        });

        await runContractCase(t, caseArtifacts, 'model not found', async () => {
            let caught: unknown;
            try {
                await provider!.chatCompletion('case-model-not-found', [...chatMessages]);
            } catch (error) {
                caught = error;
            }
            const error = assertSafeProviderError(caught, provider!, 'model_not_found');
            assert.equal(error.status, 404);
            assert.equal(error.attempts, 1);
            assert.equal(requestCount('case-model-not-found'), 1);
            return {
                code: error.code,
                attempts: error.attempts,
                requestCount: requestCount('case-model-not-found'),
                correlationId: error.correlationId,
                assertions: ['status_classification', 'no_retry', 'safe_error'],
            };
        });

        await runContractCase(t, caseArtifacts, 'document to cited answer flow with real provider HTTP', async () => {
            const document = {
                id: 'synthetic-document-001',
                text: 'Parvovirose canina: isolamento, suporte e monitorização são essenciais.',
                source: 'synthetic-guideline.pdf',
                pageStart: 7,
                pageEnd: 8,
            };
            let indexedVector: number[] = [];
            let queriedVector: number[] = [];
            let searchCalls = 0;
            let indexedPoint: QdrantSearchResult | undefined;

            const indexDocument = async (): Promise<void> => {
                indexedVector = await provider!.getEmbedding(document.text);
                assert.equal(indexedVector.length, EMBEDDING_DIMENSION);
                indexedPoint = {
                    id: document.id,
                    score: 0.94,
                    payload: {
                        text: document.text,
                        source: document.source,
                        doc_key: document.id,
                        page_start: document.pageStart,
                        page_end: document.pageEnd,
                        workspace_id: 'contract-workspace',
                        collection_id: 'contract-collection',
                    },
                };
            };

            const queryIndex = async (vector: number[]): Promise<QdrantSearchResult[]> => {
                searchCalls++;
                queriedVector = vector;
                assert.equal(vector.length, indexedVector.length);
                if (!indexedPoint || vector.length === 0) return [];
                let dot = 0;
                let indexedNorm = 0;
                let queriedNorm = 0;
                for (let index = 0; index < vector.length; index++) {
                    dot += indexedVector[index] * vector[index];
                    indexedNorm += indexedVector[index] ** 2;
                    queriedNorm += vector[index] ** 2;
                }
                const score = indexedNorm > 0 && queriedNorm > 0
                    ? dot / (Math.sqrt(indexedNorm) * Math.sqrt(queriedNorm))
                    : 0;
                return score >= 0.5 ? [{ ...indexedPoint, score }] : [];
            };

            const sent: string[] = [];
            const history: string[] = [];
            const locks = new Map<string, string>();
            const releases: string[] = [];
            const flowLogs: unknown[] = [];
            const flowRequestStart = requests.length;
            const deps: ProcessorDependencies = {
                chatCompletion: provider!.chatCompletion,
                getEmbedding: provider!.getEmbedding,
                searchQdrant: async (vector) => queryIndex(vector),
                acquireLock: async (key, value) => {
                    if (locks.has(key)) return { acquired: false };
                    locks.set(key, value);
                    return { acquired: true };
                },
                releaseLock: async (key, value) => {
                    if (locks.get(key) !== value) return { deleted: false };
                    locks.delete(key);
                    releases.push(key);
                    return { deleted: true };
                },
                sendMessage: async (_chatId, message) => {
                    sent.push(message);
                },
                getChatHistory: async () => '',
                addChatMessage: async (conversationId, role, content) => {
                    history.push(`${conversationId}:${role}:${content}`);
                },
                logger: (...args) => {
                    flowLogs.push(args);
                },
            };

            await indexDocument();
            const result = await processor!.processMessage({
                text: 'Como conduzir um caso de parvovirose canina?',
                chatId: 'contract-chat',
                retrievalContext: {
                    workspaceId: 'contract-workspace',
                    allowedCollectionIds: ['contract-collection'],
                },
            }, deps);

            assert.equal(result.ok, true);
            assert.equal(result.mode, 'answer');
            assert.equal(result.replyText?.includes('[E1]'), true);
            assert.equal(result.replyText?.includes('synthetic-guideline.pdf'), true);
            assert.equal(result.replyText?.includes('FABRICATED_PROVIDER_CITATION'), false);
            assert.equal(sent.length, 1);
            assert.equal(sent[0].includes('[E1]'), true);
            assert.equal(sent[0].includes('FABRICATED_PROVIDER_CITATION'), false);
            assert.equal(history.length, 2);
            assert.equal(history[0].includes('user:'), true);
            assert.equal(history[1].includes('assistant:'), true);
            assert.equal(searchCalls, 1);
            assert.equal(indexedVector.length, EMBEDDING_DIMENSION);
            assert.equal(queriedVector.length, EMBEDDING_DIMENSION);
            assert.equal(releases.length, 1);
            assert.equal(locks.size, 0);
            assert.equal(flowLogs.some((entry) => JSON.stringify(entry).includes('FABRICATED_PROVIDER_CITATION')), false);

            const agentRequest = requests.find((request) => (
                request.path === '/v1/chat/completions'
                && request.messageText?.includes('RAG_CONTEXT')
            ));
            assert.ok(agentRequest);
            assert.equal(agentRequest.messageText?.includes('synthetic-guideline.pdf'), true);
            assert.equal(agentRequest.messageText?.includes(document.text), true);
            assert.equal(agentRequest.messageText?.includes('FABRICATED_PROVIDER_CITATION'), false);
            assert.equal(agentRequest.authorizationPresent, true);

            const providerRequests = requests.slice(flowRequestStart);
            assert.equal(providerRequests.length, 5);
            for (const request of providerRequests) {
                assert.match(request.correlationId, UUID_PATTERN);
                assert.equal(request.authorizationPresent, true);
            }

            const failureSent: string[] = [];
            const failureHistory: string[] = [];
            const failureLocks = new Map<string, string>();
            let failureReleases = 0;
            const failureLogs: string[] = [];
            const originalConsoleLog = console.log;
            console.log = (...args: unknown[]) => {
                failureLogs.push(args.map((arg) => String(arg)).join(' '));
            };
            let failureResult: Awaited<ReturnType<ProcessorModule['processMessage']>>;
            try {
                const failureDeps: ProcessorDependencies = {
                    ...deps,
                    acquireLock: async (key, value) => {
                        if (failureLocks.has(key)) return { acquired: false };
                        failureLocks.set(key, value);
                        return { acquired: true };
                    },
                    releaseLock: async (key, value) => {
                        if (failureLocks.get(key) !== value) return { deleted: false };
                        failureLocks.delete(key);
                        failureReleases++;
                        return { deleted: true };
                    },
                    sendMessage: async (_chatId, message) => {
                        failureSent.push(message);
                    },
                    addChatMessage: async (_conversationId, role, content) => {
                        failureHistory.push(`${role}:${content}`);
                    },
                    logger: (...args) => {
                        failureLogs.push(args.map((arg) => String(arg)).join(' '));
                    },
                };
                failureResult = await processor!.processMessage({
                    text: 'CONTRACT_PROVIDER_FAILURE',
                    chatId: 'contract-failure-chat',
                }, failureDeps);
            } finally {
                console.log = originalConsoleLog;
            }

            assert.equal(failureResult!.ok, false);
            assert.equal(failureResult!.mode, 'error');
            assert.equal(failureResult!.replyText, '🚨 Erro interno. Tente novamente em breve.');
            assert.equal(failureResult!.metadata?.error, 'provider_failure');
            assert.equal(failureResult!.metadata?.providerCode, 'server_error');
            assert.match(String(failureResult!.metadata?.correlationId), UUID_PATTERN);
            assert.equal(failureResult!.metadata?.attempts, 3);
            assert.equal(failureSent.length, 1);
            assert.equal(failureHistory.length, 0);
            assert.equal(failureReleases, 1);
            assert.equal(failureLocks.size, 0);
            assert.equal(JSON.stringify(failureResult).includes(RAW_SECRET_SENTINEL), false);
            assert.equal(JSON.stringify(failureResult).includes(RAW_STACK_SENTINEL), false);
            assert.equal(failureLogs.join('\n').includes(RAW_SECRET_SENTINEL), false);
            assert.equal(failureLogs.join('\n').includes(RAW_STACK_SENTINEL), false);

            const failureRequests = requests.filter((request) => request.messageText?.includes('CONTRACT_PROVIDER_FAILURE'));
            assert.equal(failureRequests.length, 3);
            assert.equal(new Set(failureRequests.map((request) => request.correlationId)).size, 1);

            return {
                code: 'success_and_safe_failure_cleanup',
                attempts: failureResult.metadata?.attempts,
                requestCount: providerRequests.length,
                correlationId: String(failureResult.metadata?.correlationId),
                assertions: [
                    'document_embedding_index',
                    'query_embedding_retrieval',
                    'grounded_citation',
                    'no_fake_citation',
                    'lock_release_success',
                    'lock_release_failure',
                    'state_integrity',
                    'safe_error_no_leak',
                ],
            };
        });
    } finally {
        for (const timeout of pendingTimeouts) clearTimeout(timeout);
        await closeServer(server);

        const artifact = {
            schema_version: 'phase-0.6-provider-contract.v1',
            task: 'PH06-PROVIDER',
            execution_status: 'observed',
            observed_at: new Date().toISOString(),
            environment: {
                node: process.version,
                bind_host: LOOPBACK_HOST,
                provider_base_url: port ? `http://${LOOPBACK_HOST}:${port}/v1` : null,
                synthetic_data: true,
                live_provider_called: false,
                max_provider_attempts: provider?.PROVIDER_MAX_ATTEMPTS ?? 3,
            },
            cases: caseArtifacts,
            http_observations: {
                requests: requests.map(({ path, kind, model, correlationId, attempt, authorizationPresent }) => ({
                    path,
                    kind,
                    model,
                    correlationId,
                    attempt,
                    authorizationPresent,
                })),
                correlation_ids: [...new Set(requests.map((request) => request.correlationId))],
            },
            limitations: [
                'The OpenAI-compatible server is a disposable local protocol fixture, not live provider quality evidence.',
                'Qdrant, Redis, and Telegram are faithful in-memory dependencies for the vertical contract flow.',
            ],
        };
        const artifactPath = resolve(__dirname, '../../test/artifacts/phase-0.6-provider-contract.json');
        await mkdir(dirname(artifactPath), { recursive: true });
        await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
    }
});

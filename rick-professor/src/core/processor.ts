import { PROMPTS } from './prompts';
import { chatCompletion as defaultChat, getEmbedding as defaultEmbed } from '../lib/openai';
import {
    searchQdrant as defaultSearch,
    filterTrustedQdrantResults,
    QdrantSearchOptions,
} from '../lib/qdrant';
import { acquireLock as defaultLock, releaseLock as defaultRelease, renewLock as defaultRenew } from '../lib/redis-lock';
import { sendMessage as defaultSend } from '../lib/telegram';
import { getChatHistory as defaultGetHistory, addChatMessage as defaultAddMsg } from '../lib/memory';
import { config } from '../config';
import { randomUUID } from 'crypto';
import { log } from '../lib/logging';
import { evaluateEvidence } from './evidence';
import { defaultPlannerOutput, parsePlannerOutput } from './planner-contract';

interface ProcessorInput {
    text: string;
    chatId: string;
    messageId?: number;
    fromId?: number;
    raw?: any;
    /** Trusted context assembled by an authenticated gateway/route. */
    retrievalContext?: QdrantSearchOptions;
}

export interface ProcessorDependencies {
    chatCompletion: typeof defaultChat;
    getEmbedding: typeof defaultEmbed;
    searchQdrant: typeof defaultSearch;
    acquireLock: typeof defaultLock;
    releaseLock?: typeof defaultRelease;
    renewLock?: typeof defaultRenew;
    sendMessage: typeof defaultSend;
    getChatHistory: typeof defaultGetHistory;
    addChatMessage: typeof defaultAddMsg;
    logger: typeof log;
}

export interface ProcessorResult {
    ok: boolean;
    conversationId: string;
    replyText?: string;
    mode: 'answer' | 'fallback' | 'empty' | 'locked' | 'error';
    metadata?: Record<string, any>;
}

const defaultDeps: ProcessorDependencies = {
    chatCompletion: defaultChat,
    getEmbedding: defaultEmbed,
    searchQdrant: defaultSearch,
    acquireLock: defaultLock,
    releaseLock: defaultRelease,
    renewLock: defaultRenew,
    sendMessage: defaultSend,
    getChatHistory: defaultGetHistory,
    addChatMessage: defaultAddMsg,
    logger: log,
};

export const processMessage = async (
    input: ProcessorInput,
    deps: ProcessorDependencies = defaultDeps
): Promise<ProcessorResult> => {
    const { text, chatId } = input;
    const { logger } = deps;

    const conversationId = String(chatId);
    const startTime = Date.now();

    logger('info', `[Processor] Iniciando processamento`, {
        conversationId,
        textLength: text?.length,
    });

    if (!text || !text.trim()) {
        logger('error', '[Processor] Texto vazio', { conversationId });
        return { ok: false, conversationId, mode: 'empty' };
    }

    const originalQuestion = text.trim();

    let hash = 0;
    for (let i = 0; i < originalQuestion.length; i++) {
        hash = (hash << 5) - hash + originalQuestion.charCodeAt(i);
        hash |= 0;
    }
    const hashStr = Math.abs(hash).toString(36).slice(0, 12);
    const lockKey = `professor:lock:${conversationId}:${hashStr}`;
    const lockValue = randomUUID();

    const lockTtlMs = config.LOCK_TTL_MS;
    const lockRes = await deps.acquireLock(lockKey, lockValue, lockTtlMs);

    if (!lockRes.acquired) {
        logger('warn', `[Processor] Lock rejeitado`, { conversationId, lockKey });
        const lockedMessage = '⏳ Já estou processando sua pergunta. Aguarde alguns instantes.';
        await deps.sendMessage(chatId, lockedMessage);
        return {
            ok: false,
            conversationId,
            mode: 'locked',
            replyText: lockedMessage,
        };
    }

    // Keep older injected dependency objects usable in tests and integrations.
    // Production callers use the owner-aware default release client above.
    const release = deps.releaseLock ?? (async () => ({ deleted: false }));
    const renew = deps.renewLock;
    const renewalTimer = renew
        ? setInterval(() => {
            renew(lockKey, lockValue, lockTtlMs).catch(() => {
                logger('warn', '[Processor] Falha ao renovar lock', { conversationId, error: 'renew_failure' });
            });
        }, config.LOCK_RENEW_INTERVAL_MS)
        : undefined;
    renewalTimer?.unref?.();

    try {
        const preprocessorOutputRaw = await deps.chatCompletion(
            config.MODEL_PREPROCESSOR,
            [
                { role: 'system', content: PROMPTS.PREPROCESSOR },
                { role: 'user', content: originalQuestion },
            ],
            0.2,
            { type: 'json_object' }
        );

        let preprocessorData: any = {
            canonical_question_ptbr: originalQuestion,
            primary_focus: 'geral',
            input: originalQuestion,
        };

        try {
            if (preprocessorOutputRaw) preprocessorData = JSON.parse(preprocessorOutputRaw);
        } catch (e) {
            logger('error', '[Processor] Erro no parse do Preprocessor', { error: 'invalid_json' });
        }

        const embedding = await deps.getEmbedding(preprocessorData.input || originalQuestion);
        const rawResults = input.retrievalContext
            ? await deps.searchQdrant(embedding, 12, input.retrievalContext)
            : await deps.searchQdrant(embedding, 12);
        // Keep this check at the processor boundary as well as inside the
        // default Qdrant adapter: injected adapters and future integrations
        // must not be able to bypass tenant/collection validation.
        const results = filterTrustedQdrantResults(rawResults, input.retrievalContext);

        logger('info', '[Processor] Qdrant search summary', {
            conversationId,
            qdrantCollection: (config as any).QDRANT_COLLECTION,
            qdrantScoreThreshold: (config as any).QDRANT_SCORE_THRESHOLD,
            hits: Array.isArray(results) ? results.length : -1,
            topScore: Array.isArray(results) && results[0] ? results[0].score : null,
            topPayloadKeys: Array.isArray(results) && results[0]?.payload ? Object.keys(results[0].payload) : null,
        });

        const mustHave = (preprocessorData.must_include_terms || [])
            .map((t: string) => t.trim())
            .filter(Boolean);

        const gate = evaluateEvidence(results, mustHave, {
            approvedScoreThreshold: config.EVIDENCE_APPROVED_SCORE_THRESHOLD,
            weakScoreThreshold: config.EVIDENCE_WEAK_SCORE_THRESHOLD,
            minMustCoverage: config.EVIDENCE_MIN_MUST_COVERAGE,
            minApprovedHits: config.EVIDENCE_MIN_APPROVED_HITS,
        });
        const hasHits = gate.usableResults.length > 0;
        const { topScore, mustCoverage } = gate;

        logger('info', `[Processor] Resultado do Gate`, {
            status: gate.status,
            reason: gate.reason,
            hasHits,
            topScore,
            mustCoverage,
        });

        if (gate.status !== 'APPROVED_EVIDENCE') {
            logger('warn', '[Processor] Evidência não aprovada. Acionando Fallback', {
                status: gate.status,
            });

            const fallbackOutput = await deps.chatCompletion(
                config.MODEL_FALLBACK,
                [
                    { role: 'system', content: PROMPTS.FALLBACK_SYSTEM },
                    { role: 'user', content: originalQuestion },
                ],
                0.2
            );

            if (fallbackOutput) {
                await deps.sendMessage(chatId, fallbackOutput);
                await deps.addChatMessage(conversationId, 'user', originalQuestion);
                await deps.addChatMessage(conversationId, 'assistant', fallbackOutput);
            }

            return {
                ok: true,
                conversationId,
                mode: 'fallback',
                replyText: fallbackOutput || 'Não foi possível gerar resposta.',
                metadata: {
                    hits: gate.usableResults.length,
                    topScore,
                    evidenceStatus: gate.status,
                },
            };
        }

        preprocessorData._evidence_level = gate.status;

        const plannerEvidenceInput = gate.usableResults.map((result) => {
            const payload = result.payload || {};
            const safePayload: Record<string, unknown> = {};
            for (const key of [
                'text',
                'source',
                'doc_key',
                'filename',
                'title',
                'section',
                'page_start',
                'page_end',
                'workspace_id',
                'collection_id',
            ]) {
                const value = payload[key];
                if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) {
                    safePayload[key] = value;
                }
            }
            return { id: result.id, score: result.score, payload: safePayload };
        });

        const plannerUser = PROMPTS.PLANNER
            .replace('{{QUESTION}}', preprocessorData.canonical_question_ptbr)
            .replace('{{PRIMARY_FOCUS}}', preprocessorData.primary_focus)
            .replace('{{INTENT}}', preprocessorData.intent || 'outros')
            .replace('{{EXPECTS_NUMERIC}}', String(preprocessorData.expects_numeric || false))
            .replace('{{EVIDENCE_STATUS}}', gate.status)
            .replace('{{EVIDENCES}}', JSON.stringify(plannerEvidenceInput, null, 2));

        const plannerOutputRaw = await deps.chatCompletion(
            config.MODEL_PLANNER,
            [
                { role: 'system', content: PROMPTS.PLANNER },
                { role: 'user', content: plannerUser },
            ],
            0.2,
            { type: 'json_object' }
        );

        const parsedPlannerOutput = parsePlannerOutput(plannerOutputRaw);
        const plannerData = parsedPlannerOutput ?? defaultPlannerOutput();
        if (plannerOutputRaw && !parsedPlannerOutput) {
            logger('error', '[Processor] Contrato do Planner rejeitado', { error: 'invalid_planner_contract' });
        }

        const plannerReferences = plannerData.resumo_evidencias;

        const resultById = new Map(
            gate.usableResults.map((result) => [String(result.id), result])
        );

        const resolvePlannerReference = (item: unknown): string | null => {
            if (!item || typeof item !== 'object' || Array.isArray(item)) return null;

            // Planner output is a reference list, never an evidence payload.
            const referenceObject = item as Record<string, unknown>;
            const keys = Object.keys(referenceObject);
            if (keys.length !== 1 || keys[0] !== 'id') {
                return null;
            }
            const reference = referenceObject.id;
            if (typeof reference !== 'string' && typeof reference !== 'number') return null;
            return String(reference);
        };

        let rejectedPlannerReferences = 0;
        const selectedPlannerEvidence = plannerReferences
            .map((item: any) => {
                const reference = resolvePlannerReference(item);
                const result = reference === null ? undefined : resultById.get(reference);
                if (!result) rejectedPlannerReferences++;
                return result;
            })
            .filter((result: any): result is any => Boolean(result));

        if (rejectedPlannerReferences > 0) {
            logger('warn', '[Processor] Referências do planner rejeitadas', {
                rejectedPlannerReferences,
            });
        }

        const resolveSourceKey = (payload: any) => {
            const rawDocKey = String(payload?.doc_key || '').trim();
            if (rawDocKey) {
                const parts = rawDocKey.split('|').filter(Boolean);
                if (parts.length > 2) {
                    return parts.slice(0, -2).join('|');
                }
                return rawDocKey;
            }
            return String(payload?.source || 'fonte_desconhecida');
        };

        const rankedResults = gate.usableResults
            .map((r: any) => {
                const text = String(r?.payload?.text || '');
                const textNorm = text.toLowerCase();
                const mustHits = mustHave.filter((t: string) => textNorm.includes(t.toLowerCase())).length;
                const keywordBonus = mustHits * 0.08;
                const score = Number(r?.score || 0) + keywordBonus;
                const sourceKey = resolveSourceKey(r?.payload || {});
                return { ...r, _mustHits: mustHits, _rankScore: score, _sourceKey: sourceKey };
            })
            .sort((a: any, b: any) => (b._rankScore || 0) - (a._rankScore || 0));

        const diversifyEvidence = (items: any[], maxTotal = 6, maxPerSource = 2, minDistinctSources = 3) => {
            const selected: any[] = [];
            const perSource = new Map<string, number>();

            for (const item of items) {
                const source = String(item?._sourceKey || 'fonte_desconhecida');
                const used = perSource.get(source) || 0;
                if (used >= 1) continue;
                selected.push(item);
                perSource.set(source, used + 1);
                if (selected.length >= maxTotal) break;
            }

            const distinctSources = perSource.size;

            for (const item of items) {
                if (selected.length >= maxTotal) break;
                if (selected.includes(item)) continue;
                const source = String(item?._sourceKey || 'fonte_desconhecida');
                const used = perSource.get(source) || 0;
                const allowedPerSource = distinctSources >= minDistinctSources ? maxPerSource : 1;
                if (used >= allowedPerSource) continue;
                selected.push(item);
                perSource.set(source, used + 1);
            }

            if (selected.length < maxTotal) {
                for (const item of items) {
                    if (selected.length >= maxTotal) break;
                    if (selected.includes(item)) continue;
                    const source = String(item?._sourceKey || 'fonte_desconhecida');
                    const used = perSource.get(source) || 0;
                    if (used >= maxPerSource) continue;
                    selected.push(item);
                    perSource.set(source, used + 1);
                }
            }

            return selected;
        };

        const normalizeEvidenceItem = (item: any) => {
            const payload = item?.payload || {};
            const sourceKey = String(item?._sourceKey || resolveSourceKey(payload));
            const text = String(payload.text || '').replace(/\s+/g, ' ').trim();
            return {
                ...item,
                _sourceKey: sourceKey,
                _dedupeKey: `${sourceKey}::${text.slice(0, 280)}`,
            };
        };

        const dedupeEvidence = (items: any[]) => {
            const seen = new Set<string>();
            const deduped: any[] = [];
            for (const raw of items) {
                const item = normalizeEvidenceItem(raw);
                if (!item.payload?.text) continue;
                if (seen.has(item._dedupeKey)) continue;
                seen.add(item._dedupeKey);
                deduped.push(item);
            }
            return deduped;
        };

        const fallbackEvidence = dedupeEvidence(rankedResults);

        const selectedEvidence = diversifyEvidence(
            [...selectedPlannerEvidence, ...fallbackEvidence],
            6,
            2,
            3
        );

        const formatEvidence = (ev: any, idx: number) => {
            const payload = ev?.payload || {};
            const pages = payload.page_start && payload.page_end
                ? `p. ${payload.page_start}-${payload.page_end}`
                : payload.page_start
                    ? `p. ${payload.page_start}`
                    : 'página não informada';
            const source = payload.source || payload.doc_key || 'fonte não identificada';
            const docKey = payload.doc_key || source;
            const score = typeof ev?.score === 'number' ? ev.score.toFixed(3) : 'n/a';
            return [
                `[E${idx + 1}]`,
                `Fonte: ${source}`,
                `DocKey: ${docKey}`,
                `Localização: ${pages}`,
                `Score semântico: ${score}`,
                `Trecho: ${String(payload.text || '').trim()}`,
            ].join('\n');
        };

        const ragContext = selectedEvidence.map(formatEvidence).join('\n\n---\n\n');

        const chatHistory = await deps.getChatHistory(conversationId);
        const planForAgent = {
            // The evidence gate is calculated by the service, not by the
            // planner. Only finite enums cross into the final model prompt.
            gate_mode: gate.status === 'APPROVED_EVIDENCE' ? 'approved' : 'fallback_general',
            response_sections: plannerData.response_sections,
        };

        const agentUser = PROMPTS.CLINICAL_AGENT_USER_PROMPT
            .replace('{{QUESTION}}', preprocessorData.canonical_question_ptbr)
            .replace('{{CHAT_HISTORY}}', chatHistory || 'Sem histórico recente.')
            .replace('{{PLAN}}', JSON.stringify(planForAgent, null, 2))
            .replace('{{RAG_CONTEXT}}', ragContext)
            .replace('{{EVIDENCES_COUNT}}', String(gate.usableResults.length));

        const agentOutput = await deps.chatCompletion(
            config.MODEL_AGENT,
            [
                { role: 'system', content: PROMPTS.CLINICAL_AGENT },
                { role: 'user', content: agentUser },
            ],
            0.2
        );

        if (agentOutput) {
            await deps.sendMessage(chatId, agentOutput);
            await deps.addChatMessage(conversationId, 'user', originalQuestion);
            await deps.addChatMessage(conversationId, 'assistant', agentOutput);
        }

        return {
            ok: true,
            conversationId,
            mode: 'answer',
            replyText: agentOutput || 'Não foi possível gerar resposta.',
            metadata: {
                hits: gate.usableResults.length,
                topScore,
                evidenceLevel: preprocessorData._evidence_level,
                evidenceStatus: gate.status,
                rejectedPlannerReferences,
            },
        };
    } catch (error) {
        logger('error', '[Processor] Erro Crítico', { error: 'processor_failure' });
        const errMessage = '🚨 Erro interno. Tente novamente em breve.';
        await deps.sendMessage(chatId, errMessage);
        return {
            ok: false,
            conversationId,
            mode: 'error',
            replyText: errMessage,
            metadata: { error: 'processor_failure' },
        };
    } finally {
        if (renewalTimer) clearInterval(renewalTimer);
        try {
            await release(lockKey, lockValue);
        } catch (error) {
            logger('error', '[Processor] Falha ao liberar lock', { error: 'release_failure' });
        }
        logger('info', `[Processor] Finalizado`, { durationMs: Date.now() - startTime });
    }
};

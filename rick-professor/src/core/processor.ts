import { PROMPTS } from './prompts';
import { chatCompletion as defaultChat, getEmbedding as defaultEmbed } from '../lib/openai';
import { searchQdrant as defaultSearch } from '../lib/qdrant';
import { acquireLock as defaultLock } from '../lib/redis-lock';
import { sendMessage as defaultSend } from '../lib/telegram';
import { getChatHistory as defaultGetHistory, addChatMessage as defaultAddMsg } from '../lib/memory';
import { config } from '../config';
import { randomUUID } from 'crypto';
import { log } from '../lib/logging';

interface ProcessorInput {
    text: string;
    chatId: string;
    messageId?: number;
    fromId?: number;
    raw?: any;
}

export interface ProcessorDependencies {
    chatCompletion: typeof defaultChat;
    getEmbedding: typeof defaultEmbed;
    searchQdrant: typeof defaultSearch;
    acquireLock: typeof defaultLock;
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

    const lockRes = await deps.acquireLock(lockKey, lockValue, 45000);

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
            logger('error', '[Processor] Erro no parse do Preprocessor', { error: String(e) });
        }

        const embedding = await deps.getEmbedding(preprocessorData.input || originalQuestion);
        const results = await deps.searchQdrant(embedding, 12);

        logger('info', '[Processor] Qdrant search summary', {
            conversationId,
            qdrantUrl: config.QDRANT_URL,
            qdrantCollection: (config as any).QDRANT_COLLECTION,
            qdrantScoreThreshold: (config as any).QDRANT_SCORE_THRESHOLD,
            hits: Array.isArray(results) ? results.length : -1,
            topScore: Array.isArray(results) && results[0] ? results[0].score : null,
            topPayloadKeys: Array.isArray(results) && results[0]?.payload ? Object.keys(results[0].payload) : null,
        });

        const hasHits = Array.isArray(results) && results.length > 0;
        const topScore = hasHits ? (results[0]?.score ?? 0) : 0;

        const ctxText = results.map((r: any) => r?.payload?.text || '').join('\n\n');
        const ctxNorm = ctxText.toLowerCase();

        const mustHave = (preprocessorData.must_include_terms || [])
            .map((t: string) => t.trim())
            .filter(Boolean);

        let hitCount = 0;
        for (const t of mustHave) {
            if (ctxNorm.includes(t.toLowerCase())) hitCount++;
        }
        const mustCoverage = mustHave.length ? hitCount / mustHave.length : 0;

        const approvedStrong = mustCoverage >= 0.125 || topScore >= 0.62;
        const approvedSoft = hasHits && topScore >= 0.55;
        const approved = approvedStrong || approvedSoft;

        logger('info', `[Processor] Resultado do Gate`, {
            approved,
            approvedStrong,
            approvedSoft,
            hasHits,
            topScore,
            mustCoverage,
        });

        if (!hasHits) {
            logger('warn', '[Processor] Sem evidências (hits=0). Acionando Fallback');

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
                metadata: { hits: 0, topScore },
            };
        }

        preprocessorData._evidence_level = approvedStrong ? 'strong' : 'moderate';

        const plannerUser = PROMPTS.PLANNER
            .replace('{{QUESTION}}', preprocessorData.canonical_question_ptbr)
            .replace('{{PRIMARY_FOCUS}}', preprocessorData.primary_focus)
            .replace('{{INTENT}}', preprocessorData.intent || 'outros')
            .replace('{{EXPECTS_NUMERIC}}', String(preprocessorData.expects_numeric || false))
            .replace('{{EVIDENCES}}', JSON.stringify(results, null, 2));

        const plannerOutputRaw = await deps.chatCompletion(
            config.MODEL_PLANNER,
            [
                { role: 'system', content: PROMPTS.PLANNER },
                { role: 'user', content: plannerUser },
            ],
            0.2,
            { type: 'json_object' }
        );

        let planReal: any = {};
        try {
            if (plannerOutputRaw) planReal = JSON.parse(plannerOutputRaw);
        } catch (e) {
            logger('error', '[Processor] Erro no parse do Planner', { error: String(e) });
        }

        const evidences = Array.isArray(planReal.resumo_evidencias)
            ? planReal.resumo_evidencias
            : [];

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

        const rankedResults = results
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

        const plannerEvidence = dedupeEvidence(evidences);
        const fallbackEvidence = dedupeEvidence(rankedResults);

        const selectedEvidence = diversifyEvidence(
            [...plannerEvidence, ...fallbackEvidence],
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

        const agentUser = PROMPTS.CLINICAL_AGENT_USER_PROMPT
            .replace('{{QUESTION}}', preprocessorData.canonical_question_ptbr)
            .replace('{{CHAT_HISTORY}}', chatHistory || 'Sem histórico recente.')
            .replace('{{PLAN}}', JSON.stringify(planReal, null, 2))
            .replace('{{RAG_CONTEXT}}', ragContext)
            .replace('{{EVIDENCES_COUNT}}', String(results.length));

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
                hits: results.length,
                topScore,
                evidenceLevel: preprocessorData._evidence_level,
            },
        };
    } catch (error) {
        logger('error', '[Processor] Erro Crítico', { error: String(error) });
        const errMessage = '🚨 Erro interno. Tente novamente em breve.';
        await deps.sendMessage(chatId, errMessage);
        return {
            ok: false,
            conversationId,
            mode: 'error',
            replyText: errMessage,
            metadata: { error: String(error) },
        };
    } finally {
        logger('info', `[Processor] Finalizado`, { durationMs: Date.now() - startTime });
    }
};

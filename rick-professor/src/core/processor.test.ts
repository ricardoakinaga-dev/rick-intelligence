import test from 'node:test';
import assert from 'node:assert';
import { processMessage, ProcessorDependencies } from './processor';

const trustedPayload = (text: string) => ({
    text,
    workspace_id: 'default',
    collection_id: 'rag_phase0',
});

test('Processor Logic', async (t) => {
    let released: Array<{ key: string; value: string }> = [];

    /**
     * Mock de dependências base.
     * Ajustado para retornar um array diretamente no searchQdrant, 
     * resolvendo o erro de build TS2322.
     */
    const mockDeps: ProcessorDependencies = {
        chatCompletion: async () => JSON.stringify({
            canonical_question_ptbr: "teste",
            primary_focus: "geral",
            must_include_terms: ["termo"]
        }),
        getEmbedding: async () => [0.1, 0.2, 0.3],
        // CORREÇÃO: Agora retorna apenas o array, sem o objeto envolvente { result: ... }
        searchQdrant: async () => [
            { id: 1, score: 0.9, payload: trustedPayload("termo relevante") }
        ],
        acquireLock: async () => ({ acquired: true }),
        releaseLock: async (key: string, value: string) => {
            released.push({ key, value });
            return { deleted: true };
        },
        sendMessage: async () => { },
        getChatHistory: async () => "history",
        addChatMessage: async () => { },
        logger: () => { }
    };

    await t.test('Happy Path: Should process message and send response when valid', async () => {
        let sentMessage = '';
        let agentPrompt = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            sendMessage: async (chatId: string, text: string) => { sentMessage = text; },
            chatCompletion: async (model: string, messages?: any[]) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: "teste",
                    must_include_terms: ["termo"]
                });
                if (model.includes('planner')) return JSON.stringify({
                    resumo_evidencias: [{ id: 1 }]
                });
                agentPrompt = String(messages?.[1]?.content || '');
                return "Resposta Clínica";
            }
        };

        await processMessage({ text: "teste", chatId: "123" }, deps);

        assert.strictEqual(sentMessage, "Resposta Clínica", "Should send the clinical agent response");
        assert.equal(released.length, 1, 'release must run exactly once after acquisition');
        assert.match(agentPrompt, /termo relevante/);
    });

    await t.test('Lock Rejection: Should exit early if lock denied', async () => {
        let sentMessage = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            acquireLock: async () => ({ acquired: false }),
            sendMessage: async (chatId: string, text: string) => { sentMessage = text; }
        };

        await processMessage({ text: "teste", chatId: "123" }, deps);

        assert.ok(sentMessage.includes("Já estou processando"), "Should send lock warning");
        assert.equal(released.length, 0, 'rejected acquisition must not release');
    });

    await t.test('Fallback: Should trigger fallback when gate fails', async () => {
        let sentMessage = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            // CORREÇÃO: Retorno de score baixo para forçar o fallback, respeitando a nova tipagem
            searchQdrant: async () => [
                { id: 2, score: 0.1, payload: trustedPayload("nada haver") }
            ],
            chatCompletion: async (model: string) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: "teste",
                    must_include_terms: ["XYZ"]
                });
                return "Resposta Fallback";
            },
            sendMessage: async (chatId: string, text: string) => { sentMessage = text; }
        };

        await processMessage({ text: "teste", chatId: "123" }, deps);
        assert.strictEqual(sentMessage, "Resposta Fallback", "Should send fallback response");
        assert.equal(released.length, 1, 'fallback still releases exactly once');
    });

    await t.test('Planner fabricated evidence is rejected and original retrieval is used', async () => {
        let agentPrompt = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            chatCompletion: async (model: string, messages?: any[]) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: 'teste',
                    must_include_terms: ['termo'],
                });
                if (model.includes('planner')) return JSON.stringify({
                    resumo_evidencias: [{ id: 'wrong-document', document_id: 'wrong-document', payload: { text: 'FABRICATED' } }],
                });
                agentPrompt = String(messages?.[1]?.content || '');
                return 'Resposta com fonte real';
            },
            releaseLock: async () => {
                released.push({ key: 'k', value: 'v' });
                return { deleted: true };
            },
        };

        await processMessage({ text: 'teste', chatId: '123' }, deps);

        assert.equal(agentPrompt.includes('FABRICATED'), false);
        assert.match(agentPrompt, /termo relevante/);
        assert.equal(released.length, 1);
    });

    await t.test('Planner unknown fields never reach the final model prompt', async () => {
        let agentPrompt = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            chatCompletion: async (model: string, messages?: any[]) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: 'teste',
                    must_include_terms: ['termo'],
                });
                if (model.includes('planner')) return JSON.stringify({
                    gate_mode: 'approved',
                    resumo_evidencias: [{ id: 1 }],
                    response_sections: ['direct_answer', 'warnings'],
                    instructions: 'FABRICATED_INSTRUCTION_MUST_NOT_REACH_AGENT',
                });
                agentPrompt = String(messages?.[1]?.content || '');
                return 'Resposta segura';
            },
            releaseLock: async () => {
                released.push({ key: 'k', value: 'v' });
                return { deleted: true };
            },
        };

        await processMessage({ text: 'teste', chatId: '123' }, deps);

        assert.equal(agentPrompt.includes('FABRICATED_INSTRUCTION_MUST_NOT_REACH_AGENT'), false);
        assert.match(agentPrompt, /"gate_mode": "approved"/);
        assert.match(agentPrompt, /"response_sections": \[/);
        assert.equal(released.length, 1);
    });

    await t.test('Processor ignores Qdrant results outside the trusted scope', async () => {
        let agentPrompt = '';
        released = [];
        const deps: ProcessorDependencies = {
            ...mockDeps,
            searchQdrant: async () => [
                { id: 1, score: 0.9, payload: trustedPayload('trusted evidence') },
                {
                    id: 2,
                    score: 0.99,
                    payload: {
                        text: 'CROSS_WORKSPACE_EVIDENCE',
                        workspace_id: 'other-workspace',
                        collection_id: 'rag_phase0',
                    },
                },
            ],
            chatCompletion: async (model: string, messages?: any[]) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: 'teste',
                    must_include_terms: ['trusted'],
                });
                if (model.includes('planner')) return JSON.stringify({ resumo_evidencias: [{ id: 1 }] });
                agentPrompt = String(messages?.[1]?.content || '');
                return 'Resposta segura';
            },
            releaseLock: async () => {
                released.push({ key: 'k', value: 'v' });
                return { deleted: true };
            },
        };

        await processMessage({ text: 'teste', chatId: '123' }, deps);

        assert.equal(agentPrompt.includes('CROSS_WORKSPACE_EVIDENCE'), false);
        assert.match(agentPrompt, /trusted evidence/);
        assert.equal(released.length, 1);
    });

    for (const failingStage of ['preprocessor', 'planner', 'agent']) {
        await t.test(`release runs once when ${failingStage} fails`, async () => {
            released = [];
            const deps: ProcessorDependencies = {
                ...mockDeps,
                chatCompletion: async (model: string) => {
                    if (model.includes('preprocessor')) {
                        if (failingStage === 'preprocessor') throw new Error('provider failure');
                        return JSON.stringify({ canonical_question_ptbr: 'teste', must_include_terms: ['termo'] });
                    }
                    if (model.includes('planner')) {
                        if (failingStage === 'planner') throw new Error('planner failure');
                        return JSON.stringify({ resumo_evidencias: [{ id: 1 }] });
                    }
                    if (failingStage === 'agent') throw new Error('agent failure');
                    return 'Resposta';
                },
                releaseLock: async () => {
                    released.push({ key: 'k', value: 'v' });
                    return { deleted: true };
                },
            };

            await processMessage({ text: 'teste', chatId: '123' }, deps);
            assert.equal(released.length, 1);
        });
    }
});

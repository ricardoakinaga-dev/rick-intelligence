import test from 'node:test';
import assert from 'node:assert';
import { processMessage, ProcessorDependencies } from './processor';

test('Processor Logic', async (t) => {

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
            { id: 1, score: 0.9, payload: { text: "termo relevante" } }
        ],
        acquireLock: async () => ({ acquired: true }),
        sendMessage: async () => { },
        getChatHistory: async () => "history",
        addChatMessage: async () => { },
        logger: () => { }
    };

    await t.test('Happy Path: Should process message and send response when valid', async () => {
        let sentMessage = '';
        const deps: ProcessorDependencies = {
            ...mockDeps,
            sendMessage: async (chatId: string, text: string) => { sentMessage = text; },
            chatCompletion: async (model: string) => {
                if (model.includes('preprocessor')) return JSON.stringify({
                    canonical_question_ptbr: "teste",
                    must_include_terms: ["termo"]
                });
                if (model.includes('planner')) return JSON.stringify({
                    resumo_evidencias: [{ payload: { text: "evidencia lida" } }]
                });
                return "Resposta Clínica";
            }
        };

        await processMessage({ text: "teste", chatId: "123" }, deps);

        assert.strictEqual(sentMessage, "Resposta Clínica", "Should send the clinical agent response");
    });

    await t.test('Lock Rejection: Should exit early if lock denied', async () => {
        let sentMessage = '';
        const deps: ProcessorDependencies = {
            ...mockDeps,
            acquireLock: async () => ({ acquired: false }),
            sendMessage: async (chatId: string, text: string) => { sentMessage = text; }
        };

        await processMessage({ text: "teste", chatId: "123" }, deps);

        assert.ok(sentMessage.includes("Já estou processando"), "Should send lock warning");
    });

    await t.test('Fallback: Should trigger fallback when gate fails', async () => {
        let sentMessage = '';
        const deps: ProcessorDependencies = {
            ...mockDeps,
            // CORREÇÃO: Retorno de score baixo para forçar o fallback, respeitando a nova tipagem
            searchQdrant: async () => [
                { id: 2, score: 0.1, payload: { text: "nada haver" } }
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
    });
});
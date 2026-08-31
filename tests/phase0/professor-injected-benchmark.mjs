#!/usr/bin/env node

import { performance } from 'node:perf_hooks';
import assert from 'node:assert/strict';

const { processMessage } = await import('../../rick-professor/dist/core/processor.js');

const scriptedModelOutput = JSON.stringify({
  canonical_question_ptbr: 'phase 0 benchmark',
  primary_focus: 'geral',
  input: 'phase 0 benchmark',
  must_include_terms: ['phase'],
  resumo_evidencias: [
    { payload: { text: 'phase evidence', source: 'phase0' } },
  ],
});

const deps = {
  chatCompletion: async () => scriptedModelOutput,
  getEmbedding: async () => [0.1, 0.2, 0.3],
  searchQdrant: async () => [
    { id: 'phase0', score: 0.9, payload: { text: 'phase evidence', source: 'phase0' } },
  ],
  acquireLock: async () => ({ acquired: true }),
  sendMessage: async () => {},
  getChatHistory: async () => 'no history',
  addChatMessage: async () => {},
  logger: () => {},
};

const samples = [];
for (let index = 0; index < 12; index += 1) {
  const started = performance.now();
  const result = await processMessage(
    { text: 'phase 0 benchmark', chatId: 'phase0-' + index },
    deps,
  );
  samples.push(Number((performance.now() - started).toFixed(3)));
  assert.equal(result.ok, true);
  assert.equal(result.mode, 'answer');
}

const sorted = [...samples].sort((a, b) => a - b);
const nearestObserved = (fraction) => sorted[Math.max(0, Math.ceil(fraction * sorted.length) - 1)];

const output = {
  test: 'professor-injected-benchmark',
  result: 'PASS',
  n: samples.length,
  unit: 'ms',
  samples_ms: samples,
  p50: nearestObserved(0.5),
  p95: nearestObserved(0.95),
  min: sorted[0],
  max: sorted[sorted.length - 1],
  workload: 'deterministic injected preprocessor/planner/agent, embedding, Qdrant hit, lock, memory, and send functions',
  limitation: 'orchestration overhead only; no provider, database, locker HTTP, Telegram, or route overhead',
};

process.stdout.write(JSON.stringify(output) + '\n', () => process.exit(0));

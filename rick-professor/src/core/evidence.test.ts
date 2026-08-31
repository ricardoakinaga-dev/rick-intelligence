import assert from 'node:assert/strict';
import test from 'node:test';
import { evaluateEvidence } from './evidence';

const hit = (id: string, score: number, text: string) => ({
    id,
    score,
    payload: { text },
});

test('evidence gate has authoritative statuses and rejects a weak single hit', () => {
    assert.equal(evaluateEvidence([]).status, 'NO_EVIDENCE');
    assert.equal(evaluateEvidence([hit('weak', 0.6, 'contexto')]).status, 'WEAK_EVIDENCE');
    assert.equal(
        evaluateEvidence([hit('weak-term', 0.6, 'parvovirose')], ['parvovirose']).status,
        'WEAK_EVIDENCE'
    );
    assert.equal(
        evaluateEvidence([hit('strong', 0.9, 'contexto clínico')]).status,
        'APPROVED_EVIDENCE'
    );
});

test('multiple weak hits can be approved only with adequate coverage', () => {
    const result = evaluateEvidence(
        [hit('a', 0.58, 'parvovirose e tratamento'), hit('b', 0.56, 'parvovirose monitoramento')],
        ['parvovirose'],
        { minMustCoverage: 1 }
    );

    assert.equal(result.status, 'APPROVED_EVIDENCE');
    assert.equal(result.mustCoverage, 1);
});

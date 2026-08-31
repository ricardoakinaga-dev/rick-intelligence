import { QdrantSearchResult } from '../lib/qdrant';

export type EvidenceStatus = 'NO_EVIDENCE' | 'WEAK_EVIDENCE' | 'APPROVED_EVIDENCE';

export interface EvidenceGateOptions {
    approvedScoreThreshold?: number;
    weakScoreThreshold?: number;
    minMustCoverage?: number;
    minApprovedHits?: number;
}

export interface EvidenceGateResult {
    status: EvidenceStatus;
    usableResults: QdrantSearchResult[];
    topScore: number;
    mustCoverage: number;
    reason: 'no_hits' | 'below_threshold' | 'single_weak_hit' | 'strong_score' | 'covered_terms' | 'multiple_weak_hits';
}

const finiteScore = (value: unknown): number => {
    const score = Number(value);
    return Number.isFinite(score) ? score : 0;
};

const hasUsableIdentity = (result: QdrantSearchResult): boolean =>
    result?.id !== undefined && result?.id !== null && String(result.id).trim().length > 0;

const hasUsableText = (result: QdrantSearchResult): boolean =>
    typeof result?.payload?.text === 'string' && result.payload.text.trim().length > 0;

export const evaluateEvidence = (
    results: QdrantSearchResult[] | undefined,
    mustHaveTerms: string[] = [],
    options: EvidenceGateOptions = {}
): EvidenceGateResult => {
    const approvedScoreThreshold = options.approvedScoreThreshold ?? 0.62;
    const weakScoreThreshold = options.weakScoreThreshold ?? 0.55;
    const minMustCoverage = options.minMustCoverage ?? 0.5;
    const minApprovedHits = options.minApprovedHits ?? 2;
    const usableResults = (Array.isArray(results) ? results : [])
        .filter((result) => hasUsableIdentity(result) && hasUsableText(result));

    if (usableResults.length === 0) {
        return {
            status: 'NO_EVIDENCE',
            usableResults,
            topScore: 0,
            mustCoverage: 0,
            reason: 'no_hits',
        };
    }

    const topScore = Math.max(...usableResults.map((result) => finiteScore(result.score)));
    const normalizedTerms = mustHaveTerms.map((term) => term.trim().toLowerCase()).filter(Boolean);
    const context = usableResults.map((result) => result.payload.text).join('\n').toLowerCase();
    const matchingTerms = normalizedTerms.filter((term) => context.includes(term)).length;
    const mustCoverage = normalizedTerms.length ? matchingTerms / normalizedTerms.length : 0;

    if (topScore >= approvedScoreThreshold) {
        return { status: 'APPROVED_EVIDENCE', usableResults, topScore, mustCoverage, reason: 'strong_score' };
    }

    // A single result below the approved threshold is never enough, even when
    // it happens to contain every requested term.
    if (usableResults.length === 1) {
        return { status: 'WEAK_EVIDENCE', usableResults, topScore, mustCoverage, reason: 'single_weak_hit' };
    }

    if (
        topScore >= weakScoreThreshold &&
        normalizedTerms.length > 0 &&
        mustCoverage >= minMustCoverage
    ) {
        return { status: 'APPROVED_EVIDENCE', usableResults, topScore, mustCoverage, reason: 'covered_terms' };
    }

    if (
        topScore >= weakScoreThreshold &&
        normalizedTerms.length === 0 &&
        usableResults.length >= minApprovedHits
    ) {
        return { status: 'APPROVED_EVIDENCE', usableResults, topScore, mustCoverage, reason: 'multiple_weak_hits' };
    }

    return {
        status: 'WEAK_EVIDENCE',
        usableResults,
        topScore,
        mustCoverage,
        reason: 'below_threshold',
    };
};

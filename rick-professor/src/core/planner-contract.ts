import { z } from 'zod';

export const PLANNER_RESPONSE_SECTIONS = [
    'direct_answer',
    'therapeutics',
    'exams',
    'monitoring',
    'warnings',
] as const;

const PlannerEvidenceReferenceSchema = z.object({
    id: z.union([
        z.string().trim().min(1).max(256),
        z.number().int(),
    ]),
}).strict();

const PlannerOutputSchema = z.object({
    gate_mode: z.enum(['approved', 'fallback_general', 'block']).default('approved'),
    resumo_evidencias: z.array(PlannerEvidenceReferenceSchema).max(12).default([]),
    response_sections: z.array(z.enum(PLANNER_RESPONSE_SECTIONS)).min(1).max(5).default([...PLANNER_RESPONSE_SECTIONS]),
}).strict();

export type PlannerOutput = z.infer<typeof PlannerOutputSchema>;

export const defaultPlannerOutput = (): PlannerOutput => ({
    gate_mode: 'approved',
    resumo_evidencias: [],
    response_sections: [...PLANNER_RESPONSE_SECTIONS],
});

/**
 * Parses only the planner contract. Unknown keys, arbitrary instructions,
 * copied evidence payloads, and oversized output are rejected as a whole.
 */
export const parsePlannerOutput = (raw: string | null): PlannerOutput | null => {
    if (!raw || raw.length > 32_000) return null;

    try {
        const parsed = PlannerOutputSchema.safeParse(JSON.parse(raw));
        return parsed.success ? parsed.data : null;
    } catch {
        return null;
    }
};

# ADR-019 — RRF/fusion preservation

Date: 2026-09-03. Status: Accepted.

RRF k=60 with 1/(k+rank+1) and the confidence blend are preserved numerically
(rank/score parity proven); only dict-shaped dense_score attribution is richer
(documented, ranking-neutral). No fusion tuning in migration — optimization
waits for measured evidence in a later phase.

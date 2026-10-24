# AUD24 — pack RAG sintético candidato (12 casos)

**Data:** 24/10/2026. **Estado:** candidato técnico; **não aprovado** por domínio.
**Comando:** `python scripts/state_of_art/evaluate_pack.py --pack docs/evaluation/packs/aud24-synthetic-v1 --pretty`

## Composição

- 9 casos positivos de ranking/citação/claim;
- 3 negativos: sem evidência, evidência fraca, afirmação sem suporte;
- 12 casos no total, corpus sintético, sem PII e sem corpus clínico de terceiros.

## Resultado

| Threshold | Observado | Status |
|---|---|---|
| ranking hit@1 | 1,0 | PASS |
| ranking recall@2 | 1,0 | PASS |
| ACL leakage | 0 | PASS |
| citation coverage/precision/recall/completeness | 1,0 | PASS |
| unsupported claim rate | 0,0 | PASS |
| faithfulness | 1,0 | PASS |
| p95 latency | 11 ms | PASS |

**Status do avaliador:** PASS.

## Limite explícito

Os labels e a plausibilidade clínica foram produzidos para teste estrutural, **não** por revisor de domínio. O pack não é representativo de produção, não aprova qualidade clínica e não fecha AUD24-044. A assinatura em [D04](../operations/d04-aud24-corpus-decision.md) continua obrigatória.

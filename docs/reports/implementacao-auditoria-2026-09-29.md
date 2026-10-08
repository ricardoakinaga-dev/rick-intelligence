# Implementação das melhorias da auditoria 29/09/2026

**Data:** 29/09/2026  
**Origem:** [auditoria](relatorio-auditoria-geral-2026-09-29.md), [roadmap](../roadmap-auditoria-2026-09-29.md) e [backlog](../backlog-auditoria-2026-09-29.md).

## Implementado e verificado

- **RA29-03:** migration `0008_composite_scope_constraints.sql` com FKs compostas para chunks, conversations e messages, FK de collection opcional e índices escopados. Nenhum backfill destrutivo.
- **RA29-04:** `password_plain` limitado ao `PlainTestVerifier` process-local; verificadores não efêmeros usam hash.
- **RA29-05:** validação explícita de tenant/workspace nas mutações administrativas, preservando a validação atômica dos providers.
- **RA29-06:** benchmark hermético usa fixture não clínica/allowlisted, com checksum e evidência coerentes; thresholds não foram reduzidos.
- **RA29-07:** `ConfirmDialog` expõe IDs/ARIA estáveis; testes de confirmação, foco, axe e reflow focados passam.
- **RA29-09:** gates raiz passaram a incluir API/worker compile, web lint/typecheck/build; `api15-benchmark` inclui contrato antes da execução.
- **RA29-12:** `toolchain.json` alinhado a Qdrant 1.12.5 e Redis 7.4, com notas de proveniência.
- **RA29-13:** Actions das workflows phase pinadas por SHA; bootstrap MinIO não recebe credenciais root; Jaeger memory está explicitamente documentado como efêmero.
- **RA29-11:** pisos de cobertura por suíte, lockfiles Python com hashes, teste de razão exata para API e upload do resumo configurado como artefato na lane de contrato.
- **Melhoria adicional de estabilidade visual:** reserva de altura no hero tablet de login para evitar layout shift/CLS acima de 0,1.

## Verificações executadas

- `make validate`: PASS.
- `make test-fast`: PASS; incluindo contrato do benchmark.
- `make api15-full`: PASS; contratos 12, providers 76, locking 54, professor 86, API 751 e benchmark local PASS.
- `make api16-root`: PASS; 751 testes.
- `scripts/state_of_art/tests/test_summarize_coverage.py`: 7/7 PASS; a entrada pytest-cov real agregou 8.385/11.081 statements (75,67%), 55 arquivos e 45 linhas excluídas.
- Checks estáticos dos pins das Actions e imagens da toolchain: PASS.
- `make lint`, `make typecheck`, `make build`: PASS.
- Migration estática e integrada: 5/5 testes PASS em PostgreSQL descartável com dados sintéticos; cobriu instalação vazia/repetida, relações válidas e cross-scope inválidas e rejeição de dados históricos incompatíveis sem avançar o ledger. O container criado pelo teste foi removido. Banco instalado/externo permanece NOT_RUN.
- Compose estático: 14 serviços dev e 14 staging, PASS; runtime não iniciado.
- Testes web focados: 5/5 PASS; os dois casos que falharam na matriz completa (search error e tablet login performance) passaram isoladamente após correções.
- Matriz web completa: execução de 321 testes produziu 319 PASS e 2 falhas de performance/estado antes das correções finais; não foi repetida integralmente após o último ajuste. Portanto não é declarado PASS integral.

## Não executado / bloqueado honestamente

- RA29-08: a suíte API sequencial passou; não há evidência de runtime distribuído concorrente suficiente para encerrar a investigação de intermitência.
- RA29-10: warnings de HTTPX/Starlette permanecem registrados; não foram ocultados por filtro.
- RA29-11: os testes locais e o relatório capturado passaram; a GitHub Actions ainda não foi executada, e a evidência veio de um snapshot isolado com worktree sujo.
- RA29-14/15: collector/alertas/SLO reais e lanes de autoridade continuam sem execução externa.
- RA29-16/17: golden path distribuído, provider real, Redis/Qdrant/S3 integrados e outbox sob restart não executados.
- RA29-18/19/20: restore/RPO/RTO, carga, chaos, soak, revisão independente e promoção continuam dependentes de D01–D07.

Nenhum deploy, provider pago, banco externo, restore, chaos, soak, push ou promoção foi executado. Alterações preexistentes do worktree foram preservadas.

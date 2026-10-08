# Índice canônico de documentação

**Status:** CURRENT para o checkout auditado.
**Última consolidação:** auditoria local de 07/10/2026, baseline 64,2/100 em 26 áreas e 20 achados (A01–A20); promoção `NO-GO`. **Remediação em andamento:** AUD07-01–15, AUD07-17, AUD07-18 e AUD07-19 concluídas e evidenciadas (M0 e M1 completos: A02, A03, A04, A16; M2 em curso: A10 no npm, A09 no typecheck, A11 na evidência de 1,86 GB e na higiene do worktree; o restante segue pendente). A nota descreve o corte auditado; alterações posteriores precisam de nova validação. O scorecard de 03/10/2026 permanece como baseline histórica desta rodada, com escopo e número de áreas diferentes — não comparável diretamente.
**Regra:** documentos com status `HISTORICAL`, `REFERENCE / NOT_RUN` ou fase anterior não comprovam o estado executável atual.

## Autoridades atuais

| Assunto | Fonte canônica | Estado |
|---|---|---|
| Estado do produto e comandos | [README](../README.md) | CURRENT |
| Contribuição e segurança operacional | [CONTRIBUTING](../CONTRIBUTING.md) | CURRENT |
| Arquitetura executável | [system-architecture.md](architecture/system-architecture.md) e [production-runtime.md](architecture/production-runtime.md) | CURRENT, runtime externo NOT_RUN |
| Limites de dependência | [dependency-boundaries.json](architecture/dependency-boundaries.json) | CURRENT como regra automatizada |
| Segurança e autorização | [authorization.md](architecture/authorization.md) e [security/](architecture/security/) | CURRENT, integração externa pendente |
| Operação e promoção | [release-readiness.md](operations/release-readiness.md) | REFERENCE / NOT_RUN |
| Snapshot desta auditoria | [relatório de 07/10/2026](reports/relatorio-auditoria-2026-10-07.md) | CURRENT como baseline; escore técnico local; promoção NO-GO |
| Roadmap desta auditoria | [roadmap-auditoria-2026-10-07.md](roadmap-auditoria-2026-10-07.md) | CURRENT como planejamento de referência |
| Backlog desta auditoria | [backlog-auditoria-2026-10-07.md](backlog-auditoria-2026-10-07.md) | CURRENT como contrato de escopo e aceite; 43 tarefas AUD07, **AUD07-01–15 e AUD07-17 concluídas, AUD07-43 em curso** |
| Snapshot anterior (AUD03) | [scorecard de 03/10/2026](reports/evidence/auditoria-2026-10-03/scorecard.json) | HISTORICAL como baseline anterior; escopo de 29 áreas, não comparável |
| Roadmap anterior (AUD03) | [roadmap-auditoria-2026-10-03.md](roadmap-auditoria-2026-10-03.md) | HISTORICAL; preservado para rastreabilidade |
| Backlog anterior (AUD03) | [backlog-auditoria-2026-10-03.md](backlog-auditoria-2026-10-03.md) | HISTORICAL; 36 tarefas AUD03 sem encerramento automático |
| Plano de implementação AUD03 | [execplan-aud03-implementation-2026-10-03.md](plans/execplan-aud03-implementation-2026-10-03.md) | IN_PROGRESS; registros de execução separados do planejamento; aceite global não demonstrado |
| Checkpoint das 36 tarefas AUD03 | [execution-checkpoint-v2.json](reports/evidence/implementation-aud03-2026-10-03/execution-checkpoint-v2.json) | Continuação local; nenhum aceite integral declarado; v1 preservado como predecessor; conferir hashes e revisões antes de retomar |
| Plano de implementação AUD26 | [execplan-aud26-implementation-2026-10-01.md](plans/execplan-aud26-implementation-2026-10-01.md) | Programa anterior preservado; consultar seus próprios registros de execução |

## Evidências e relatórios

- [Relatório da auditoria atual](reports/relatorio-auditoria-2026-10-07.md): notas das 26 áreas, achados A01–A20, comandos, exit codes e limites.
- [Roadmap atual](roadmap-auditoria-2026-10-07.md): oito marcos M0–M7, sequência, gates de passagem e dependências externas.
- [Backlog atual](backlog-auditoria-2026-10-07.md): 43 tarefas AUD07 com prioridades, dependências, tamanhos relativos e critérios de aceite.
- [Evidência M0 (AUD07-03–09)](reports/evidence/auditoria-2026-10-07/fix-gates-1.md): gates por alvo, `make ci` em checkout limpo com dependências só dos locks.
- [Evidência M1 (AUD07-10–12)](reports/evidence/auditoria-2026-10-07/fix-gates-2.md): correções de idempotência e de lifecycle, discriminação por reversão, cobertura de lanes e correções de `PYTHONPATH`.
- [Evidência AUD07-13 (política default-deny de rotas)](reports/evidence/auditoria-2026-10-07/route-policy.md): paridade registro ↔ handler via `ROUTERS`, imposição declarada vs. executada, limite de escopo próprio, discriminação por reversão e gates do candidato.
- [Evidência AUD07-14 (`production_safe` fail-closed)](reports/evidence/auditoria-2026-10-07/resilience-fail-closed.md): admissão de port sem probe, `health_check` sem fallback, teste de admissão na composição, discriminação e gates.
- [Evidência AUD07-15 (supply chain npm)](reports/evidence/auditoria-2026-10-07/npm-supply-chain.md): `sharp`/`source-map-js` pins explícitos, gates web, E2E 339 e `pip-audit` limpo.
- [Evidência AUD07-17 (type checking gradual)](reports/evidence/auditoria-2026-10-07/python-typecheck.md): mypy 2.4.0 no `make typecheck`, baseline versionado 0/0 em contratos+autorização, discriminação e gates.
- [Evidência AUD07-18 (destino versionável da evidência)](reports/evidence/auditoria-2026-10-07/evidence-destination.md): árvore de 50 351 ficheiros/1,86 GB → 411 ficheiros/≈3,5 MB, bolsa *content-addressed* com manifesto ancorado por hash, incidente do primeiro `apply` e discriminação A/B/C.
- [Evidência AUD07-19 (higiene do worktree)](reports/evidence/auditoria-2026-10-07/untracked-hygiene.md): `.gitignore` generalizado (`.opencode/`, `.agent/*.lock`), regressão `test_untracked_hygiene.py` com `git check-ignore --no-index`, checkout limpo com 0 linhas, 0 crescimento em `make ci`/`make test`, experimentos E1–E4 (E4 = checkout novo com `make validate` = 0 inputs de CI trackeados) e as opções A/B/C de decisão.
- [Evidência AUD07-43 (7 falhas de CI do checkout novo)](reports/evidence/auditoria-2026-10-07/ci-lanes-remediation.md): run `37768041811`, causa raiz por job, correções (referência legada do diferencial, control-inputs, CVEs do `test.lock`, harnesses AUD03, `pyjwt`, watchdog de 900 s, corrida no teste de shutdown), resultado do push `4d2ac2c` (4 lanes verdes), PHASE3 `--verify` mantido vermelho por decisão explícita de 08/10/2026, `State of Art / release integrity` vermelho por envelopes de runtime não vinculados (pré-existente) e nenhum gate alterado.
- Pontes para material movido pela política de evidência (AUD07-18): [implementation-aud03-2026-10-03](reports/evidence/implementation-aud03-2026-10-03/README.md), [ci-restore](reports/evidence/implementation-aud03-2026-10-03/ci-restore/README.md), [runtime](reports/evidence/implementation-aud03-2026-10-03/runtime/README.md) — o conteúdo está na bolsa `artifacts/evidence-store/`.
- [Baseline das reproduções A02/A03](reports/evidence/auditoria-2026-10-07/baseline-gates.md): estado pré-fix com comandos, exit codes e os `.json`/`.stderr` originais preservados.
- [Snapshot da auditoria de 03/10/2026](reports/evidence/auditoria-2026-10-03/scorecard.json), [roadmap AUD03](roadmap-auditoria-2026-10-03.md) e [backlog AUD03](backlog-auditoria-2026-10-03.md): baseline histórica de 29 áreas, preservada sem encerramento automático dos seus itens.
- [ExecPlan de implementação AUD03](plans/execplan-aud03-implementation-2026-10-03.md): escopo, ownership, execução e limites; implementação não equivale a aceite.
- [Continuação das melhorias de 03/10/2026](reports/continuacao-melhorias-2026-10-03.md): correções desta retomada, testes e limites de aceite.
- [Continuação das melhorias de 04/10/2026](reports/continuacao-melhorias-2026-10-04.md): preflight de escopo 0008 somente de leitura, provas PostgreSQL e limites do inventário instalado.
- [Reauditoria anterior de 01/10/2026](reports/relatorio-auditoria-geral-2026-10-01.md), [roadmap AUD26](roadmap-auditoria-2026-10-01.md), [backlog AUD26](backlog-auditoria-2026-10-01.md) e [ExecPlan AUD26](plans/execplan-aud26-implementation-2026-10-01.md): contexto anterior preservado, sem encerramento automático dos seus itens.
- [Baseline preservada](reports/relatorio-auditoria-local-2026-10-01-base.md): scorecard anterior desta rodada.
- [Roadmap histórico](roadmap-auditoria-atual.md) e [backlog histórico](backlog-auditoria-atual.md): snapshots superseded, preservados para rastreabilidade.
- [External evidence blockers](reports/external-evidence-blockers.md): dependências e autorizações ainda ausentes.
- [Relatórios com datas anteriores](reports/): preservados para rastreabilidade; não substituir a evidência do checkout atual.

## Regras de frescor

Todo novo relatório ou evidência deve informar:

1. data/hora UTC;
2. SHA e estado do worktree;
3. comando/procedimento completo e exit code;
4. artefato produzido e validade;
5. dependências externas e autorizações usadas;
6. limitações (`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL` ou `INCONCLUSIVO`).

Não há promoção baseada apenas em média de notas. Um gate obrigatório falho, ausente ou externo mantém o candidato em `NO-GO`.

# Índice canônico de documentação

**Status:** CURRENT para o checkout auditado.
**Atualização de planejamento — 24/10/2026:** a [auditoria AUD24](<reports/relatorio-auditoria-2026-10-24.md>) registra **74,7/100** e produção `NO-GO` no checkout `48e383c` com worktree sujo. A decisão AUD24-D1 foi ratificada no [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) (A+ em duas etapas; OIDC fora do perfil de produção). A primeira onda e as etapas 1–2 da identidade foram executadas localmente: G0 PASS, 6.040 testes Python, 263 web, 1.875 testes de API (79,22%) e CONTRACT verde; permanecem o gate live PostgreSQL/IdP, a tipagem AUD24-018, o candidato sujo e as ondas externas, portanto `NO-GO`. O [plano executivo AUD24](<plans/execplan-aud24-2026-10-24.md>), o [roadmap AUD24](<roadmap-auditoria-2026-10-24.md>) e o [backlog AUD24](<backlog-auditoria-2026-10-24.md>) propõem 29 contratos novos, herdam as obrigações PROD12 e mantêm oito marcos. Planejamento `PROPOSTO`: nenhum item foi adotado no [controlador](../.agent/backlog.json), nenhum aceite anterior foi alterado e nenhuma execução externa, DDL, deploy ou promoção foi autorizada.
**Atualização de planejamento — 15/10/2026:** o [relatório AUD15](<reports/relatorio-auditoria-2026-10-15.md>) fundamenta o [backlog complementar](<backlog-auditoria-2026-10-15.md>) com 24 contratos novos e o [roadmap AUD15](<roadmap-auditoria-2026-10-15.md>) com oito marcos. As obrigações externas continuam nos IDs PROD12 existentes; novos IDs não foram adotados por este planejamento, nenhum aceite anterior foi alterado e produção permanece `NO-GO`. Resultados de testes citados são os da auditoria, não novas execuções nesta elaboração.
**Atualização de planejamento — 12/10/2026:** [roadmap de produção](roadmap-producao-2026-10-12.md) e [backlog PROD12](backlog-producao-2026-10-12.md) propostos com 56 tarefas e oito marcos. A [baseline de 12/10](reports/baseline-producao-2026-10-12.md) registra achados/resultados do SHA `48e383c25ca4af32aa7ffe7e2367360ca9742c58`; a suíte ampliada falhou (7.713 passed, 6 failed, 221 skipped) e `make validate` ficou bloqueado por raiz do run. Nenhum código/gate/ledger/aceite anterior foi alterado pelo planejamento; implementação e produção não autorizadas por esses documentos. Promoção `NO-GO`.

**Checkpoint de execução anterior:** retomada local de 09/10/2026. AUD07-01–26, 44–46 concluídas localmente; AUD07-27 parcial por revisão independente e vínculo de evidência ao candidato; AUD07-43 mantém gates externos abertos. O [relatório da retomada](reports/retomada-2026-10-09.md) registra os resultados atuais. A auditoria de 07/10 permanece baseline histórica de 64,2/100 em 26 áreas, sem recalcular a nota. Promoção `NO-GO`. O scorecard de 03/10 tem escopo diferente e não é diretamente comparável.
**Regra:** documentos com status `HISTORICAL`, `REFERENCE / NOT_RUN` ou fase anterior não comprovam o estado executável atual.

## Autoridades atuais

| Assunto | Fonte canônica | Estado |
|---|---|---|
| Estado do produto e comandos | [README](../README.md) | CURRENT |
| Contribuição e segurança operacional | [CONTRIBUTING](../CONTRIBUTING.md) | CURRENT |
| Arquitetura executável | [system-architecture.md](architecture/system-architecture.md) e [production-runtime.md](architecture/production-runtime.md) | CURRENT, runtime externo NOT_RUN |
| Limites de dependência | [dependency-boundaries.json](architecture/dependency-boundaries.json) | CURRENT como regra automatizada |
| Segurança e autorização | [authorization.md](architecture/authorization.md) e [production-runtime.md](architecture/production-runtime.md) | CURRENT, integração externa pendente; `security/` preserva decisões e evidências dos legados |
| Operação e promoção | [release-readiness.md](operations/release-readiness.md) | REFERENCE / NOT_RUN |
| Baseline do planejamento de produção | [baseline-producao-2026-10-12.md](reports/baseline-producao-2026-10-12.md) | SNAPSHOT observado em 12/10; não é nova execução nem aprovação |
| Roadmap para produção | [roadmap-producao-2026-10-12.md](roadmap-producao-2026-10-12.md) | PROPOSTO; sequência/gates, sem status de execução concorrente |
| Backlog para produção | [backlog-producao-2026-10-12.md](backlog-producao-2026-10-12.md) | Especificação de 56 contratos; adoção anterior em TODO registrada no plano ativo; status/aceite somente no controlador, sem encerramento pelo planejamento AUD15 |
| Snapshot mais recente de auditoria | [relatório AUD24](<reports/relatorio-auditoria-2026-10-24.md>) | SNAPSHOT observado em 24/10; 74,7/100; NO-GO, sem reexecução externa |
| Decisão de auditoria/revogação | [ADR-024](<architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md>) | RATIFICADA em 24/10; A+ em duas etapas; produção não autorizada |
| Pack RAG candidato | [evidência](<reports/evidence/auditoria-2026-10-24/rag-pack-candidate.md>) | 12 casos sintéticos; thresholds PASS; revisão de domínio pendente |
| Decisão D04 AUD24 | [pacote de corpus](<operations/d04-aud24-corpus-decision.md>) | PROPOSTO; revisão de domínio pendente |
| Smoke Orca/AT-SPI | [evidência](<reports/evidence/auditoria-2026-10-24/accessibility-at-spi-smoke.md>) | PARCIAL; transporte AT-SPI provado, auditoria humana NOT_RUN |
| Lab Docker M5 | [evidência](<reports/evidence/auditoria-2026-10-24/m5-lab-runtime.md>) | PostgreSQL/Redis/S3/Qdrant e **multi-worker 8/8 crash points PASS** em containers |
| Pacote externo AUD24 | [M5–M7](<operations/aud24-m5-m7-external-package.md>) | PREPARADO; authority matrix, comandos, aborto e bloqueios D01–D07 |
| Primeira onda AUD24 | [escopo executável](<plans/aud24-first-wave-2026-10-24.md>) | PREPARADO; AUD24-001/003, gate G0, sem executar |
| Plano executivo AUD24 | [plano de 24/10](<plans/execplan-aud24-2026-10-24.md>) | PROPOSTO; workstreams, decisões humanas, gates e primeiros 10 dias |
| Roadmap AUD24 | [roadmap de 24/10](<roadmap-auditoria-2026-10-24.md>) | PROPOSTO; oito marcos M0–M7, dependências e gates locais/externos/decisão |
| Backlog AUD24 | [backlog de 24/10](<backlog-auditoria-2026-10-24.md>) | PROPOSTO; 29 contratos novos e herança PROD12, sem ledger de execução |
| Snapshot AUD15 preservado | [relatório AUD15](<reports/relatorio-auditoria-2026-10-15.md>) | Observação histórica de 14/10 local–15/10 UTC; 74,6/100; NO-GO, sem reexecução neste planejamento |
| Backlog complementar AUD15 | [backlog de 15/10](<backlog-auditoria-2026-10-15.md>) | PROPOSTO; 24 contratos novos, vínculos PROD12 e aceites, sem novo ledger de execução |
| Roadmap complementar AUD15 | [roadmap de 15/10](<roadmap-auditoria-2026-10-15.md>) | PROPOSTO; oito marcos, dependências e gates locais/externos/promoção |
| Snapshot AUD07 preservado | [relatório de 07/10/2026](reports/relatorio-auditoria-2026-10-07.md) | HISTORICAL como baseline de 07/10; não substitui a observação AUD24 |
| Roadmap desta auditoria | [roadmap-auditoria-2026-10-07.md](roadmap-auditoria-2026-10-07.md) | CURRENT como planejamento de referência |
| Backlog desta auditoria | [backlog-auditoria-2026-10-07.md](backlog-auditoria-2026-10-07.md) | CURRENT como contrato de escopo e aceite; 46 tarefas AUD07, **AUD07-01–26 e 44–46 concluídas localmente; 27 parcial; 28–43 dependem de evidência externa** |
| Snapshot anterior (AUD03) | [scorecard de 03/10/2026](reports/evidence/auditoria-2026-10-03/scorecard.json) | HISTORICAL como baseline anterior; escopo de 29 áreas, não comparável |
| Roadmap anterior (AUD03) | [roadmap-auditoria-2026-10-03.md](roadmap-auditoria-2026-10-03.md) | HISTORICAL; preservado para rastreabilidade |
| Backlog anterior (AUD03) | [backlog-auditoria-2026-10-03.md](backlog-auditoria-2026-10-03.md) | HISTORICAL; 36 tarefas AUD03 sem encerramento automático |
| Plano de implementação AUD03 | [execplan-aud03-implementation-2026-10-03.md](plans/execplan-aud03-implementation-2026-10-03.md) | IN_PROGRESS; registros de execução separados do planejamento; aceite global não demonstrado |
| Checkpoint das 36 tarefas AUD03 | [execution-checkpoint-v2.json](reports/evidence/implementation-aud03-2026-10-03/execution-checkpoint-v2.json) | Continuação local; nenhum aceite integral declarado; v1 preservado como predecessor; conferir hashes e revisões antes de retomar |
| Plano de implementação AUD26 | [execplan-aud26-implementation-2026-10-01.md](plans/execplan-aud26-implementation-2026-10-01.md) | Programa anterior preservado; consultar seus próprios registros de execução |
| Retomada atual da construção | [plano de 09/10](plans/execplan-retomada-2026-10-09.md) e [relatório](reports/retomada-2026-10-09.md) | Correções locais AUD07; conferir resultados definitivos no relatório |
| Testes externos não executados | [inventário de skips](reports/skips-2026-10-09.md) | 221 node IDs classificados por dependência e gate |
| Auditoria congelada da barra | [current-triple-aaa-gap-audit.md](reports/current-triple-aaa-gap-audit.md) | HISTORICAL, bytes imutáveis exigidos pelo quality bar; o título original não estabelece frescor |

## Evidências e relatórios

- [Relatório AUD24](<reports/relatorio-auditoria-2026-10-24.md>): 74,7/100, comandos/exit codes, 26 dimensões, achados AUD24-01…12 e limites; leitura read-only do checkout sujo.
- [Plano executivo AUD24](<plans/execplan-aud24-2026-10-24.md>): objetivo, workstreams, marcos, riscos, governança e decisões humanas.
- [Roadmap AUD24](<roadmap-auditoria-2026-10-24.md>): oito marcos, caminho crítico, portões externos e critérios de parada.
- [Backlog AUD24](<backlog-auditoria-2026-10-24.md>): 29 contratos com prioridade, tamanho, dependências, aceite e evidência; herança PROD12 sem duplicação.
- [Relatório da auditoria de 15/10](<reports/relatorio-auditoria-2026-10-15.md>): baseline histórica de 74,6/100 e achados AUD15-01…13.
- [Relatório da auditoria atual](reports/relatorio-auditoria-2026-10-07.md): notas das 26 áreas, achados A01–A20, comandos, exit codes e limites.
- [Roadmap atual](roadmap-auditoria-2026-10-07.md): oito marcos M0–M7, sequência, gates de passagem e dependências externas.
- [Backlog atual](backlog-auditoria-2026-10-07.md): 46 tarefas AUD07 com prioridades, dependências, tamanhos relativos e critérios de aceite.
- [Evidência M0 (AUD07-03–09)](reports/evidence/auditoria-2026-10-07/fix-gates-1.md): gates por alvo, `make ci` em checkout limpo com dependências só dos locks.
- [Evidência M1 (AUD07-10–12)](reports/evidence/auditoria-2026-10-07/fix-gates-2.md): correções de idempotência e de lifecycle, discriminação por reversão, cobertura de lanes e correções de `PYTHONPATH`.
- [Evidência AUD07-13 (política default-deny de rotas)](reports/evidence/auditoria-2026-10-07/route-policy.md): paridade registro ↔ handler via `ROUTERS`, imposição declarada vs. executada, limite de escopo próprio, discriminação por reversão e gates do candidato.
- [Evidência AUD07-14 (`production_safe` fail-closed)](reports/evidence/auditoria-2026-10-07/resilience-fail-closed.md): admissão de port sem probe, `health_check` sem fallback, teste de admissão na composição, discriminação e gates.
- [Evidência AUD07-15 (supply chain npm)](reports/evidence/auditoria-2026-10-07/npm-supply-chain.md): `sharp`/`source-map-js` pins explícitos, gates web, E2E 339 e `pip-audit` limpo.
- [Evidência AUD07-17 (type checking gradual)](reports/evidence/auditoria-2026-10-07/python-typecheck.md): mypy 2.4.0 no `make typecheck`, baseline versionado 0/0 em contratos+autorização, discriminação e gates.
- [Evidência AUD07-18 (destino versionável da evidência)](reports/evidence/auditoria-2026-10-07/evidence-destination.md): árvore de 50 351 ficheiros/1,86 GB → 411 ficheiros/≈3,5 MB, bolsa *content-addressed* com manifesto ancorado por hash, incidente do primeiro `apply` e discriminação A/B/C.
- [Evidência AUD07-19 (higiene do worktree)](reports/evidence/auditoria-2026-10-07/untracked-hygiene.md): `.gitignore` generalizado (`.opencode/`, `.agent/*.lock`), regressão `test_untracked_hygiene.py` com `git check-ignore --no-index`, checkout limpo com 0 linhas, 0 crescimento em `make ci`/`make test`, experimentos E1–E4 (E4 = checkout novo com `make validate` = 0 inputs de CI trackeados) e as opções A/B/C de decisão.
- [Evidência AUD07-43 (7 falhas de CI do checkout novo)](reports/evidence/auditoria-2026-10-07/ci-lanes-remediation.md): run `37768041811`, causa raiz por job, correções (referência legada do diferencial, control-inputs, CVEs do `test.lock`, harnesses AUD03, `pyjwt`, watchdog de 900 s, corrida no teste de shutdown), resultado final do CI (6 das 7 pipelines verdes; PHASE3 `--verify` mantido vermelho por decisão de 08/10/2026 e `State of Art / release integrity` por envelopes de runtime não vinculados, ambos pré-existentes/decididos) e nenhum gate alterado. §9 (09/10): lane RUNTIME do `quality` — `a9ee017` (`npm ci`) e `ce7a579` (`make control-inputs-restore`), verificação ao vivo por `workflow_dispatch` (`37871005009`, `37872405794`) com bloqueios 33 → 26 → 25 e nenhum defeito local, decomposição dos 4 sub-checks de `supply-chain` em AUD07-44 e AUD07-45.
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

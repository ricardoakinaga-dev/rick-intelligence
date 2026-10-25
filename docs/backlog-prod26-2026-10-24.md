# Backlog PRD26 — 22 contratos para fechar a distância até produção

**Data:** 24/10/2026 (America/Sao_Paulo) · **UTC:** 25/10/2026, 01:43
**Estado de publicação:** `PROPOSTO` · **Produto:** `NO-GO`
**Baseline:** [avaliação independente AVAL24](<reports/avaliacao-independente-2026-10-24.md>) — 78,0/100, HEAD `dc79ec6`, worktree limpo.
**Documentos irmãos:** [plano executivo](<plans/execplan-prod26-2026-10-24.md>) e [roadmap](<roadmap-prod26-2026-10-24.md>).

Este documento é **especificação**, não ledger de execução. Os 22 contratos são de **coordenação, aceite e lacunas reais**; as obrigações técnicas já especificadas em AUD24/PROD12 permanecem com seus IDs e são referenciadas na §5, sem duplicação. Nenhum item é adotado no [controlador](<../.agent/backlog.json>) por este documento.

## 1. Regras

- **IDs `PRD26-001…053` são tarefas.** Não confundir com AVAL24 (avaliação), AUD24 (auditoria) ou PROD12 (programa anterior).
- **Prioridade:** `P0` = bloqueia segurança, dados, release ou decisão; `P1` = obrigatório antes da candidatura; `P2` = robustez/manutenção.
- **Tamanho:** `P` pequeno e delimitado; `M` múltiplas fronteiras; `G` grande ou dependente de ambiente/decisão. Não são dias.
- **Dependências são AND.** Preparação pode avançar; o aceite exige todos os predecessores.
- **Um writer por arquivo/recurso.** Dois contratos não editam o mesmo arquivo em paralelo.
- **Sem weakening:** proibido remover teste, `skip`/`xfail`, reduzir floor, alargar allowlist ou converter `NOT_RUN` em PASS.
- **Aceite observável:** “implementado” não é `DONE`; `DONE` exige critério, evidência vinculada e aceite registrado.
- **Herança não é duplicação:** quando a obrigação técnica existe em AUD24/PROD12, o contrato PRD26 só coordena sequência, evidência e aceite; o critério técnico herdado permanece autoritativo.

## 2. Definition of Done comum

1. Candidato identificado por SHA + branch + estado do worktree + fingerprint de configuração.
2. Procedimento completo, ambiente, exit code, timestamp UTC, artefatos e hashes.
3. Defeito reproduzido antes; o novo teste falha na versão antiga e passa na corrigida.
4. Cobertura de sucesso, erro, callback tardio, concorrência e escopo quando aplicável.
5. Revisão independente para identidade, auditoria, dados, segurança, RAG e release; o autor não aprova o próprio patch.
6. Nenhum gate enfraquecido; nenhuma evidência histórica apresentada como atual.
7. Limitações e riscos residuais explícitos (`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL`).

## 3. Visão por épico

| Épico | Contratos | IDs | Foco |
|---|---:|---|---|
| E0 — Governança e aceite | 3 | 001–003 | Baseline, aceite local, docs correntes |
| E1 — Engenharia sustentável | 4 | 010–013 | Toolchain, tipos, contrato único, cobertura |
| E2 — IA/RAG e acessibilidade | 3 | 020–022 | D04, avaliação live, AT humano |
| E3 — Dados e restore | 3 | 030–032 | Stores, golden path, restore |
| E4 — Identidade, providers e operação | 5 | 033, 040–043 | Carga/chaos/soak, IdP, provider, observabilidade, worker A/B |
| E5 — Release e decisão | 4 | 050–053 | CI remoto, supply chain, packet, decisão |

**Total: 22 contratos — 12 P0, 9 P1, 1 P2.**

## 4. Fila e dependências

| ID | Marco | Pri | Tam | Dono sugerido | Depende | Herda |
|---|---|---|---|---|---|---|
| PRD26-001 | M0 | P0 | P | Lead/QA | — | AVAL24; AUD24-001/003 |
| PRD26-002 | M1 | P0 | M | Lead/QA + autoridade | 001 | AUD24 M0–M3; PROD12-026 |
| PRD26-003 | M1 | P1 | M | Docs/Lead | 001 | AUD24-040; PROD12-020 |
| PRD26-010 | M2 | P1 | M | Plataforma | 002 | AUD24-032; PROD12-016 |
| PRD26-011 | M2 | P1 | M | API/worker/qualidade | 002 | AUD24-042; PROD12-017 |
| PRD26-012 | M2 | P1 | M | API/web | 002 | AUD24-041 |
| PRD26-013 | M2 | P2 | M | QA/arquitetura | 011 | AUD24-043; PROD12-018 |
| PRD26-020 | M3 | P0 | G | Domínio/RAG | 002 | AUD24-044; PROD12-038 |
| PRD26-021 | M3 | P1 | G | RAG/provider | 020 | PROD12-033/038 |
| PRD26-022 | M3 | P1 | M | QA/design | 002 | AUD24-045; PROD12-041 |
| PRD26-030 | M4 | P0 | G | DBA/SRE | 002, 010 | PROD12-027–032 |
| PRD26-031 | M4 | P0 | G | Ingestão/QA | 030 | PROD12-034/037 |
| PRD26-032 | M4 | P0 | G | Recovery/DBA/SRE | 030, 031 | PROD12-045 |
| PRD26-033 | M5 | P0 | G | SRE/performance | 030–032 | PROD12-046–048 |
| PRD26-040 | M5 | P0 | G | Identity/segurança | 030, 002 | PROD12-035 |
| PRD26-041 | M5 | P1 | G | Provider/RAG | 021, 030 | PROD12-033 |
| PRD26-042 | M5 | P1 | G | Observabilidade/SRE | 030, 040 | PROD12-043/044 |
| PRD26-043 | M5 | P1 | G | Worker/DBA | 030, 040 | PROD12-036/008–010 |
| PRD26-050 | M6 | P0 | M | Release/CI | 011–012, 022, 033, 040–043 | AUD24-031/034; PROD12-050 |
| PRD26-051 | M6 | P0 | G | Release/supply chain | 050 | PROD12-028 |
| PRD26-052 | M6 | P0 | G | Lead + revisores | 050, 051 | PROD12-051/052 |
| PRD26-053 | M7 | P0 | M | Autoridade humana | 052 | PROD12-053–056 |

## 5. Contratos

### E0 — Governança e aceite

#### PRD26-001 — Baseline executável e reconciliação PRD26 ↔ AUD24/PROD12

**Prioridade:** P0 · **Tamanho:** P · **Dono:** Lead/QA · **Depende:** —
**Entrega:** baseline AVAL24 vinculada ao SHA `dc79ec6`, branch e worktree; matriz de 22 contratos sem sobreposição de IDs; confirmação de herança; links no INDEX; quality bar e comandos de evidência congelados.
**Aceite:** matriz versionada; zero ID duplicado; `make docs-check` e `make validate` verdes; controlador intacto; nenhum aceite anterior alterado.
**Evidência:** matriz + `git rev-parse HEAD` + `git status` + logs dos gates.
**Herda:** AVAL24; AUD24-001/003.

#### PRD26-002 — Fechar a lacuna de aceite local

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Lead/QA + autoridade · **Depende:** 001
**Entrega:** classificação de cada item AUD24/PROD12 já implementado como `DONE`, `VERIFY` com evidência ou `BLOCKED_EXTERNAL` justificado; envelope por item; atualização do controlador somente após PRD26-D1.
**Aceite:** 100% dos itens locais com disposição; nenhum `DONE` por documento; nenhum item `VERIFY` sem artefato; revisão independente de aceite.
**Evidência:** matriz item → status → evidência → limitação.
**Herda:** AUD24 M0–M3; PROD12-026.

#### PRD26-003 — Alinhar documentação corrente e travar frescor

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Docs/Lead · **Depende:** 001
**Entrega:** correção de `production-runtime.md`, `operations/release-readiness.md`, `roadmap-auditoria-2026-10-24.md` e `README.md` onde a evidência M0–M5 superou o texto; revisão de citações relativas; atualização do INDEX.
**Aceite:** nenhuma afirmação `CURRENT` contradiz a evidência; `make docs-check` 0 erros; links novos resolvem; revisão de frescor sem achado alto.
**Evidência:** diff + lista de claims corrigidos + docs-check.
**Status local (24/10):** `VERIFY` — drift corrigido; ver [onda local 1](<reports/evidence/prd26-2026-10-24/local-wave-1.md>).
**Herda:** AUD24-040; PROD12-020.

### E1 — Engenharia sustentável

#### PRD26-010 — Toolchain reproduzível e E2E portátil

**Prioridade:** P1 · **Tamanho:** M · **Dono:** Plataforma · **Depende:** 002
**Entrega:** bootstrap em host limpo com Python 3.12.3, Node 22.19.0, npm 10.9.3; `.runtime/toolchain` reproduzível; `TMPDIR` curto e documentado; nenhum caminho dependente do host.
**Aceite:** `make ci` e `make web-validate` verdes no toolchain declarado em checkout limpo; E2E sem ajuste manual de ambiente; Node 24 não é evidência do contrato.
**Evidência:** log de bootstrap limpo + versões + gates.
**Status local (24/10):** `VERIFY` — `TMPDIR` curto implementado; caminho longo 5/5 e matriz completa 363/363. Ver [onda local 1](<reports/evidence/prd26-2026-10-24/local-wave-1.md>).
**Herda:** AUD24-032; PROD12-016.

#### PRD26-011 — Tipagem ampliada nos caminhos de risco

**Prioridade:** P1 · **Tamanho:** M · **Dono:** API/worker/qualidade · **Depende:** 002
**Entrega:** mypy para rotas, services, worker, identity/knowledge stores; baseline explícito; nenhum `ignore` genérico; correções incrementais.
**Aceite:** `make typecheck` verde no novo escopo; baseline versionado; nenhuma regressão de tipos; revisão de tipos.
**Evidência:** baseline + log de typecheck + diff.
**Status local (24/10):** `VERIFY` — mypy ampliado para 19 roots, 0/0; rotas/services/worker ainda pendentes. Ver [onda local 1](<reports/evidence/prd26-2026-10-24/local-wave-1.md>).
**Herda:** AUD24-042; PROD12-017.

#### PRD26-012 — Fonte única de contrato OpenAPI → TypeScript

**Prioridade:** P1 · **Tamanho:** M · **Dono:** API/web · **Depende:** 002
**Entrega:** geração de tipos a partir do OpenAPI ou validação runtime equivalente; eliminação do espelho manual de 479 linhas; teste de drift no CI.
**Aceite:** nenhum schema duplicado; CI falha em drift; build web e contrato verdes; nenhuma quebra de contrato sem migração.
**Evidência:** gerador/validador + teste de drift + OpenAPI.
**Herda:** AUD24-041.

#### PRD26-013 — Cobertura com denominadores e mutation testing

**Prioridade:** P2 · **Tamanho:** M · **Dono:** QA/arquitetura · **Depende:** 011
**Entrega:** cobertura sobre todos os módulos declarados; mutation testing nos caminhos de auth/audit/queue; relatório de sobreviventes.
**Aceite:** floors preservados; denominadores explícitos; mutantes críticos mortos ou disposição registrada; nenhuma redução de gate.
**Evidência:** coverage + mutation report + baseline.
**Herda:** AUD24-043; PROD12-018.

### E2 — IA/RAG e acessibilidade

#### PRD26-020 — Decisão D04 e corpus representativo

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Domínio/RAG · **Depende:** 002
**Entrega:** decisão D04 com corpus, proveniência, licença, labels, estratos, thresholds e risco clínico; pack representativo com casos single-hop, multi-hop, distrator, top-1 erra/top-3 recupera, abstenção real, ACL pré-filtro, claim não suportado e limite.
**Aceite:** D04 assinado; corpus/licença verificáveis; thresholds por grupo; nenhum pack sintético apresentado como representativo; revisão de domínio.
**Evidência:** D04 + corpus + manifest + relatório de revisão.
**Herda:** AUD24-044; PROD12-038.

#### PRD26-021 — Avaliação live de retrieval, citação e abstenção

**Prioridade:** P1 · **Tamanho:** G · **Dono:** RAG/provider · **Depende:** 020
**Entrega:** avaliação com modelo/provider aprovados; recall/MRR/nDCG, faithfulness, citation precision/recall/completeness, abstenção e unsupported claim; seeds, variância e latência descritiva.
**Aceite:** métricas por grupo; abstenção e claim medidos de verdade; nenhuma alegação clínica; custo/budget registrados.
**Evidência:** relatório + artefatos + provider/modelo + custos.
**Herda:** PROD12-033/038.

#### PRD26-022 — Auditoria humana de acessibilidade e WCAG

**Prioridade:** P1 · **Tamanho:** M · **Dono:** QA/design · **Depende:** 002
**Entrega:** auditoria de teclado, leitor de tela, zoom, contraste e foco nos fluxos críticos; correções; relatório de lacunas; nenhuma alegação de WCAG global.
**Aceite:** nenhum bloqueio crítico nos fluxos principais; lacunas documentadas; revisor humano; evidência de browser/AT.
**Evidência:** relatório + capturas + achados + correções.
**Herda:** AUD24-045; PROD12-041.

### E3 — Dados e restore

#### PRD26-030 — Selar a onda de dados reais

**Prioridade:** P0 · **Tamanho:** G · **Dono:** DBA/SRE · **Depende:** 002, 010
**Entrega:** PostgreSQL/Redis/Qdrant/S3 em ambiente descartável autorizado; migrations, constraints, índices, planos, queue fencing, DLQ, replay e retenção; tenant A/B.
**Aceite:** todos os gates de dados `PASS` no mesmo artefato; nenhum `NOT_RUN` obrigatório; nenhuma prova simulada; evidência de isolamento.
**Evidência:** logs + artefatos JSON + migrations + DSN/ambiente autorizado.
**Status local (24/10):** `VERIFY` parcial — PostgreSQL/Redis/Qdrant/S3 `PASS` em lab loopback; golden path e restore pendentes. Ver [gates locais](<reports/evidence/prd26-2026-10-24/local-runtime-gates.md>).
**Herda:** PROD12-027–032.

#### PRD26-031 — Golden path de ingestão com crash/replay

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Ingestão/QA · **Depende:** 030
**Entrega:** upload → fila → lease → indexação → retrieval → delete/reindex; crash boundaries; multi-worker A/B; nenhuma publicação duplicada.
**Aceite:** E2E com crash/replay; recuperação de lease; ausência de duplicata; estado/attempt/audit consistentes.
**Evidência:** relatório E2E + matriz de crash + artefatos.
**Status local (24/10):** `VERIFY` — upload 202, worker `run_once` **succeeded=1**, job `published/SUCCEEDED`, documento `published`, 1 chunk e 1 ponto Qdrant; falha anterior `storage_unavailable` era FK de `created_by` e foi corrigida. Publicação do documento e resposta grounded com citação `PASS` local (`APPROVED_EVIDENCE`, `publication_validation=verified`); fixture de provider não é modelo real. Ver [gates locais](<reports/evidence/prd26-2026-10-24/local-runtime-gates.md>).
**Herda:** PROD12-034/037.

#### PRD26-032 — Restore/DR integrado com RPO/RTO

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Recovery/DBA/SRE · **Depende:** 030, 031
**Entrega:** `seed → backup → destroy → restore → rebuild → verify`; checksums, counts, ACL pós-restore, RPO/RTO e rollback/roll-forward.
**Aceite:** restore verificado; RPO/RTO medidos; tenant A/B pós-restore; runbook atualizado; nenhuma simulação local aceita como DR.
**Evidência:** relatório de restore + tempos + checksums + runbook.
**Status local (24/10):** `VERIFY` parcial — `PASS` local no gate formal `make restore-runtime`: seed→backup→destroy→restore→rebuild→verify, RPO 0,0 s e RTO 3,823 s, componentes PostgreSQL/object/jobs/audit/evidence/Qdrant; `production_safe=false`; envelope Phase 3 `BLOCKED_EXTERNAL` por preflight de topologia ausente. Ver [gates locais](<reports/evidence/prd26-2026-10-24/local-runtime-gates.md>).
**Herda:** PROD12-045.

### E4 — Identidade, providers e operação

#### PRD26-033 — Performance, chaos e soak

**Prioridade:** P0 · **Tamanho:** G · **Dono:** SRE/performance · **Depende:** 030–032
**Entrega:** carga 1/10/50/100 em topologia production-shaped; cenários de falha (latência, 5xx, timeout, partição); soak curto e prolongado com memória/leak.
**Aceite:** budgets de p50/p95/p99, throughput, erro e memória; nenhum leak; falhas recuperam; limites explícitos.
**Evidência:** relatórios de carga/chaos/soak + métricas + custos.
**Herda:** PROD12-046–048.

#### PRD26-040 — IdP real, membership e multi-réplica

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Identity/segurança · **Depende:** 030, 002
**Entrega:** IdP/OIDC ou nativo Postgres conforme PRD26-D3; membership, sessão, revogação, logout e multi-workspace; duas réplicas de API e rate limiter compartilhado.
**Aceite:** matriz de identidade/tenant sem vazamento; revogação e logout comprovados; cross-tenant negativo; nenhum cookie enganoso.
**Evidência:** matriz + logs + IdP/config + negativos.
**Status local (24/10):** `VERIFY` parcial — Keycloak 26.7.3, realm `rick`, client `rick-api`, password grant `PASS`, verificação OIDC real (RS256/issuer/audience), `GET /api/v1/auth/me` **200** e `POST /api/v1/chat` **200** (abstenção segura `ESCALATE`/`NO_EVIDENCE`) via Uvicorn real em `127.0.0.1:18000`, com composição externa local e 14 checks `true`; membership store, revogação, multi-réplica e readiness de produção `NOT_RUN`. Ver [gates locais](<reports/evidence/prd26-2026-10-24/local-runtime-gates.md>).
**Herda:** PROD12-035; ADR-024.

#### PRD26-041 — Provider/RAG live, budgets e falhas

**Prioridade:** P1 · **Tamanho:** G · **Dono:** Provider/RAG · **Depende:** 021, 030
**Entrega:** provider real ou servidor local aprovado; streaming, cancelamento, timeout, retry, circuit breaker, budget e falha; nenhum segredo em log/trace.
**Aceite:** matriz de capability; falha/cancelamento/budget; fallback seguro; custo dentro do orçamento.
**Evidência:** relatório + traces + custos + logs redigidos.
**Status local (24/10):** `VERIFY` parcial — contrato HTTP `PASS` contra provider fixture local; provider real/TLS pendentes. Ver [gates locais](<reports/evidence/prd26-2026-10-24/local-runtime-gates.md>).
**Herda:** PROD12-033.

#### PRD26-042 — Observabilidade distribuída e alertas

**Prioridade:** P1 · **Tamanho:** G · **Dono:** Observabilidade/SRE · **Depende:** 030, 040
**Entrega:** OTel Collector/Jaeger/Prometheus/Alertmanager; propagação de trace, redaction, métricas, alertas e burn rate.
**Aceite:** traces ponta a ponta; alertas disparam/resolvem; nenhum PII/segredo; SLO observável.
**Evidência:** traces + dashboards + regras + teste de alerta.
**Herda:** PROD12-043/044.

#### PRD26-043 — Worker A/B, sinais reais e shutdown

**Prioridade:** P1 · **Tamanho:** G · **Dono:** Worker/DBA · **Depende:** 030, 040
**Entrega:** dois workers reais, SIGTERM, claims em voo, drain, teardown seguro, fencing e recuperação de crash.
**Aceite:** nenhum job perdido/duplicado; shutdown limpo dentro do budget; dependências não fechadas em uso.
**Evidência:** matriz de crash + sinais + logs.
**Herda:** PROD12-036/008–010.

### E5 — Release e decisão

#### PRD26-050 — CI remoto no candidato exato

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Release/CI · **Depende:** 011–012, 022, 033, 040–043
**Entrega:** push do candidato; execução de todos os lanes no CI remoto; artefatos vinculados ao SHA; branch protection e retenção.
**Aceite:** todos os lanes mandatórios `PASS` no mesmo SHA; nenhuma evidência local-only; logs/artefatos recuperáveis.
**Evidência:** URL do run + SHA + artefatos + checks.
**Herda:** AUD24-031/034; PROD12-050.

#### PRD26-051 — Supply chain: SBOM, scans, assinatura e imagens imutáveis

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Release/supply chain · **Depende:** 050
**Entrega:** imagens por digest, non-root, SBOM, scan de CVE/segredo, assinatura cosign e verificação; rollback disponível.
**Aceite:** imagens assinadas/verificadas; nenhum achado alto; SBOM anexado; digest exato no packet.
**Evidência:** SBOM + scans + assinatura + verificação + digest.
**Herda:** PROD12-028.

#### PRD26-052 — Release packet, scorecard e revisão independente

**Prioridade:** P0 · **Tamanho:** G · **Dono:** Lead + revisores · **Depende:** 050, 051
**Entrega:** packet de 29 seções, scorecard tipado, mapa de evidência e limitações; revisão independente de arquitetura, segurança, operação e web.
**Aceite:** packet completo e linkado; nenhum achado alto; risco residual explícito; revisão com contexto novo.
**Evidência:** packet + scorecard + pareceres.
**Herda:** PROD12-051/052.

#### PRD26-053 — Decisão humana, risco residual e canary readiness

**Prioridade:** P0 · **Tamanho:** M · **Dono:** Autoridade humana · **Depende:** 052
**Entrega:** dossiê de decisão; `GO`/`NO-GO` assinado para o SHA/digest exato; se `GO`, plano de canary/rollback com métricas de aborto — não executado neste contrato.
**Aceite:** decisão registrada; risco residual aceito; canary só com autoridade/janela/orçamento próprios; `NO-GO` mantém o ciclo.
**Evidência:** decisão assinada + dossiê + plano.
**Herda:** PROD12-053–056.

## 6. Herança AUD24/PROD12 — referência, não duplicação

| Faixa herdada | Conteúdo | Relação PRD26 |
|---|---|---|
| AUD24-001–003 | Baseline, B01, reconciliação | 001 reutiliza; 002 dá delta de aceite |
| AUD24-010–018 | Identidade e auditoria | 002/040 reutilizam; 040 dá delta de IdP real |
| AUD24-020–025 | Recuperação web | 002/022 reutilizam; 022 dá delta de AT |
| AUD24-030–034 | CONTRACT, candidato, toolchain, VPS, CI remoto | 010/050 reutilizam |
| AUD24-040–045 | Docs, contrato, tipos, cobertura, RAG, AT | 003/011/012/013/020/022 dão delta |
| PROD12-001–006 | Governança, baseline, perfil, budgets, inputs | 001/002/003 reutilizam |
| PROD12-007–014 | Logout, shutdown, limiter, CSRF | 043 reutiliza; sem delta de código |
| PROD12-015–026 | Candidato local, toolchain, tipos, cobertura, web | 002/010–013 reutilizam |
| PROD12-027–032 | Topologia, imagens, lab, PostgreSQL, Redis, S3/Qdrant | 030 herda integralmente |
| PROD12-033–040 | Provider, golden path, identidade, workers, arquivos hostis, RAG, evidência, casos | 020/021/031/040/041 herdam |
| PROD12-041–049 | Browser/AT, revisão, observabilidade, auditoria, restore, performance, chaos, soak, runbooks | 022/032/033/042 herdam |
| PROD12-050–053 | CI remoto, reviews, packet, decisão | 050–053 herdam |
| PROD12-054–056 | Canary, expansão, operação | Pós-G7; fora deste backlog |

## 7. Rastreabilidade AVAL24 → PRD26

| Dimensão AVAL24 | Nota | Contratos | Marco |
|---|---:|---|---|
| 1 Arquitetura/fronteiras | 87 | 001, 012 | M0/M2 |
| 2 Contratos de API | 84 | 012 | M2 |
| 3 Autenticação/sessão | 80 | 002, 040 | M1/M5 |
| 4 Autorização/tenant | 85 | 040 | M5 |
| 5 Entrada/abuso | 76 | 040 | M5 |
| 6 Auditoria/honestidade | 80 | 002, 042 | M1/M5 |
| 7 Persistência/integridade | 86 | 030, 032 | M4 |
| 8 Ingestão/documentos | 86 | 031 | M4 |
| 9 Worker/concorrência | 89 | 031, 043 | M4/M5 |
| 10 Providers/resiliência | 84 | 041 | M5 |
| 11 Retrieval/proveniência | 86 | 020, 021 | M3 |
| 12 IA/RAG | 46 | 020, 021 | M3 |
| 13 Frontend/UX | 84 | 003, 022 | M1/M3 |
| 14 FE ↔ API | 82 | 012 | M2 |
| 15 Acessibilidade | 75 | 022 | M3 |
| 16 Testes/regressão | 89 | 002, 011, 013 | M1/M2 |
| 17 Cobertura/denominadores | 77 | 013 | M2 |
| 18 Tipagem | 75 | 011 | M2 |
| 19 Lint/higiene | 90 | 010 | M2 |
| 20 Build frontend | 89 | 010 | M2 |
| 21 CI/supply chain | 74 | 050, 051 | M6 |
| 22 Documentação | 79 | 003 | M1 |
| 23 Reprodutibilidade | 76 | 010 | M2 |
| 24 Observabilidade/operação | 74 | 042 | M5 |
| 25 Backup/restore/DR | 55 | 032 | M4 |
| 26 Prontidão de produção | 40 | 050–053 | M6/M7 |

## 8. Não escopo

- Novas features de produto, reescrita de módulos, troca de framework ou provider sem decisão.
- Alterar IDs, aceites ou status de AUD07/AUD15/AUD24/PROD12.
- Simular store/IdP/provider/browser com fixture e chamar de evidência externa.
- Aplicar DDL real, publicar imagem, assinar release ou fazer deploy sem autoridade.
- Fechar acessibilidade, RAG clínico ou SLO por documento.
- Usar média de notas, documento ou checklist como substituto de gate.

## 9. Adoção, status e primeira onda

- Este backlog permanece `PROPOSTO`. Adoção no [controlador](<../.agent/backlog.json>) exige pedido humano explícito (PRD26-D1); a partir daí, o controlador é a única fonte de status/aceite.
- Até a adoção, nenhum item pode ser declarado `DONE` por este documento.
- **Primeira onda recomendada:** 001 → 002 → 003; em paralelo, 010/011/012; depois 020/022 e 030.
- **Não iniciar** 030–043 sem PRD26-D4; não iniciar 050–053 sem 040–043; não iniciar 053 sem 052.
- **Ordem de segurança:** primeiro aceite e docs; depois engenharia; depois RAG/AT; depois dados; depois identidade/provider/operação; por fim release/decisão.

## 10. Contagem final

| Status | Quantidade |
|---|---:|
| Contratos PRD26 | 22 |
| P0 | 12 |
| P1 | 9 |
| P2 | 1 |
| Herdados AUD24 (referência) | 29 |
| Herdados PROD12 (referência) | 56 |
| Itens AUD07/AUD15 preservados | 46 + 24 |

**Nota:** a contagem é de especificação, não de execução. O controlador permanece a fonte de verdade após a adoção.

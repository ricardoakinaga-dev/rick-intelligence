# Backlog executivo — RICK Intelligence State of the Art / AAA

Prioridade: `P0` bloqueia promoção, `P1` é necessário para release AAA, `P2`
melhora contínua. Estado `IN_PROGRESS`, `READY`, `BLOCKED` ou `DONE` sempre
precisa de evidência no campo correspondente; nunca significa apenas intenção.

## Fundação e controle

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-001 | P0 | Reconciliar state/backlog/planos com o worktree atual | — | Lead / `.agent/**` | state revision, evento append-only, histórico preservado | DONE |
| SA-002 | P0 | Fechar regressão de identidade root↔legacy e rodar matriz Phase 1.4–1.6 | SA-001 | Lead / knowledge + scripts | differential, api15, api16, security, OpenAPI, preservation | DONE |
| SA-003 | P0 | Fixar Quality Bar v1 e fingerprint da execução | SA-001 | Lead / `.gauntlet-state-of-art/**` | bar imutável, fingerprint diagnóstico, round ledger | DONE |
| SA-004 | P0 | Revisar contratos de tenant/workspace/collection e IDs | SA-002 | Lead + Security | contrato serializável, paridade e negativos | DONE — contrato local, ACL, busca e negativos verificados; identidade externa ainda pendente em SA-021 |

## Spine de produção

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-010 | P0 | Persistência canônica de documentos, jobs, sessões e auditoria | SA-004 | Domain builder / migrations + packages | migration up/down, constraints, isolation tests | IN_PROGRESS — SQLite knowledge/vector/audit/job journal locais; Postgres/queue/object externo pendentes |
| SA-011 | P0 | Object storage privado com checksum, retention e presigned policy | SA-010 | Platform builder / adapters | upload/download autorizado, path traversal negative, cleanup | IN_PROGRESS — filesystem local com checksum/atomicidade/reopen verificado; S3-compatible/presigned/retention externo e wiring pendentes |
| SA-012 | P0 | Worker durável com fila, backpressure, retry finito e dead-letter | SA-010 | Worker builder / apps/worker | restart/recovery, cancellation, idempotency, queue bounds | IN_PROGRESS — SQLite queue local com lease/token/retry/dead-letter verificada; broker distribuído e multi-instância pendentes |
| SA-013 | P0 | Adapters reais Qdrant/Redis lease/provider sob contratos atuais | SA-010 | Platform builder / packages | disposable integration + degraded health | IN_PROGRESS — adapters HTTP/Redis herméticos verificados (9/36); live endpoint/health/wiring pendentes |
| SA-014 | P0 | Provider resilience: timeout, circuit breaker, budgets, redaction | SA-013 | Provider builder | fixture HTTP + failure matrix + metrics | IN_PROGRESS — wrapper local com budgets/circuit breaker/redaction e 47 testes de providers; telemetry/live policy pendentes |
| SA-015 | P0 | Readiness/liveness com required/optional dependencies reais | SA-012, SA-013 | Ops builder / apps/api | safe JSON, dependency down/up, no secrets | IN_PROGRESS — readiness inclui vector store e estados locais; dependências live/down-up pendentes |
| SA-016 | P1 | Observabilidade estruturada, trace/correlation, SLO e alertas | SA-012 | Ops builder | logs redacted, metrics, trace sampling, alert fixtures | IN_PROGRESS — API local compõe métricas bounded, request/correlation headers e SLO em `/api/v1/admin/metrics`; primitives de evento/trace existem; exporter/collector, stream de worker, agregação e alert delivery pendentes |

## API e segurança

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-020 | P0 | Completar API lifecycle v1 e OpenAPI root como fonte única | SA-004 | API integrator | contract snapshot, negative matrix, compatibility | IN_PROGRESS — 33 paths, search/admin e lifecycle local verificados; adapters live pendentes |
| SA-021 | P0 | Integrar identidade externa/OIDC sem fallback permissivo em produção | SA-010 | Security builder / identity | login/session/revocation/rate limits | READY |
| SA-022 | P0 | Provar isolamento tenant/workspace/collection em todas as rotas | SA-021 | Security builder | cross-scope negatives, no existence oracle | IN_PROGRESS — slice local propagates tenant through lifecycle/search and proves cross-tenant 404 opacity; external identity/storage and full route matrix pendentes |
| SA-023 | P1 | CSRF/CORS/headers/cookies e abuse limits do caller web | SA-021 | Security builder / API | browser-origin matrix, headers, rate limit | IN_PROGRESS — local limiter remains |
| SA-024 | P1 | Auditoria de ações sensíveis sem conteúdo bruto | SA-016, SA-022 | Security builder / API | schema + redaction + retention policy | DONE local — SQLite WAL, redaction/retention e admin bounded list; sink externo pendente |

## Web canônica e UX

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-030 | P0 | Criar `apps/web` root com Next, lockfile, env contract e build | SA-020 | Web builder / `apps/web/**` | lint/type/build, no legacy imports | DONE — initial slice |
| SA-031 | P0 | Definir design system RICK: tokens, type, color, spacing, motion, icons | SA-030 | Design builder / `apps/web/**` | token inventory, contrast checks, component states | DONE — initial token system |
| SA-032 | P0 | Shell autenticado, tenant switcher e navegação por permissão | SA-021, SA-031 | Web builder | E2E login/redirect/forbidden/logout | IN_PROGRESS — shell/roles/nav/search/admin atuais; tenant switcher e logout externo pendentes |
| SA-033 | P0 | Workspace de documentos: upload, jobs, reindex, delete, filters | SA-020, SA-032 | Web builder | E2E against root API, all states, no stale data | IN_PROGRESS — upload/catalog/delete/reindex/retry/cancel, filtros por coleção, busca local e paginação incremental verificados; runtime externo pendente |
| SA-034 | P0 | Search/chat com evidence drawer, citations e confidence states | SA-022, SA-031 | Web builder | grounded/weak/no-evidence, copy/export safe | IN_PROGRESS — busca root, histórico, evidence e estados approved/weak/no-evidence/retrieval-failed locais; eval/Professor/live thresholds pendentes |
| SA-035 | P1 | Dashboard, audit e admin operacionais | SA-016, SA-032 | Web builder | permission matrix + pagination + empty/error | IN_PROGRESS — health/audit/admin local; dashboard, paginação e ops reais pendentes |
| SA-036 | P0 | Accessibility, responsive and visual QA | SA-031–SA-035 | Design QA / read-only critic | 375/768/1440 render, WCAG AA, score ≥95 | IN_PROGRESS — Cycle4 web escopado: 108/108 visuais, 219/225 funcionais + 6 skips planejados, axe/reduced-motion local e críticos independentes 97/100 e 95,52/100; produto completo e performance de campo pendentes |

## Inteligência e qualidade de resposta

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-040 | P0 | Corpus/eval harness aprovado e versionado sem dados sensíveis | SA-004 | Eval builder | fixtures licensed, golden queries, reproducibility | IN_PROGRESS — fixture/harness offline e sem dados sensíveis verificados; corpus aprovado/licenciamento pendente |
| SA-041 | P0 | Retrieval evaluation: recall, hit@k, ACL leakage, freshness, latency | SA-040, SA-013 | Retrieval builder | thresholds + regression artifacts | IN_PROGRESS — hit/recall/ACL/provenance/latency fixture verificado; live/freshness/thresholds pendentes |
| SA-042 | P0 | Professor grounded generation com evidence pack e citation coverage | SA-041, SA-014 | Professor builder | unsupported-claim negatives, provider failures | READY |
| SA-043 | P1 | Feedback/review queue e melhoria segura por sinal humano | SA-016, SA-042 | Product builder | audit trail, no silent prompt mutation | READY |
| SA-044 | P1 | OCR/table/page provenance para formatos prioritários | SA-011, SA-040 | Ingestion builder | parser fixtures, page/source accuracy | READY |

## Release, operações e promoção

| ID | Pri | Item | Dependências | Ownership | Aceite/evidência | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| SA-050 | P0 | Compose/dev environment root com health and seeded local fixtures | SA-010–SA-015 | Ops builder | `make up`, smoke, teardown, no secret defaults | IN_PROGRESS — compose reference/YAML parse/static gate; Docker startup/smoke NOT_RUN |
| SA-051 | P0 | CI gates: lint/type/test/security/contract/eval/visual artifacts | SA-002, SA-036 | CI builder | workflow dry run + artifact retention | READY |
| SA-052 | P0 | Backup/restore, migrations, disaster/restart drills | SA-010–SA-016 | Ops builder | restore evidence and RTO/RPO record | IN_PROGRESS — migration/check/runbook manifests locais; backup/restore/RTO/RPO execution NOT_RUN |
| SA-053 | P1 | Load/performance/soak and cost budgets | SA-012, SA-041 | Perf builder | p50/p95/p99, concurrency, memory, budget | READY |
| SA-054 | P0 | Canary/rollback and migration map from preserved children | all P0 | Lead / release | dual evidence, switch, rollback rehearsal | READY |
| SA-055 | P0 | Fresh Integration Reviewer and Final Critic | all required | Gauntlet critics | sealed packets, mutation sentinel, APPROVE | READY |

O backlog é deliberadamente maior que uma única rodada. A execução atual
começa em `SA-001`–`SA-003`; cada rodada seguinte deve selecionar o maior gap
material, registrar a hipótese e atualizar os artefatos de evidência.

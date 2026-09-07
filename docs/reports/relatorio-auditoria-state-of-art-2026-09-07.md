# Relatório de auditoria — RICK Intelligence State of Art

**Data da observação:** 2026-09-07
**Escopo:** `docs/`, aplicações root, packages, worker, infraestrutura, testes e artefatos de verificação.
**Classificação:** auditoria atual, local/hermética, sem promoção de produção.
**Revisão observada:** `HEAD 3c78513`; checkout compartilhado dirty.

Este relatório preserva a diferença entre o que foi observado no código e o que
continua apenas planejado, `NOT_RUN`, `READY` ou dependente de serviços externos.
Ele complementa os documentos anteriores em
[`docs/plans/state-of-art-executive.md`](../plans/state-of-art-executive.md),
[`docs/plans/state-of-art-roadmap.md`](../plans/state-of-art-roadmap.md) e
[`docs/plans/state-of-art-backlog.md`](../plans/state-of-art-backlog.md).

## 1. Método e evidência

Foram lidos todos os 114 arquivos de `docs`, totalizando 7.997 linhas e
450.702 bytes. A auditoria comparou documentação, código alcançável, contratos,
testes, artefatos gerados e limites explícitos de produção.

Validações atuais executadas:

| Verificação | Resultado atual |
| --- | --- |
| `make api14-full` | PASS — 477 testes |
| `make api15-full` | FAIL — 450 testes passam; benchmark falha por `tenant_id` ausente |
| `make api16-full` | PASS — 455 testes |
| `make api-security` | PASS — 25 testes |
| `make api-contract` | PASS — OpenAPI root validado |
| `make storage-test` | PASS — 9 testes |
| `make eval-retrieval` | PASS — fixture offline; dependências live `NOT_RUN` |
| `make ops-static` | PASS — apenas validação estática |
| `make web-validate` | PASS — 219/225; 6 skips planejados |
| `make api15-verify` | FAIL — inclui o benchmark Phase 1.5 atual |
| `make api16-verify` | FAIL — inclui o `api15-full` reprovado |
| `docs/ci/check_control_plane.py` | PASS estrutural; checkout dirty e sem `release-evidence.json` |

Os artefatos sanitizados atuais registram a mesma conclusão em
[`phase-1.5-verification.json`](../progress/phase-1.5-verification.json) e
[`phase-1.6-verification.json`](../progress/phase-1.6-verification.json).

## 2. Veredito executivo

| Dimensão | Nota |
| --- | ---: |
| Construção local e hermética | **81/100** |
| Prontidão para produção | **55/100** |

O RICK Intelligence já possui uma base de produto real: API root, contratos,
identidade local, ACL multi-tenant, ingestão, retrieval, Professor, auditoria,
worker local e aplicação web. A lacuna dominante não é ausência de código de
domínio; é a promoção desse caminho local para uma topologia durável,
multi-instância, observável e operável.

## 3. O que já está construído

- API FastAPI root com rotas explícitas, default-deny, contratos de erro,
  readiness/liveness, streaming e compatibilidade OpenAI.
- Pacotes canônicos de contratos, autorização, identidade, knowledge, ingestion,
  retrieval, providers, locking, Professor, observabilidade e storage.
- `SQLiteKnowledgeStore`, vector store local, audit sink SQLite e journal local
  com WAL, limites, tombstones e recuperação bounded.
- Upload, parsing, chunking, embeddings, indexação, reindex, retry,
  cancelamento, delete e estados seguros de job.
- Retrieval híbrido dense/sparse, RRF, reranking, filtros ACL, provenance,
  citações e limites de contexto.
- Professor com evidence gate, confidence, validação de citações, lease,
  budgets, redaction e provider resilience.
- Adapters Qdrant e Redis hermeticamente testados, sem conexão implícita no
  import; integração live ainda separada.
- Web Next/React com login, shell, documentos, busca, chat, admin, auditoria,
  estados de erro/empty/loading, foco, reduced motion, axe local e E2E.
- Compose de referência, migrations iniciais, Makefile, workflows e runbooks
  estáticos.

## 4. O que ainda não está pronto

- Postgres como store canônico de produção.
- Object storage privado S3-compatible com retenção e políticas presigned.
- Broker/fila distribuída, worker multi-instância e recovery em topologia real.
- Wiring live de Qdrant, Redis lease e provider externo.
- OIDC/identidade externa e rate limiting distribuído.
- Corpus aprovado/licenciado, thresholds de qualidade e avaliação live.
- Backup/restore, RTO/RPO, carga, soak, custo, canary e rollback executados.
- Exporter/collector de telemetria, alert delivery e SLO distribuído.
- `release-evidence.json` fresco e checkout limpo para promoção.

## 5. Notas por item analisado

| Item | Nota | Avaliação atual |
| --- | ---: | --- |
| Documentação e rastreabilidade | 86 | Muito abrangente e honesta sobre `NOT_RUN`; há artefatos históricos e pequenas divergências de frescor. |
| Arquitetura e boundaries | 92 | Root canônico, DI explícita, route registry e preservação dos children. |
| API, contratos e OpenAPI | 91 | 34 paths root e matriz API atual funcional; promoção externa ainda não composta. |
| Identidade, RBAC e multi-tenant | 89 | Sessões, permissões e negativos cross-tenant locais; OIDC externo pendente. |
| Knowledge e persistência | 78 | SQLite transacional verificado; Postgres e durabilidade multi-instância ausentes. |
| Ingestão e lifecycle | 82 | Fluxo público completo localmente; fila e staging ainda locais. |
| Retrieval/RAG | 84 | Pipeline híbrido, ACL e evidence construídos; corpus/live/freshness pendentes. |
| Professor/provider/grounding | 78 | Guardrails e orquestração fortes localmente; provider real e benchmark íntegro pendentes. |
| Locking e concorrência | 82 | Ownership e renew/release implementados; Redis live e wiring root pendentes. |
| Worker e fila durável | 72 | Primitivas locais existem; broker distribuído e integração da aplicação não. |
| Auditoria e observabilidade | 79 | Redaction, métricas e audit bounded; sem collector/agregação. |
| Segurança e privacidade | 86 | Default-deny, CSRF/CORS, limites e fail-closed de produção; OIDC/Argon2/rate distribuído pendentes. |
| Web, UX e acessibilidade | 90 | Lint/type/build, 219/225 E2E e 108/108 visuais; aprovação limitada à web local. |
| Testes e regressão | 84 | Matriz ampla e atual; Phase 1.5 falha e há warnings relevantes. |
| Operações e deployment | 55 | Compose/migration/runbooks são referência; runtime, restore e deploy não executados. |
| Performance e escala | 62 | Métricas locais abaixo do limite; sem carga, soak, p99, custo ou campo. |

## 6. Gaps materiais

### GAP-AAA-001 — Benchmark Phase 1.5 quebrado

**Prioridade:** P0 / correctness.
**Evidência:** [`scripts/phase15/benchmark.py:59`](../../scripts/phase15/benchmark.py:59) cria um contexto sem `tenant_id`, enquanto o contrato de `RetrievalContext` exige esse campo.
**Impacto:** `api15-full`, `api15-verify` e `api16-verify` não podem ser promovidos.
**Aceite de fechamento:** benchmark passa com contexto tenant-scoped e a matriz Phase 1.5 é reproduzida sem relaxar o contrato.

### GAP-AAA-002 — Spine de produção incompleto

**Prioridade:** P0 / availability e data integrity.
**Evidência:** o factory root exige componentes externos em produção, mas o
  ambiente atual fornece apenas stores locais; ver
  [`apps/api/src/app.py:342`](../../apps/api/src/app.py:342).
**Impacto:** não há disponibilidade durável, multi-instância ou recuperação de
  produção comprovada.
**Aceite de fechamento:** Postgres, object storage, queue/worker, Qdrant, Redis
  e provider live passam integração descartável, restart, failure e readiness.

### GAP-AAA-003 — Identidade externa não integrada

**Prioridade:** P0 / security.
**Impacto:** a identidade local é adequada para desenvolvimento, mas não atende
  federação, revogação operacional e ciclo de vida corporativo de produção.
**Aceite de fechamento:** OIDC, mapeamento de tenant/roles, logout/revogação,
  rate limits e negativos cross-tenant passam contra um IdP de teste autorizado.

### GAP-AAA-004 — Qualidade de inteligência ainda sem corpus de produção

**Prioridade:** P0 / accuracy.
**Impacto:** a fixture offline comprova plumbing, não qualidade semântica ou
  freshness em corpus aprovado.
**Aceite de fechamento:** corpus licenciado, golden set, thresholds,
  unsupported-claim negatives, leakage zero e regressão live versionada.

### GAP-AAA-005 — Release sem evidência final

**Prioridade:** P0 / release.
**Impacto:** checkout dirty, `release-evidence.json` ausente e gates live
  `NOT_RUN`; não existe base honesta para promoção.
**Aceite de fechamento:** checkout candidato limpo, manifesto/fingerprint,
  backup/restore, canary/rollback, critic independente e gate final PASS.

### GAP-AAA-006 — Frescor da evidência web

**Prioridade:** P1 / traceability.
**Impacto:** o documento canônico registra LCP máximo de 620 ms, enquanto o
  resumo atual local observou 920 ms; ambos passam o limite, mas a fonte precisa
  ser reconciliada.
**Aceite de fechamento:** documentação e artefato apontam para o mesmo build,
  janela e agregação atuais.

## 7. Próxima ação executável

Corrigir `GAP-AAA-001`, executar novamente `make api15-verify` e
`make api16-verify`, atualizar os artefatos de verificação e só então iniciar o
spine externo. Não promover qualquer componente live antes desse fechamento.

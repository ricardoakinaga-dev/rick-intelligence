# Relatório de Auditoria Geral — RICK Intelligence

**Data:** 27/09/2026. **Tipo:** auditoria técnica independente (inspeção estática de código + documentação), sem execução de deploy distribuído nem selo de promoção.

**Nota geral:** **79/100** (média simples de 26 itens). Referência anterior: 72/100 em 24/09/2026, 70/100 em 17/09/2026.

**Parecer técnico:** a implementação evoluiu de forma consistente desde a auditoria de 24/09. A maioria dos bloqueadores funcionais e de segurança documentados (A24-01, A24-02, A24-03, A24-05, A24-07, A24-08) foi **corrigida no código com regressões dirigidas**. O que impede uma nota mais alta já não é a qualidade do código local, mas a ausência persistente de **evidência operacional distribuída** (runtime real com PostgreSQL/Redis/Qdrant/S3/provider trabalhando juntos) e de **autoridade externa** (review independente, selo e Go/No-Go humano). Não há evidência suficiente para aprovar produção nem para atribuir selo AAA/TRIPLE_AAA; a classificação honesta continua `STATE_OF_ART_CANDIDATE`.

---

## 1. Escopo e método

- **Objeto:** checkout local `/home/ricardo/rick-intelligence`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, **incluindo 121 arquivos modificados e 56 não rastreados** (trabalho Q24 em andamento até 25/09). A nota descreve o estado atual do workspace, não exclusivamente esse commit.
- **Método:** inspeção estática de código e documentação, triangulada por quatro auditores independentes (backend/kernel, domínio RAG/packages, frontend, infraestrutura/CI/segurança) mais a leitura direta do auditor-consolidador. Não foram executados testes longos nem iniciado Docker/deploy.
- **Confiança:** alta nos achados estáticos (arquivo:linha verificados e cruzados por dois ou mais auditores); moderada/baixa na extrapolação operacional distribuída, que **não foi executada** e permanece `BLOCKED_EXTERNAL`.
- **Regra de nota:** as 26 áreas da metodologia histórica, com dimensões ponderadas — implementação vs. escopo (40), correção/tratamento de falhas (25), qualidade de testes/evidência (20), integração/comprovação operacional (15). Média simples **2.049 / 26 = 78,8 ≈ 79**.

---

## 2. Notas por item (0–100)

| Nº | Item analisado | 24/09 | 27/09 | Fundamentação e principal limite |
|---:|---|---:|---:|---|
| 1 | Arquitetura e separação de responsabilidades | 85 | **86** | Fronteiras `apps → packages → contracts` verificáveis; composição raiz explícita (`deployment_composition`). Persistem três legados paralelos e caminhos de compatibilidade. |
| 2 | Documentação e aderência ao estado atual | 64 | **72** | Documentação excepcionalmente honesta (`NOT_RUN`/`BLOCKED_EXTERNAL` explícitos, nunca fabricados). Ainda há drift toolchain (Qdrant 1.7.4 no `toolchain.json` vs 1.12.5 no compose). |
| 3 | Identidade e sessões | 80 | **87** | Snapshot autoritativo imutável, PBKDF2-100k, OIDC fail-closed, revogação por versão de senha/role. Fluxo completo sobre PostgreSQL real não re-exercitado nesta rodada. |
| 4 | Autorização e isolamento | 83 | **86** | Engine canônico narrowing-only (nunca alarga escopo); revalidação ao vivo por interseção; filtragem pós-leitura. Matriz integrada multi-store ainda sem prova operacional. |
| 5 | Kernel HTTP e controles defensivos | 76 | **88** | Duplo limite de corpo, envelope sem vazamento, rate-limit fail-closed, gate de produção rígido, semáforo de streaming. **A24-01 resolvido** (dependências atualizadas). |
| 6 | Contratos e compatibilidade | 82 | **85** | Contratos de chat/metadados/`tool_calls` fortalecidos; compat OpenAI com `constant_time_compare`. Compromisso com consumidores externos reais persiste. |
| 7 | Knowledge: documentos, versões e proveniência | 81 | **88** | Proveniência content-addressed, lineage completo, re-ingest idempotente. `metadata` ainda é `dict` genérico; `source_type` por sufixo de arquivo. |
| 8 | Ingestão e reindexação | 85 | **90** | Batching `MAX_EMBEDDING_BATCH=256` com validação total pré-escrita; cancelamento cooperativo; parser isolado (spawn + kill de grupo). Faltou execução com embeddings reais. |
| 9 | Retrieval e busca híbrida | 74 | **92** | **A24-05 resolvido**: `search_hybrid` HTTP dense+sparse com escopo idêntico, degradação explícita, RRF + revalidação ACL. Ativação de índice (alias) é passo manual separado. |
| 10 | Evidence: fontes e citações | 84 | **89** | ID content-addressed no servidor, re-resolução canônica no PostgreSQL, bundle imutável. Suporte semântico por claim permanece léxico (não-entailment). |
| 11 | Decision: responder, abster e escalar | 45 | **78** | **A24-02 resolvido**: classificação real via `NonClinicalRequestPolicy` v1; permitidas alcançam ANSWER, desconhecidas ESCALATE. Escopo ainda limitado a QA não-clínico até D04. |
| 12 | Professor e geração fundamentada | 80 | **89** | Rejeição de resposta sem `[cite:]` obrigatória; lease com heartbeat interrompe geração; budgets anti-loop. `approved_confidence=0.50` é heurística não calibrada. |
| 13 | Integração com providers | 86 | **86** | `ResilientProvider` com budgets, circuit breaker, streaming validado. Sem chamada a modelo real nesta auditoria; tool-calls orçadas mas não executadas no domínio. |
| 14 | Avaliação da qualidade RAG | 55 | **80** | **A24-04 resolvido** (contrato viável v2 com 22 testes). Campanha representativa permanece `NOT_RUN`/`BLOCKED` sem corpus/provider autorizados. |
| 15 | Chat, histórico e apresentação das evidências | 82 | **82** | SSE único contrato; idempotência canônica; metadados allowlist; replay revalidado. Geração útil ponta-a-ponta com modelo real não comprovada. |
| 16 | Documentos, busca e ingestão pela interface | 64 | **92** | **A24-03 resolvido** (coleção unificada + retry binário byte-a-byte). Cap de polling (~9,6 s) e granularidade do `forbidden` admin persistem (médio). |
| 17 | Administração, auditoria e casos | 73 | **85** | Outbox atômico + advisory locks; **A24-06 endereçado** (consumidor `PostgresAdminAuditReconciler` com SKIP LOCKED/dead-letter). Reconciliação ponta-a-ponta em runtime completo não provada. |
| 18 | Containers e composição do ambiente | 68 | **78** | Hardening forte (no-new-privileges, cap_drop ALL, read_only), readiness encadeada, redes `internal`. Root credential no bootstrap MinIO e jaeger in-memory são débitos. |
| 19 | Jobs, PostgreSQL e migrações | 68 | **90** | SKIP LOCKED + optimistic locking + fencing owner-bound + outbox transacional. **A24-07 resolvido** (checksum compatibility). Migração real em banco distribuído não re-exercitada. |
| 20 | Worker e ciclo de vida | 73 | **88** | Shutdown cooperativo com deadline, prevenção de late-ack, poison-claim non-retryable, oito crash points. Signals dependem do launcher/supervisor invocar shutdown. |
| 21 | Redis e coordenação distribuída | 71 | **92** | Fencing owner-safe via Lua (`SET NX PX`, renew/release comparam owner); circuit breaker; release at-most-once. Heartbeat sem compensação de clock-skew. |
| 22 | Storage e inicialização persistente | 66 | **85** | `S3CompatibleObjectStore` com endpoint validado, `require_https`, credenciais assinadas; reidratação de índice validada. Health bodyless não verifica escrita real. |
| 23 | Observabilidade e SLO | 67 | **84** | **A24-08 resolvido** (`timeout=None` agora limitado a 250 ms no pool fixo). Exportação/coletor/alerta reais continuam `NOT_RUN`. |
| 24 | Recuperação, capacidade e tolerância a falhas | 45 | **55** | Runbook robusto (RPO≤15 min/RTO≤60 min, manifest com SHA-256), mas `RUNBOOK READY / NOT_RUN`; **nenhum RPO/RTO medido**. |
| 25 | CI e promoção de release | 60 | **72** | Workflow com 8+ lanes, envelope selado Ed25519, release fail-closed. **A24-09 persiste** (3 gates finais sem executor conectado). Actions não-pinadas em alguns workflows. |
| 26 | Qualidade global dos testes | 80 | **86** | 95 arquivos de teste Python + 15 specs; regressões dirigidas a cada achado; testes Qdrant/PostgreSQL reais descartáveis. Dependência de mocks para provider/corpus. |

> As notas de interface (16) avaliam implementação e comportamento no teste delimitado, não uma aprovação geral de acessibilidade. As áreas 18, 24 e 25 refletem fortemente a ausência de ambiente externo (Docker/DAEMON e serviços), não apenas a qualidade do código.

---

## 3. Estado dos achados A24 (da auditoria de 24/09)

| Achado | Estado atual | Evidência |
|---|---|---|
| **A24-01** dependências com CVE de DoS (multipart 0.0.9, starlette 0.36.3) | ✅ **RESOLVIDO** | `apps/api/pyproject.toml` pina `python-multipart==0.0.32`, `starlette==1.7.0`, `fastapi==0.141.1`, `uvicorn==0.54.0`, `anyio==4.15.0` — todas pós-correção dos CVEs conhecidos. |
| **A24-02** decision fixava risco UNKNOWN → escalava tudo | ✅ **RESOLVIDO** | `packages/decision/src/rick_decision/request_policy.py` introduz `NonClinicalRequestPolicy` v1; `professor_backend.py:524` classifica de verdade; UNKNOWN continua ESCALATE (conservador). |
| **A24-03** upload enviava coleção vazia + retry binário via `.text()` | ✅ **RESOLVIDO** | `documents/page.tsx:167-168` lê `uploadCollectionValue`; `api.ts:205-212` envia `File` blob diretamente; testes byte-a-byte em PDF binário. |
| **A24-04** meta RAG matematicamente inviável | ✅ **RESOLVIDO** | pack sintético v2 com contrato viável; `make eval-retrieval-pack` passa (22 testes). |
| **A24-05** busca híbrida ausente no caminho HTTP | ✅ **RESOLVIDO** | `backends.py:111-124` chama `search_hybrid`; `qdrant.py:1028-1112` pernas dense+sparse com escopo idêntico; testes `test_http_hybrid.py`/`_runtime.py`. |
| **A24-06** auditoria pendente sem reconciliação | 🟡 **ENDEREÇADO (parcial)** | `apps/worker/admin_audit_outbox.py` (consumidor com SKIP LOCKED/dead-letter/backoff) + outbox atômico. Falta prova ponta-a-ponta em runtime completo. |
| **A24-07** migração 0005 sem upgrade p/ histórico | ✅ **RESOLVIDO** | `migrate.py` com pares checksum histórico/atual, `verify_jobs_rewrite`, repair 0004 com ledger; documentado e testado. |
| **A24-08** telemetria `timeout=None` síncrono ilimitado | ✅ **RESOLVIDO** | `events.py:148-153` mapeia `timeout=None` para 250 ms no pool fixo (2 workers, fila 1024); teste dedicado de sink bloqueado. |
| **A24-09** promoção com etapas sem executor conectado | 🔴 **PERSISTE** | `triple_aaa_verify.py:513,541,544` — `lab-readiness`, `independent-reviews`, `production-runtime` com `command=None` + `external=True`. |
| **A24-10** operação distribuída sem validação | 🟡 **PERSISTE (estrutural)** | performance/chaos/soak são pass-through de harness externo; sem daemon/credenciais aprovados. |

**Resumo:** 7 dos 10 achados resolvidos, 1 endereçado parcialmente (A24-06), 2 persistentes por natureza estrutural/externa (A24-09, A24-10).

---

## 4. Achados novos e residuais (não-bloqueantes)

| Prioridade | Achado | Localização |
|---|---|---|
| Médio | **Cap de polling de ingestão (~9,6 s):** uploads longos reportam "ainda em andamento" mesmo em sucesso (80 polls × 120 ms). | `documents/page.tsx:139,155` |
| Médio | **Granularidade grosseira do `forbidden` admin:** um 403 em health OU audit esconde o outro recurso. | `admin/page.tsx:65-69,102-104` |
| Médio | **Root credential compartilhada no bootstrap do MinIO** (init script usa credencial de root). | `docker-compose.dev.yml:126-127` vs `150-151` |
| Médio | **Drift de versão toolchain:** `toolchain.json` cita Qdrant 1.7.4/Redis 7.0.15; compose usa 1.12.5/7.4. | `toolchain.json` vs `docker-compose.dev.yml` |
| Médio | **`retrieval_mode` não explícito** na composição (depende do default `auto`). | `external_composition.py:424` |
| Baixo | Duplicação de `ConfirmDialog` (`ui.tsx` vs `admin-management.tsx`) e de `errorMessage` (4×). | apps/web |
| Baixo | `provider_confidence_signal` hardcoded 1.0 ("disponibilidade"), não métrica real. | `professor_backend.py:376-380` |
| Baixo | `source_type` derivado por sufixo de arquivo, não magic bytes. | `pipeline.py:749` |
| Baixo | CSRF token vazio por padrão em local/test; produção multi-domínio deve ter nonce por sessão. | `core/csrf.py:96` |
| Baixo | Actions GitHub não-pinadas em `phase-1.x.yml` (inconsistente com `quality.yml`). | `.github/workflows/` |

---

## 5. O que a nota NÃO captura (leitura honesta)

A nota **79/100** mede a qualidade do código e da evidência local. Ela **não** é um score de promoção. Há duas escalas distintas no projeto e é importante não confundi-las:

1. **Nota técnica de auditoria** (este relatório e o de 24/09): avalia a solidez do código, dos testes e da documentação verificáveis no checkout. O programa é maduro aqui (79).
2. **Score de promoção AAA** (`rick-intelligence-triple-aaa-final-promotion.md`): exige runtime distribuído real, review independente, selo e Go/No-Go humano — meta `≥96/100`. Este continua em **`NO-GO`** com a maioria das dimensões `BLOCKED_EXTERNAL`/`NOT_RUN`, porque **o ambiente externo (Docker daemon aprovado, PostgreSQL/Redis/Qdrant/S3/provider reais, autoridade humana) não está disponível neste workspace**.

O que separa 79 de 96 não é mais "corrigir bugs", e sim **obter e conectar evidência operacional real + autoridade externa** — exatamente o que A24-09 e A24-10 registram.

---

## 6. Ordem de trabalho proposta

| Ordem | Entrega | Critério |
|---:|---|---|
| 1 | Fechar A24-09 | Conectar produtores/consumidores reais para `lab-readiness`, `independent-reviews` e `production-runtime` (ou assumir explicitamente que são decisões humanas externas e documentar o processo). |
| 2 | Fechar A24-10 e A24-06 (ponta-a-ponta) | Executar upload → fila → worker → índice → resposta → citações → histórico em ambiente descartável aprovado, incluindo reconciliação do outbox administrativo sob falha/restart. |
| 3 | Medir operação real | RPO/RTO, carga (1/10/50/100), caos e soak com harness aprovado. |
| 4 | D04 — política de domínio clínico | substituir o allowlist não-clínico por uma política de domínio revisada, sem liberar respostas indevidamente. |
| 5 | Hardening residual | nonce CSRF por sessão, credencial scoped no bootstrap MinIO, pin de ações GitHub, eliminar duplicação de diálogos. |

---

## 7. Entrega e preservação

Este relatório é **somente leitura**: nenhum arquivo de produto, migração, controle canônico (`.agent/`, `.gauntlet/`) ou evidência histórica foi alterado. Nenhum teste foi executado, nenhum provider chamado, nenhum commit/push/deploy realizado. O único artefato adicionado é este documento.

**Classificação honesta:** `STATE_OF_ART_CANDIDATE`. **Promoção:** `NO-GO` (sem evidência operacional e autoridade externa).

# AUD24 — pacote de execução externa M5–M7

**Data:** 24/10/2026. **Estado:** `PREPARADO / BLOCKED_EXTERNAL`. **Não executa nada.**
Este pacote fecha a preparação da onda externa do goal AUD24; a execução exige autoridade, credenciais, ambientes e budgets que não existem nesta sessão.

## 1. Regra de autoridade

Nenhum comando abaixo pode ser executado por inferência. Cada onda exige a decisão correspondente registrada pelo owner humano:

| ID | Decisão | Necessária para | Estado |
|---|---|---|---|
| D01 | Perfil de lançamento e topologia | M5/M6 | **AUSENTE** |
| D02 | PostgreSQL/Redis/Qdrant/S3 descartáveis e credenciais | M5 | **AUSENTE** |
| D03 | IdP/perfil de identidade de produção | M6 | **AUSENTE**; OIDC fora até broker (D3) |
| D04 | Provider, corpus, direitos, labels e thresholds | M6 | **AUSENTE** |
| D05 | RPO/RTO, backup/restore e SLO | M5/M6 | **AUSENTE** |
| D06 | Carga, chaos, soak e janela de aborto | M6 | **AUSENTE** |
| D07 | Revisão independente, risco residual e GO/NO-GO | M7 | **AUSENTE** |

Sem o ID correspondente: `BLOCKED_EXTERNAL`, nenhuma prova simulada é aceita.

## 2. M5 — dados e recuperação

| Fronteira | Comando/entrada | Evidência mínima | Owner proposto |
|---|---|---|---|
| PostgreSQL/migrations | `make postgres-runtime` com `RICK_TEST_DATABASE_DSN` descartável | checksums, constraints, queue/lease/version, crash/replay, DLQ | Plataforma/DBA |
| Redis/rate limit | `make redis-runtime` com `RICK_TEST_REDIS_URL` autenticado | namespace, failover/reconnect, limite compartilhado | Plataforma |
| Qdrant | `make object-qdrant-runtime` com endpoint descartável | ACL, alias/rebuild, delete/restore, consistência | Retrieval |
| Objeto S3 | `make object-qdrant-runtime` com bucket descartável | PUT/HEAD/GET/DELETE, checksum, retenção, credenciais | Plataforma |
| Ingestão E2E | `make golden-runtime` | upload→fila→parse→index→retrieve→delete/reindex | QA/runtime |
| Restore/DR | `make restore-runtime` / `make phase3-restore-runtime` | seed→backup→destroy→restore→verify, RPO/RTO | SRE |

**Critério de aborto:** qualquer leitura/escrita fora do namespace aprovado, checksum divergente, perda/duplicação de tenant ou restore que não reproduza contagens/ACL. Abortar, preservar logs e não promover.

## 3. M6 — identidade, provider e operação

| Fronteira | Comando/entrada | Evidência mínima | Owner proposto |
|---|---|---|---|
| IdP/tenant A/B | `make tenant-evidence-runtime` | login/logout/revogação/outage/multiaba, negativo cross-tenant | Identidade/segurança |
| Provider/RAG | `make golden-runtime` + pack aprovado | capability, streaming, cancel, citação, budget/custo | Domínio/QA |
| Observabilidade | `make observability-runtime` | traces, métricas, redaction, alertas, burn rate | SRE |
| Browser/API real | `make web-e2e` com API real | 375/768/1440, teclado, leitor de tela, offline/403/401 | QA/design |
| Performance | `make phase3-performance` | p50/p95/p99, throughput, erros, memória, fila, custo | SRE |
| Chaos | `make phase3-chaos` | crash, latência, partição, dependência lenta, retry storm | SRE |
| Soak | `make phase3-soak` | janela aprovada, vazamento, recuperação, limites | SRE |

**Budgets:** latência/erro/custo/RPO/RTO/duração **não são inventados aqui**. Precisam ser ratificados em D05/D06 antes da execução; sem budget, o resultado é descritivo e não um gate.

## 4. M7 — packet e decisão

| Etapa | Comando | Evidência |
|---|---|---|
| Candidato/packet | `make phase3-evidence`, `make release-evidence` | manifesto, digests, SBOM, scans, assinatura |
| Verificação | `make phase3-evidence-verify`, `make triple-aaa-verify` | 0/2/1 conforme o contrato fail-closed |
| Revisão | reviewers novos, read-only | achados, disposição, risco residual |
| Decisão | D07 | `GO`/`NO-GO` para o artefato exato |

**GO exige:** todos os gates mandatórios PASS no mesmo artefato, nenhum P1 aberto, packet íntegro e risco residual aceito. Caso contrário, `NO-GO`.

## 5. O que está bloqueado agora

| Obrigação | Bloqueio | Ação do owner |
|---|---|---|
| PostgreSQL/Redis/Qdrant/S3 | sem D02/credenciais/ambientes | provisionar descartáveis e autorizar |
| IdP | sem D03 | definir perfil (nativo Postgres ou broker) |
| Provider/RAG | sem D04/corpus/budget | aprovar conta, corpus, direitos e thresholds |
| Restore/RPO/RTO | sem D05 | ratificar budgets e janela |
| Perf/chaos/soak | sem D06 | aprovar carga, aborto e janela |
| Release | sem D07 | designar reviewer e autoridade |

## 6. Formato de evidência

Cada execução deve registrar: data UTC, ambiente, commit/fingerprint, configuração, comandos, exit codes, artefatos/hashes, autoridade usada e limitações. Nenhum resultado histórico é reapresentado como atual; nenhum `NOT_RUN` vira PASS.

## 7. Próximo passo

Levar D01–D07 ao owner humano e executar M5 primeiro (dados/restore), porque é a fronteira de maior risco e a que menos aceita substituto. Sem isso, o goal permanece `BLOCKED_EXTERNAL` para M5–M7, com M0–M4 tratados separadamente.

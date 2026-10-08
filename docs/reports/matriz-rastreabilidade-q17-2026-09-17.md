# Matriz de rastreabilidade Q17 — auditoria, scorecard, gates e casos

Data: 2026-09-17. Versão MT17-v1. Estado: **PROPOSED / CATÁLOGO PROPOSTO; NÃO É BACKLOG CANÔNICO NEM ACEITE DE PROMOÇÃO**.

Fontes: [auditoria](relatorio-auditoria-2026-09-17.md), [backlog BL17][BL], [quality bar congelado][QB], [prompt atual de 10/09][PR], [Makefile][MK]. Inspeção local sobre HEAD `b52f32c`, com árvore suja compartilhada; não constitui candidato selado. Nenhum serviço, CI remoto, provider ou reviewer foi acionado nesta entrega.

## Autoridade, nomenclatura e leitura

- Q17-01..26 são os itens da auditoria, não IDs de dimensões. Os vínculos abaixo são **propostos**, usando os critérios já associados no backlog; não são uma nova política de promoção.
- O JSON indicado pelo pedido contém **12 `criteria[].id`**, cada qual com `dimension`, `target`, `evidence_method`, `conditions` e `validity_notes`. **Não contém 26 IDs de scorecard nem lista formal de gates por dimensão.** Os 26 nomes exatos vêm da seção 57 do [prompt][PR] e de `PACKET_SCORECARD_DIMENSIONS` no [engine][PE]. Não se inventam IDs nem gates oficiais ausentes: a coluna critérios preserva os IDs do JSON; a coluna gates registra o vínculo operacional proposto aos targets existentes.
- Todos os critérios JSON são `required: true`. O score ≥96/100 é geral, não um limiar individual inventado. Condições obrigatórias permanecem: evidência same-candidate/current, ausência de Critical/High, autoridade independente, nenhum mock promovido a runtime, isolamento e budgets aprovados. Consultar o `target` e `evidence_method` do critério citado; a matriz não os substitui nem altera valores congelados.
- **IMPLEMENTED** significa que o contrato/runner/cálculo explicitado na linha existe e foi inspecionado, não que o caso passou ao vivo. **NOT_RUN** significa aceite não exercido ou implementação específica ainda ausente (indicada na linha). **BLOCKED_EXTERNAL** significa que a evidência exigida depende de harness, serviços, orçamento, CI ou autoridade externa não fornecidos/executados neste trabalho. Não é uma sondagem da disponibilidade atual do host.
- Linhas Q17 registram aceite dos épicos como NOT_RUN, não apagam correções paralelas. Linhas de caso distinguem contrato executável local de evidência externa. `Q17-NN.X` remete à tarefa exata no [backlog][BL]; nenhum ID canônico foi criado.
- Caminhos de artefatos de runtime ainda não produzidos são descritos pelos runners vinculados, não por links para arquivos inexistentes. Código e testes são evidência de implementação, nunca prova de execução real.

## Matriz única

| ID / requisito ou caso | Dimensões exatas do scorecard | Critérios JSON obrigatórios | Gate / comando proprietário | Backlog | Evidência atual e limite | Status |
|---|---|---|---|---|---|---|
| Q17-01 Arquitetura | Architecture; Modularity | P0-CONTROL; P1-REVIEWS-PROMOTION | `make validate`; `make triple-aaa-verify` | Q17-01.A/B/C | [BL], [MK], [PE]; revisão/ownership final não realizados | NOT_RUN |
| Q17-02 Documentação | Documentation; CI/CD; Production Readiness | P0-CONTROL; P0-RELEASE | `make validate`; `make quality-bar-static`; `make release-evidence` | Q17-02.A/B/C | [QB], esta matriz; cobertura integral das 64 seções e reconciliação canônica ainda pendentes | NOT_RUN |
| Q17-03 Identidade | Security; Multi-tenancy | P1-TENANT-EVIDENCE | `make api-security`; `make phase3-tenant-evidence-runtime` | Q17-03.A/B | [TE]; sessão/persistência/browser não aceitos aqui | NOT_RUN |
| Q17-04 Autorização | Security; Multi-tenancy | P1-TENANT-EVIDENCE | `make phase3-tenant-evidence-runtime` | Q17-04.A/B | [TE]; papéis/escopos exigem execução autorizada | NOT_RUN |
| Q17-05 Kernel HTTP | Security; Production Readiness | P0-LAB; P1-TENANT-EVIDENCE | `make api-security`; `make api16-root`; `make compose-static` | Q17-05.A/B | [MK], [TE]; lifecycle de stack não observado | NOT_RUN |
| Q17-06 Contratos | Modularity; Provider; Frontend | P0-CONTROL; P1-RAG-PROVIDER | `make api15-contracts`; `make api-contract`; `make api16-root` | Q17-06.A/B | [MK]; equivalência API/SSE não aceita nesta entrega | NOT_RUN |
| Q17-07 Knowledge | Ingestion; Object Storage; Evidence | P0-DURABILITY; P1-TENANT-EVIDENCE | `make api16-domain`; `make phase3-postgres-runtime`; `make phase3-tenant-evidence-runtime` | Q17-07.A/B | [PG], [TE]; paridade persistente requer runtime | NOT_RUN |
| Q17-08 Ingestão | Ingestion; Qdrant; Worker | P0-DURABILITY; P1-RAG-PROVIDER | `make phase3-golden-runtime`; `make phase3-file-security-runtime` | Q17-08.A/B/C | [GO], [FS]; 11 pontos declarados versus 12 exigidos | NOT_RUN |
| Q17-09 Retrieval | Retrieval; Qdrant | P0-REDIS-STORAGE; P1-RAG-PROVIDER | `make phase3-object-qdrant-runtime`; `make eval-retrieval-pack` | Q17-09.A/B | [OQ], [EV]; ablação real ausente | NOT_RUN |
| Q17-10 Evidence | Evidence; Multi-tenancy | P1-TENANT-EVIDENCE; P1-RAG-PROVIDER | `make phase3-tenant-evidence-runtime`; `make eval-retrieval-pack` | Q17-10.A/B | [TE], [EV]; consistência temporal real não observada | NOT_RUN |
| Q17-11 Decision | Decision; Evidence | P1-RAG-PROVIDER | `make phase3-provider-rag-runtime`; `make eval-retrieval-pack` | Q17-11.A/B | [MK], [GO]; política de domínio não aprovada aqui | NOT_RUN |
| Q17-12 Professor | Professor; Decision | P1-RAG-PROVIDER | `make api15-professor`; `make phase3-provider-rag-runtime` | Q17-12.A/B | [MK], [PV]; orçamento/stream real não observado | NOT_RUN |
| Q17-13 Providers | Provider; Resilience | P1-RAG-PROVIDER | `make api15-provider`; `make phase3-provider-runtime` | Q17-13.A/B | [PV]; credenciais/modelo/budget fora desta entrega | NOT_RUN |
| Q17-14 Avaliação RAG | Retrieval; Evidence; Decision; Professor; Provider | P1-RAG-PROVIDER | `make eval-retrieval`; `make eval-retrieval-pack` | Q17-14.A/B | [EV], [EP], [ET], [EC]; parte A local; baseline por grupo conflitante; holdout não executado | NOT_RUN |
| Q17-15 Chat | Frontend; Evidence; Professor | P1-FRONTEND; P1-RAG-PROVIDER | `make api16-root`; `make phase3-frontend-supply-runtime` | Q17-15.A/B | [FE]; caminho API/browser não exercido aqui | NOT_RUN |
| Q17-16 Documentos UI | Frontend; Ingestion; Accessibility | P1-FRONTEND; P0-DURABILITY | `make web-e2e`; `make phase3-golden-runtime` | Q17-16.A/B | [FE], [GO]; matriz browser não executada | NOT_RUN |
| Q17-17 Administração | Frontend; Security; Multi-tenancy; PostgreSQL | P1-TENANT-EVIDENCE; P1-FRONTEND; P0-DURABILITY | `make phase3-tenant-evidence-runtime`; `make phase3-postgres-runtime`; `make web-e2e` | Q17-17.A/B/C | [TE], [PG], [FE]; mutação/audit/UI requerem prova integrada | NOT_RUN |
| Q17-18 Containers | Production Readiness; Supply Chain | P0-LAB; P1-SUPPLY-CHAIN | `make compose-static`; `make up`; `make phase3-frontend-supply-runtime` | Q17-18.A/B | [MK], [FE]; nenhuma stack iniciada; up apenas com autorização | NOT_RUN |
| Q17-19 Jobs/PostgreSQL | Jobs; PostgreSQL | P0-DURABILITY | `make ops-static`; `make phase3-postgres-runtime` | Q17-19.A/B | [PG]; migração/transação real não executada | NOT_RUN |
| Q17-20 Worker | Worker; Jobs; Resilience | P0-DURABILITY; P0-LAB | `make api16-worker`; `make jobs-test`; `make phase3-multi-worker-runtime` | Q17-20.A/B | [MW], [WG]; oito seams presentes na árvore inspecionada, não runtime aceito | NOT_RUN |
| Q17-21 Redis | Redis; Resilience | P0-REDIS-STORAGE | `make phase3-redis-runtime`; `make phase3-redis-multi-replica-runtime` | Q17-21.A/B | [RD], [RR]; TLS/replicas não exercidos | NOT_RUN |
| Q17-22 Storage | Object Storage; Qdrant; Ingestion | P0-REDIS-STORAGE; P0-DURABILITY | `make storage-test`; `make phase3-object-qdrant-runtime` | Q17-22.A/B | [OQ]; rotação/rebuild/restore não aceitos | NOT_RUN |
| Q17-23 Observabilidade | Observability; Production Readiness | P1-OBSERVABILITY | `make phase3-observability-runtime` | Q17-23.A/B | [OB]; trace/scrape/alerta distribuído não observado | NOT_RUN |
| Q17-24 Recuperação/capacidade | Resilience; Disaster Recovery; Performance | P1-RECOVERY | `make phase3-restore-runtime`; `make phase3-performance`; `make phase3-chaos`; `make phase3-soak` | Q17-24.A/B/C | [DR], [OP], [OL]; harness e budgets aprovados requeridos | NOT_RUN |
| Q17-25 CI/release | CI/CD; Supply Chain; Production Readiness | P0-CONTROL; P0-RELEASE; P1-SUPPLY-CHAIN; P1-REVIEWS-PROMOTION | `make release-evidence`; `make phase3-evidence`; `make phase3-evidence-verify`; `make triple-aaa-verify` | Q17-25.A/B/C/D | [CI], [CE], [PE], [TV]; sem CI same-SHA/selo/Go independente | NOT_RUN |
| Q17-26 QA/visual | Architecture; Frontend; Accessibility; Production Readiness | P0-CONTROL; P1-FRONTEND; P1-REVIEWS-PROMOTION | `make validate`; `make lint`; `make typecheck`; `make web-validate`; `make triple-aaa-verify` | Q17-26.A/B/C/D | [MK], [FE], [PE]; testes locais não equivalem a revisão independente | NOT_RUN |
| CI-01 FAST | CI/CD; Architecture | P0-CONTROL | `make validate`; `make ops-static`; `make compose-static` | Q17-25.B; Q17-26.B | [CI] job fast + [CE]; lane definida, sem execução GitHub aqui | IMPLEMENTED |
| CI-02 UNIT | CI/CD; Modularity | P0-CONTROL | `make api15-contracts`; `make api16-domain`; `make api16-worker` | Q17-25.B; Q17-26.B | [CI] job unit + [CE]; inclui provider/lock/professor/evidence/decision | IMPLEMENTED |
| CI-03 CONTRACT | CI/CD; Modularity | P0-CONTROL | `make api-contract`; `make api16-root` | Q17-25.B; Q17-26.B | [CI] job contract + [CE] | IMPLEMENTED |
| CI-04 SECURITY | CI/CD; Security | P1-TENANT-EVIDENCE | `make api-security`; `make security-adversarial` | Q17-25.B; Q17-26.B | [CI] job security + [CE] | IMPLEMENTED |
| CI-05 RAG_EVAL | CI/CD; Retrieval; Evidence | P1-RAG-PROVIDER | `make eval-retrieval`; `make eval-retrieval-pack`; `make api14-acl` | Q17-25.B; Q17-14.A | [CI] job rag-eval + [CE]; definição presente, baseline agora expõe falha | IMPLEMENTED |
| CI-06 FRONTEND | CI/CD; Frontend | P1-FRONTEND | `make web-lint`; `make web-typecheck`; `make web-build` | Q17-25.B; Q17-26.C | [CI] job frontend + [CE]; browser é gate separado | IMPLEMENTED |
| CI-07 SUPPLY_CHAIN | CI/CD; Supply Chain | P1-SUPPLY-CHAIN | workflow: `pip-audit`, `npm audit`, `python infrastructure/docker/check_release.py --mode prepared` | Q17-25.B/C | [CI] job supply-chain + [CE]; não há target Make exclusivo para estes scanners | IMPLEMENTED |
| CI-08 RELEASE | CI/CD; Production Readiness | P0-RELEASE; P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-25.B/D | [CI] job release, [TV], [PE]; definição fail-closed não é aprovação | IMPLEMENTED |
| WORKER-01 after_claim | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG] CRASH_POINTS/_run_crash_cycle; seam executável, DB real não rodado | IMPLEMENTED |
| WORKER-02 after_heartbeat | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; heartbeat e recovery após crash | IMPLEMENTED |
| WORKER-03 during_handler | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; seam do handler na árvore atual | IMPLEMENTED |
| WORKER-04 before_result | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; before result write | IMPLEMENTED |
| WORKER-05 in_transaction | Worker; PostgreSQL | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B; Q17-19.B | [MW], [WG]; inside result transaction, não confundir com fake rollback | IMPLEMENTED |
| WORKER-06 after_commit | Worker; PostgreSQL | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; after commit before ACK | IMPLEMENTED |
| WORKER-07 before_publish | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; recuperação exige autoridade/outbox | IMPLEMENTED |
| WORKER-08 after_publish | Worker; Jobs | P0-DURABILITY | `make phase3-multi-worker-runtime` | Q17-20.B | [MW], [WG]; produção requer todos os oito PASS reais | IMPLEMENTED |
| INGEST-01 after upload | Ingestion; Object Storage | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GO], [GG] after_upload; injector/composição externa requerida | BLOCKED_EXTERNAL |
| INGEST-02 after object write | Ingestion; Object Storage | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_object_store via [GO] | BLOCKED_EXTERNAL |
| INGEST-03 after enqueue | Ingestion; Jobs | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_enqueue via [GO] | BLOCKED_EXTERNAL |
| INGEST-04 after parse | Ingestion | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_extraction via [GO]; equivalência parse/extraction precisa ser preservada no injector | BLOCKED_EXTERNAL |
| INGEST-05 after normalize | Ingestion | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [PR] seção 23 exige; [GG] FAILURE_POINTS tem 11 e não separa normalize; lacuna de implementação | NOT_RUN |
| INGEST-06 after chunk | Ingestion | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_chunking via [GO] | BLOCKED_EXTERNAL |
| INGEST-07 after embed | Ingestion; Provider | P0-DURABILITY; P1-RAG-PROVIDER | `make phase3-golden-runtime` | Q17-08.C | [GG] after_embedding via [GO] | BLOCKED_EXTERNAL |
| INGEST-08 during Qdrant | Ingestion; Qdrant | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] during_qdrant via [GO] | BLOCKED_EXTERNAL |
| INGEST-09 before verify | Ingestion; Evidence | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] before_verification via [GO] | BLOCKED_EXTERNAL |
| INGEST-10 after verify | Ingestion; Evidence | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_verification via [GO] | BLOCKED_EXTERNAL |
| INGEST-11 before publish | Ingestion; Worker | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] before_publish via [GO]; preservar versão válida | BLOCKED_EXTERNAL |
| INGEST-12 after publish | Ingestion; Worker | P0-DURABILITY | `make phase3-golden-runtime` | Q17-08.C | [GG] after_publish via [GO]; conferir linhagem após recovery | BLOCKED_EXTERNAL |
| CITATION-01 citation_precision | Evidence | P1-RAG-PROVIDER | `make eval-retrieval-pack` | Q17-14.A/B | [EV] _claim_support_metrics; interseção de IDs anotados, não entailment | IMPLEMENTED |
| CITATION-02 citation_recall | Evidence | P1-RAG-PROVIDER | `make eval-retrieval-pack` | Q17-14.A/B | [EV] _claim_support_metrics; referências aprovadas exigidas | IMPLEMENTED |
| CITATION-03 citation_completeness | Evidence | P1-RAG-PROVIDER | `make eval-retrieval-pack` | Q17-14.A/B | [EV] _claim_support_metrics; claims com suporte anotado | IMPLEMENTED |
| CITATION-04 unsupported_claim_rate | Evidence; Decision | P1-RAG-PROVIDER | `make eval-retrieval-pack` | Q17-14.A/B | [EV] _claim_support_metrics; ausência de anotação não é zero | IMPLEMENTED |
| CITATION-05 faithfulness | Evidence; Professor | P1-RAG-PROVIDER | `make eval-retrieval-pack` | Q17-14.A/B | [EV] _claim_support_metrics; anotação reviewed explícita, sem juiz semântico live | IMPLEMENTED |
| CHAOS-01 kill-worker | Resilience; Worker | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL] CHAOS_FAULTS; requer RICK_PHASE3_CHAOS_COMMAND aprovado | BLOCKED_EXTERNAL |
| CHAOS-02 kill-worker-a-only | Resilience; Worker | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; Worker B deve recuperar | BLOCKED_EXTERNAL |
| CHAOS-03 kill-redis | Resilience; Redis | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-04 restart-redis | Resilience; Redis | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-05 kill-qdrant | Resilience; Qdrant | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-06 restart-qdrant | Resilience; Qdrant | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-07 postgres-outage | Resilience; PostgreSQL | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-08 s3-outage | Resilience; Object Storage | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-09 provider-timeout | Resilience; Provider | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; orçamento e provider aprovados | BLOCKED_EXTERNAL |
| CHAOS-10 provider-429 | Resilience; Provider | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; orçamento e provider aprovados | BLOCKED_EXTERNAL |
| CHAOS-11 provider-500 | Resilience; Provider | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; injector externo | BLOCKED_EXTERNAL |
| CHAOS-12 network-delay | Resilience | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; lab isolado autorizado | BLOCKED_EXTERNAL |
| CHAOS-13 connection-reset | Resilience | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OP], [OL]; lab isolado autorizado | BLOCKED_EXTERNAL |
| INVARIANT-01 no_silent_corruption | Resilience; Disaster Recovery | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OL] CHAOS_ASSERTIONS; exigido em cada uma das 13 faults | BLOCKED_EXTERNAL |
| INVARIANT-02 no_duplicate_publish | Resilience; Worker | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OL] CHAOS_ASSERTIONS; exigido por fault | BLOCKED_EXTERNAL |
| INVARIANT-03 bounded_retries | Resilience; Provider | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OL] CHAOS_ASSERTIONS; exigido por fault | BLOCKED_EXTERNAL |
| INVARIANT-04 circuit_breaker_correct | Resilience; Provider | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OL] CHAOS_ASSERTIONS; exigido por fault | BLOCKED_EXTERNAL |
| INVARIANT-05 eventual_recovery | Resilience; Disaster Recovery | P1-RECOVERY | `make phase3-chaos` | Q17-24.C | [OL] CHAOS_ASSERTIONS; exigido por fault | BLOCKED_EXTERNAL |
| SOAK-01 short | Resilience; Performance | P1-RECOVERY | `make phase3-soak` | Q17-24.C | [OP], [OL] SOAK_PROFILES/SOAK_METRICS; RICK_PHASE3_SOAK_COMMAND e janela aprovada | BLOCKED_EXTERNAL |
| SOAK-02 extended | Resilience; Performance | P1-RECOVERY | `make phase3-soak` | Q17-24.C | [OP], [OL]; memória/threads/processos/conexões/filas/latência/retries/starvation/FDs | BLOCKED_EXTERNAL |
| PERF-01 api-only × 1 | Performance | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL] PERFORMANCE_WORKLOADS/CONCURRENCY_LEVELS; RICK_PHASE3_PERFORMANCE_COMMAND | BLOCKED_EXTERNAL |
| PERF-02 api-only × 10 | Performance | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; baseline/hardware/limites/dataset/provider/modelo/versões | BLOCKED_EXTERNAL |
| PERF-03 api-only × 50 | Performance | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-04 api-only × 100 | Performance | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-05 retrieval × 1 | Performance; Retrieval | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; p50/p95/p99/throughput/erros/CPU/RAM/queue_depth exigidos em cada célula | BLOCKED_EXTERNAL |
| PERF-06 retrieval × 10 | Performance; Retrieval | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-07 retrieval × 50 | Performance; Retrieval | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-08 retrieval × 100 | Performance; Retrieval | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-09 chat × 1 | Performance; Professor | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; orçamento externo aprovado | BLOCKED_EXTERNAL |
| PERF-10 chat × 10 | Performance; Professor | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-11 chat × 50 | Performance; Professor | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-12 chat × 100 | Performance; Professor | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-13 ingestion × 1 | Performance; Ingestion | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; dataset aprovado | BLOCKED_EXTERNAL |
| PERF-14 ingestion × 10 | Performance; Ingestion | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-15 ingestion × 50 | Performance; Ingestion | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-16 ingestion × 100 | Performance; Ingestion | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-17 worker-throughput × 1 | Performance; Worker | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; queue real requerida | BLOCKED_EXTERNAL |
| PERF-18 worker-throughput × 10 | Performance; Worker | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-19 worker-throughput × 50 | Performance; Worker | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| PERF-20 worker-throughput × 100 | Performance; Worker | P1-RECOVERY | `make phase3-performance` | Q17-24.B | [OP], [OL]; sem amostra real | BLOCKED_EXTERNAL |
| REVIEW-01 Architecture | Architecture; Modularity | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE] PACKET_REVIEW_SCOPES; reviewer fresco independente não fornecido | BLOCKED_EXTERNAL |
| REVIEW-02 Security | Security; Multi-tenancy | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-03 Runtime | Production Readiness; Worker | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-04 Database | PostgreSQL; Jobs | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-05 Distributed Systems | Redis; Qdrant; Resilience | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-06 RAG | Retrieval; Evidence; Decision; Professor; Provider | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-07 Observability | Observability | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-08 Recovery | Disaster Recovery; Resilience | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-09 Frontend | Frontend | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-10 Accessibility | Accessibility | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-11 Supply Chain | Supply Chain | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| REVIEW-12 Operations | Production Readiness; Performance; Documentation | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; não executada | BLOCKED_EXTERNAL |
| FINAL-01 race_condition | Worker; Jobs | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE] PACKET_CRITIC_CHECKS; crítica independente exigida, não feita | BLOCKED_EXTERNAL |
| FINAL-02 lost_update | PostgreSQL; Jobs | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-03 split_brain | Redis; Worker | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-04 stale_lease | Worker; Redis | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-05 duplicate_publish | Worker; Ingestion | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-06 unsafe_retry | Provider; Resilience | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-07 deadlock | PostgreSQL; Worker | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-08 cross_tenant_leakage | Security; Multi-tenancy | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-09 timing_leak | Security; Multi-tenancy | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-10 stale_evidence | Evidence | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-11 fake_promotion | CI/CD; Production Readiness | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-12 secret_leak | Security; Observability | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-13 retry_storm | Resilience; Provider | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-14 orphan_object | Object Storage; Ingestion | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-15 stale_qdrant_projection | Qdrant | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-16 audit_gaps | Security; PostgreSQL | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-17 unbounded_memory | Performance; Resilience | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |
| FINAL-18 unsafe_fallback | Retrieval; Resilience | P1-REVIEWS-PROMOTION | `make triple-aaa-verify` | Q17-26.D | [PE]; crítica não feita | BLOCKED_EXTERNAL |

## Verificação e prova

**Escopo/IDs:** Q17-02.A parcial e Q17-14.A parcial. Uma matriz: 26 linhas Q17 + 103 casos = **129 linhas**. Casos: 8 CI, 8 worker, 12 ingestão, 5 citações, 13 chaos + 5 invariantes (os cinco em cada fault), 2 soak, 20 células de performance, 12 reviews, 18 checks. Distribuição: **21 IMPLEMENTED, 27 NOT_RUN, 81 BLOCKED_EXTERNAL**. As 26 dimensões do scorecard e os 12 critérios do JSON aparecem no vínculo Q17.

**Candidato/ambiente:** árvore local compartilhada e não selada, Python 3.12.3, sem rede/serviços/commits. Nenhum hash de artefato de aceitação é fabricado. As referências são fontes atuais inspecionadas, não evidência same-SHA de produção. Inspeção do worker pode refletir mudanças paralelas; não atribui autoria nem aceite a este builder.

**Procedimento:** ler Makefile e contratos, enumerar casos sem colapsar ausências, checar cada destino de link local, comparar IDs de critérios/dimensões/subtarefas e targets Make com as fontes. Testes: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q scripts/state_of_art/tests/test_evaluate_pack.py scripts/state_of_art/tests/test_evaluate_retrieval.py`; baseline obrigatório: `make eval-retrieval-pack`. Os 378 testes de `python3 -m pytest scripts/state_of_art/tests/ -x --tb=short` passaram durante esta entrega; isso não executa as matrizes externas. A invocação anterior com `pytest` sem `python3 -m` falhou em coleta por import path; não é um PASS oculto.

**Checagens locais observadas:** testes focados finais: 21 passed, exit 0; `make lint`: exit 0; `git diff --check` no patch: exit 0. Validador Python temporário `/tmp/opencode/check_q17_matrix.py`: exit 0, 29 destinos locais existentes, 129 linhas, IDs/subtarefas/targets íntegros, 26 dimensões e 12 critérios cobertos. Este verificador é auxiliar local, não gate canônico novo. `make typecheck` não foi executado porque chama build do Professor fora do escopo permitido; compilação sintática em memória dos dois arquivos Python alterados passou. `make eval-retrieval-pack`: FAIL, receita exit 1 (Make exit 2); não há baseline verde.

**Resultado/limite:** a aplicação rigorosa dos thresholds por grupo revela alpha Recall@1=0.5 <0.75 no pack congelado, embora agregado=0.75. Não se reduziu limiar nem se relabelou fixture para manter verde. Ver [contrato de avaliação][EC]. A resolução depende do owner do pack. Esta matriz não afirma Q17-14.A completo.

**Revisão/recuperação:** autoinspeção do builder, não revisão independente. Recuperação: reverter somente estes patches próprios sob coordenação da árvore compartilhada; nenhuma mudança em dados/serviços. Nenhum arquivo de controle canônico ou snapshot histórico foi editado por esta entrega.

**NOT-DONE:** mapa seção-a-seção das 64 seções e ativação canônica D06; aprovação dos vínculos dimensionais/gates ausentes no JSON; after-normalize como boundary distinto; execução real das matrizes; revisão independente/autoridade e aceitação final. O threshold verde incompatível, reranker gain/relevância/abstenção e corpus licenciado/holdout permanecem abertos. Não há score nem GO novo. Próximo passo: owner resolver conflito do baseline e nomenclatura oficial antes de aceitar Q17-02.A/Q17-14.A integralmente.

[BL]: ../plans/backlog-qualidade-2026-09-17.md
[QB]: current-triple-aaa-quality-bar-v1.json
[PR]: ../prompts/triple-aaa-runtime-closure-2026-09-10.txt
[MK]: ../../Makefile
[PE]: ../../scripts/state_of_art/promotion_engine.py
[TV]: ../../scripts/state_of_art/triple_aaa_verify.py
[CI]: ../../.github/workflows/quality.yml
[CE]: ../../scripts/state_of_art/ci_lane_evidence.py
[EV]: ../../scripts/state_of_art/evaluate_retrieval.py
[EP]: ../../scripts/state_of_art/evaluate_pack.py
[ET]: ../../scripts/state_of_art/tests/test_evaluate_pack.py
[EC]: ../evals/rag-evaluation.md
[TE]: ../../scripts/state_of_art/run_phase3_tenant_evidence.py
[PG]: ../../scripts/state_of_art/run_phase3_postgres.py
[GO]: ../../scripts/state_of_art/run_phase3_golden_runtime.py
[GG]: ../../scripts/phase11/golden_runtime_gate.py
[FS]: ../../scripts/state_of_art/run_phase3_file_security.py
[OQ]: ../../scripts/state_of_art/run_phase3_object_qdrant.py
[PV]: ../../scripts/state_of_art/run_phase3_provider.py
[FE]: ../../scripts/state_of_art/run_phase3_frontend_supply.py
[MW]: ../../scripts/state_of_art/run_phase3_multi_worker.py
[WG]: ../../scripts/phase11/multi_worker_runtime_gate.py
[RD]: ../../scripts/state_of_art/run_phase3_redis.py
[RR]: ../../scripts/state_of_art/run_phase3_redis_multi_replica.py
[OB]: ../../scripts/state_of_art/run_phase3_observability.py
[DR]: ../../scripts/state_of_art/run_phase3_restore.py
[OP]: ../../scripts/state_of_art/run_phase3_operational.py
[OL]: ../../scripts/state_of_art/phase3_lane.py

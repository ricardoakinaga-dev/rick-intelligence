# Roadmap — RICK Intelligence State of the Art / AAA

O roadmap é orientado por gates, não por datas artificiais. Cada estágio só
avança com o evidence pack definido no plano e com rollback conhecido.

| Estágio | Objetivo | Entregas principais | Gate de saída | Estado |
| --- | --- | --- | --- | --- |
| R0. Recuperação e baseline | Tornar o estado do programa confiável | plano vivo, bar congelado, backlog, fingerprint, regressão corrigida, matriz atual | `SA-FOUNDATION` sem regressões conhecidas | concluído no escopo hermético |
| R1. Spine canônico | Tirar o root do modo apenas hermético | SQLite knowledge/vector/audit/job journal, staging privado, fila bounded, adapters Qdrant/Redis herméticos e provider resilience; ainda faltam Postgres, object storage externo, broker distribuído e wiring live | restart/retry/ACL/live adapters demonstrados | local verificado; externo pendente |
| R2. Web canônica | Colocar o produto na frente dos usuários | `apps/web`, auth/session, shell, documentos com filtros/paginação, busca, chat com estados de evidência, admin/readiness, lifecycle, E2E e screenshots | search/audit/lifecycle completos + visual/a11y independente | local verificado; critic pendente |
| R3. Inteligência AAA | Melhorar qualidade e confiança da resposta | harness offline de retrieval, fixture sem dados sensíveis, provenance/citations, provider budgets e guardrails iniciais | corpus aprovado, quality thresholds e regressão live de eval | fixture verificada; externo pendente |
| R4. Operação de produção | Operar com segurança e previsibilidade | compose/migração/regras SLO/observabilidade/runbooks estáticos e validadores | Docker/deploy, collectors, backup/restore, readiness real, failure drills e performance | artefatos estáticos; runtime pendente |
| R5. Promoção | Decidir rollout de forma reversível | dual validation, canary, migration map, critic final e handoff | Final Gauntlet APPROVE, zero gaps críticos/altos | planejado |

## Sequenciamento e paralelismo

R0 é sequencial. Após o gate de fundação, R1 pode dividir-se em três lanes:

- **R1-Domain:** contratos, persistência e lifecycle;
- **R1-Platform:** adapters live, worker e observabilidade;
- **R1-Security:** auth externa, tenant isolation e hardening.

R2 pode começar em paralelo com R1-Platform depois de congelar o contrato HTTP
e a fixture API; não pode editar os contratos compartilhados sem handoff.
R3 possui uma harness offline independente e pode avançar em paralelo, mas só
promove qualidade quando os adapters live e as fixtures aprovadas estiverem
disponíveis. R4 pode produzir artefatos estáticos agora, porém o gate real
depende de runtime externo, secrets e drills executados. R5 é posterior à
integração das frentes.

## Critérios por estágio

### R0 — recuperação

- estado `.agent` reconciliado sem apagar histórico;
- nova execução Gauntlet identificada separadamente;
- backlog executivo e machine-readable alinhados;
- `make validate`, differential, API, segurança, contrato e preservation checks
  executados com resultado explícito;
- qualquer falha é corrigida pela causa, com teste direcionado e regressão.

### R1 — spine canônico

- caminho de upload não depende de memória local para disponibilidade;
- documento e job sobrevivem restart e possuem chave de idempotência;
- storage privado não aceita path do cliente;
- worker possui backpressure, retry finito, dead-letter e cancelamento seguro;
- Qdrant/Redis/provider têm adapters tipados e health sem vazamento;
- métricas não contêm prompt, documento, segredo ou URL sensível.

### R2 — web canônica

- `apps/web` possui package/lockfile/build independentes e chama apenas API root;
- fluxos principais têm loading, empty, error, permission denied e success;
- teclado, foco, contraste, reduced motion e leitor de tela são verificados;
- 375, 768 e 1440px têm screenshot/render atual e zero overflow regressivo;
- a linguagem visual é coerente: confiança, evidência, escopo e status são
  visíveis sem ruído de “dashboard genérico”.

### R3–R5

Os critérios detalhados estão no backlog e no Quality Bar congelado. A regra é
não transformar um mock determinístico em evidência de produção, nem transformar
uma tela bonita em prova de segurança ou grounding.

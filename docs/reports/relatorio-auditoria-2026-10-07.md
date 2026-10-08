# Auditoria do RICK Intelligence — 07/10/2026

## 1. Parecer executivo

**Nota geral do recorte auditado: 64,2/100 (64/100 arredondada). Produção: `NO-GO`.**

O checkout atual não passa a própria cadeia de validação. Cinco gates obrigatórios retornam
vermelho: `make validate`, `make lint`, `make test-fast`, `make api-security` e `make build`.
A remoção dos três componentes legados não foi reconciliada com validadores, workflows de CI,
README nem com 48 documentos que ainda os descrevem como superfícies preservadas. Foram
reproduzidos ao vivo dois defeitos já conhecidos (busca em coleção arquivada e idempotência
cruzando conversas) e identificado um terceiro novo (rotas de auditoria fora da política
default-deny).

Do lado positivo, a base local é substancial: **≈ 7.175 testes verdes** em oito lanes,
**339 testes de navegador** em três viewports com evidência de performance, cobertura web de
92,14% de linhas, `pip-audit` limpo, zero segredos versionados e Actions fixadas por SHA.

A nota é avaliação técnica qualitativa, não percentual de funcionalidades concluídas, não
probabilidade de segurança e não autorização para produção. Um gate obrigatório falho não é
compensado pela média.

## 2. Escopo, versão e método

- Observação: **07/10/2026, aproximadamente 10:40–11:20 UTC**.
- Checkout: `/home/ricardo/rick-intelligence`; HEAD `b52f32c`.
- **Árvore extensamente modificada**: 889 mudanças (219 modificados, 439 apagados, 231 não
  rastreados), `+23.745 / −3.532`. O objeto auditado é esse worktree, não somente o HEAD.
- Modo: auditoria brownfield somente de leitura sobre o código do repositório. Nenhum arquivo
  versionado foi alterado; nenhuma migration, deploy, push, leitura de `.env` ou chamada a
  modelo pago foi executada.
- Ambiente: Python `3.12.3` (compatível com `toolchain.json`); Node `v24.20.0` no host contra o
  contrato `22.19.0`; venv temporário criado a partir de `requirements/test.lock` com hashes,
  porque `.runtime/venvs/cvg` está vazio e o Python do sistema não possui `jsonschema`.

### Documentos de referência lidos

[README](../../README.md), [índice documental](../INDEX.md), [contribuição](../../CONTRIBUTING.md),
[contrato de avaliação de retrieval](../evaluation/retrieval-evaluation.md),
[limites de dependência](../architecture/dependency-boundaries.json),
[integridade de release](../architecture/release-integrity.md),
[runbook de release](../operations/release-readiness.md) e os relatórios/roadmaps/backlogs das
rodadas AUD03 e de 06/10/2026, usados como contexto histórico e não como evidência desta rodada.

### Critérios e escala

Critérios definidos antes do parecer: documentação e aderência ao checkout, arquitetura,
higiene do repositório, contratos, autorização, segurança, integridade de dados, testes,
reprodutibilidade, lint/typecheck, frontend/E2E, CI, build, qualidade de IA, operação e promoção.

| Faixa | Interpretação |
|---|---|
| 0–39 | Evidência insuficiente ou lacunas estruturais graves |
| 40–59 | Parcial; bloqueios relevantes |
| 60–74 | Base útil, com fragilidades materiais |
| 75–89 | Implementação local forte, ainda com limites relevantes |
| 90–100 | Evidência muito forte e abrangente para o escopo; 100 exigiria ausência de lacunas materiais conhecidas |

A nota geral é a **média simples das 26 áreas** (soma 1.670, divisão por 26). Não é comparável
diretamente com scorecards anteriores de outros escopos.

## 3. Comandos executados e resultados

| Comando | Exit | Resultado |
|---|---:|---|
| `make validate` | **2** | FAIL — `missing preserved component` × 3 |
| `make lint` | **2** | FAIL — 406 erros / 5053 avisos, **todos** em `apps/web/.next-audit-20261006/`; `eslint` sobre o código-fonte real = **0 problemas** |
| `make typecheck` | **2** | `tsc --noEmit` web **PASS**; lanes legadas `NOT AVAILABLE`; nenhum type-checker Python configurado |
| `make test-fast` | **2** | FAIL — validador de fronteiras + `jsonschema` ausente + lanes legadas |
| `make build` | **2** | build web **PASS**; Professor/CVG/CPython legados `NOT AVAILABLE` |
| `make api-test` | **2** | 1 arquivo quebra a coleta (`test_differential_auth.py`) |
| `make api-contract` | 0 | **PASS** — 55 paths OpenAPI |
| `make api-security` | **2** | **1 failed / 72 passed** — 3 rotas fora do `ROUTE_REGISTRY` |
| `make api14-acl` | 0 | **PASS** — 14 |
| `make api15-full` / `make api16-full` | 2 | bloqueados por `validate` |
| `make compose-static` | 0 | **PASS** — 16 serviços × 2 topologias |
| `make eval-retrieval-pack` | 0 | **PASS** — pack de **5 casos** sintéticos |
| `make security-adversarial` | 0 | **PASS** — 8 registros / 8 categorias |
| `make storage-test` | 0 | **PASS** — 28 |
| `make ops-static` | 0 | **PASS** — 297 |
| `make web-build` | 0 | **PASS** |
| `make web-e2e` | 0 | **PASS** — 339 testes, LCP máx 1044 ms, CLS máx 0,0022 |
| `npm run test:coverage` (web) | 0 | **PASS** — 76 testes, 89,81% stmts / 92,14% linhas |
| pytest `apps/api/tests` (ignorando `test_differential_auth.py`) | 0 | **1561 passed, 18 skipped** |
| pytest por pacote em `packages/` | — | **3278 passed** (retrieval com 2 arquivos legados excluídos) |
| pytest `apps/worker` (ignorando 1 arquivo) | 0 | **730 passed** |
| pytest `infrastructure` | 0 | **894 passed, 84 skipped** |
| `pip-audit -r requirements/runtime.lock --strict` | 0 | **sem vulnerabilidades conhecidas** |
| `npm audit` (apps/web) | — | **2 HIGH** — `sharp` (CVE-2026-96889) e `source-map-js` (GHSA-68fv-2mgg-jv7q), ambos com fix |

**Total aproximado de testes verdes nesta rodada: 7.175.**

### Verificação de documentação (links locais)

| Conjunto | Arquivos | Links | Quebrados |
|---|---:|---:|---:|
| Primários (README, CONTRIBUTING, INDEX, architecture, operations, ci, runbooks, security, evals, prompts) | 69 | 80 | **0** |
| `docs/plans/` | 19 | 82 | **0** |
| `docs/reports/*.md` | 52 | 332 | **1** |
| Varredura ampla (inclui cópias históricas em `evidence/`) | 749 | 1113 | 126 |

## 4. Notas por item analisado

| # | Item | Nota /100 | Fundamentação e principal limite |
|---:|---|---:|---|
| 1 | Documentação: organização e honestidade | **68** | Índice, regras de frescor e recusa explícita de `GO` são exemplares; 48 de 199 `.md` ainda descrevem sistemas legados inexistentes. |
| 2 | Aderência documentação ↔ checkout | **35** | [README](../../README.md#L3-L17) declara os três legados como superfícies "byte-identical" e os lista no layout; os diretórios não existem (439 arquivos apagados). |
| 3 | Arquitetura e limites de dependência | **82** | Separação `apps → packages → contratos` consistente; o [validador](../../scripts/phase15/check_boundaries.py) existe e roda, mas sua regra central falha por legado ausente, não por violação de import. |
| 4 | Higiene do repositório | **40** | 90 MB de build não rastreado, **2 GB untracked** (`docs/reports/evidence/` = 1,86 GB), árvore de 5,1 GB com 759 arquivos versionados; basenames de teste duplicados entre pacotes. |
| 5 | Estado do worktree / rastreabilidade Git | **30** | 889 mudanças pendentes, `+23.745/−3.532`; nada commitável em bloco; evidência de 1,86 GB fora do versionamento. |
| 6 | Contratos API e OpenAPI | **88** | `make api-contract` PASS, 55 paths, envelopes validados; diff de breaking change não verificado nesta rodada. |
| 7 | Autorização e política de rotas | **66** | Default-deny + allowlist com teste próprio e 34 testes de autorização verdes; **3 rotas novas fora do registro** derrubam `api-security`. |
| 8 | Identidade, sessão e grants | **88** | 201 pass / 16 skip; snapshots, revogação e escopo explícitos. |
| 9 | Segurança (segredos + dependências) | **80** | Zero segredos em arquivos rastreados; Actions por SHA e installs com hashes; `pip-audit` limpo; **2 HIGH no npm** com fix disponível. |
| 10 | Integridade de idempotência do chat | **35** | **A03 reproduzido**: replay devolve resposta de outra conversa/pedido. |
| 11 | Lifecycle de coleção e frescor da busca | **45** | **A02 reproduzido**: conteúdo de coleção arquivada continua retornando em busca escopada e global. |
| 12 | Ingestão e validação de documentos | **87** | 374 testes verdes; embeddings validados antes de escrita; corpus hostil completo não repetido. |
| 13 | Persistência, knowledge e lineage | **72** | 83 pass com **98 skips** (PostgreSQL real não exercitado); storage 28 pass. |
| 14 | Worker, filas e fencing | **86** | 730 testes verdes; ack/receipts separados de execução. |
| 15 | Providers, streaming e resiliência | **82** | 2143 testes verdes; `production_safe` ainda defaulta a `True` sem probe no wrapper. |
| 16 | Volume e resultado dos testes | **85** | ≈7.175 verdes em 8 lanes + 339 E2E; os defeitos reproduzidos ainda escapam das suites. |
| 17 | Reprodutibilidade do bootstrap de testes | **45** | Exigiu venv manual, `PYTHONPATH` declarado só no CI, `.runtime/venvs/cvg` vazio, `jsonschema` ausente, 1 arquivo quebrando coleta. |
| 18 | Lint e limpeza de código | **58** | Código-fonte real com **0 problemas**; o gate falha por artefato obsoleto; 300 `TODO/FIXME`. |
| 19 | Typecheck | **62** | `tsc` web PASS; **nenhum type-checker Python** configurado no projeto. |
| 20 | Frontend: testes unitários e build | **90** | 76 testes, 89,81% stmts / 92,14% linhas, build de produção verde. |
| 21 | E2E de navegador e acessibilidade | **88** | 339 testes em 375/768/1440, specs de teclado, reflow 200% e reduced-motion, evidência de performance gerada. |
| 22 | CI e workflows | **40** | Pinagem por SHA e locks com hashes são fortes; **58 referências a caminhos apagados** quebram `supply-chain` → `release`. |
| 23 | Build, Compose e imagens | **70** | Compose estático PASS, 3 Dockerfiles + manifesto/política de release; build/scan/SBOM/assinatura não executados aqui. |
| 24 | Qualidade de IA/RAG (avaliação) | **42** | Harness determinístico PASS, mas pack com **5 casos sintéticos** e corpus adversarial de **8 registros**; nenhum modelo real avaliado. |
| 25 | Ops: migrations, observabilidade, estáticos | **74** | `ops-static` 297 PASS, 10 migrações com checksums e lock; nada de runtime PostgreSQL/Redis/Qdrant/OTel ao vivo. |
| 26 | Promoção e prontidão de produção | **32** | Gates fail-closed existem, mas o próprio checkout não passa `validate`, `lint`, `test-fast`, `api-security` e `build`. |

**Média simples (26 itens): 1.670 / 26 = 64,2 → 64/100.**

## 5. Achados priorizados

Prioridades: **P0** = corrigir antes de qualquer candidatura a produção; **P1** = corrigir antes
do gate de integração; **P2** = próxima rodada de robustez/manutenção. Severidade mede impacto;
prioridade mede ordem. Confiança é alta nos achados reproduzidos ao vivo e nos encadeamentos
estáticos abaixo.

### A01 — Alta / P0 — remoção dos legados não foi reconciliada com validadores, CI e documentação

**Esperado:** a [regra de migração](../../README.md#L145-L156) exige equivalência e ajuste dos
consumidores antes da remoção.

**Observado:** `make validate`, `make lint`, `make test-fast`, `make build`, `api15-full` e
`api16-full` terminam em exit 2 apontando `cvg-master-rag-v2`, `rick-professor` e
`modulo-redis-locker` ausentes. Há **58 referências** a esses caminhos em
`.github/workflows/` (40 em `phase-0.6.yml`, 8 em `quality.yml`, 8 em `phase-1.1.yml`), sendo a
lane `supply-chain` a que executa `npm ci`/`pip-audit` sobre eles; o job `release` depende de
`supply-chain`. O [README](../../README.md#L53-L70) e **48 de 199** arquivos `.md` ainda os
descrevem como superfícies preservadas byte-idênticas.

**Impacto:** a cadeia canônica não é executável e a CI não pode passar; a declaração de
equivalência declarada não é verificável.

**Fechamento:** decidir preservação ou retirada autorizada; reconciliar README, os 48
documentos, `scripts/phase15/check_boundaries.py` e as 58 referências de workflow; demonstrar
`make validate`, `make ci` e as suites originais em checkout limpo, sem exclusões ad hoc.

### A02 — Alta / P0 — busca continua expondo conteúdo de coleção arquivada (reproduzido)

**Esperado:** lifecycle/revogação uniforme entre catálogo, Professor e busca.

**Observado e reproduzido:** login `200` → `POST /api/v1/search` `200/1 item` →
`POST /api/v1/collections/rag_phase0/archive` `200/"archived"` → nova busca `200/1 item`,
tanto escopada (`collection_id`) quanto global. O catálogo corretamente retorna `[]`, mas a
[busca](../../apps/api/src/routes/search.py#L141-L182) revalida escopo e não a autoridade de
lifecycle; [retrieval_service](../../apps/api/src/services/retrieval_service.py) não consulta
`status` de coleção em nenhum ponto do caminho.

**Impacto:** conteúdo retirado do catálogo permanece consultável. Reprodução in-process local;
não foi demonstrado vazamento entre tenants nem exposição em Qdrant remoto.

**Fechamento:** revalidar coleção/documento/fontes atuais na admissão e na resposta; regressão
pública `archive → search` com cache quente/frio, SQLite e backend remoto autorizado.

### A03 — Alta / P0 — idempotência devolve resposta de outra conversa/pedido (reproduzido)

**Esperado:** chave de retry ligada ao usuário, à conversa e ao fingerprint do turno, conforme
[ChatRequest](../../packages/contracts/src/rick_contracts/chat.py).

**Observado e reproduzido:** com `chat_history` ativo, chave `k-final` na conversa `conv-A` com
mensagem `ALPHA` responde `200 / ANSWER_FOR::ALPHA`; a **mesma chave** na conversa `conv-B` com
mensagem `BETA` responde `200`, `conversation_id: conv-A` e `ANSWER_FOR::ALPHA`, sem `409`.
O [replay](../../apps/api/src/services/chat_service.py#L301-L307) ocorre antes de preparar a
conversa e a chave em `chat_history` é apenas
`(tenant, workspace, user, idempotency_key)` — sem `conversation_id` nem fingerprint de payload.

**Impacto:** quebra de integridade request/response e confusão de contexto. Não demonstrado
vazamento entre usuários (a chave já é escopada por sessão).

**Fechamento:** persistir fingerprint canônico + `conversation_id` do turno; repetição idêntica
devolve o mesmo resultado e reuso incompatível responde `409`; cobrir JSON, SSE e os três
stores (in-memory, SQLite, PostgreSQL).

### A04 — Alta / P0 — três rotas fora do registro default-deny de política (novo)

**Esperado:** toda rota `/api|/health|/v1` montada tem entrada em `ROUTE_REGISTRY`, exigido por
`test_registry_covers_all_app_routes`.

**Observado:** `GET /api/v1/audit/operations`, `GET /api/v1/audit/operations/{id}` e
`POST /api/v1/audit/operations/{id}/reconcile` existem em
[knowledge.py](../../apps/api/src/routes/knowledge.py#L38-L54) sem entrada em
[routes/\_\_init\_\_.py](../../apps/api/src/routes/__init__.py#L13). `make api-security`
termina em exit 2 (1 failed / 72 passed).

**Impacto:** as rotas usam `Depends(require_authenticated)`, portanto não são públicas, mas a
granularidade de permissão não está declarada e o gate de segurança está vermelho.

**Fechamento:** registrar as três rotas com `auth`/`permission` explícitos; `make api-security`
verde; teste que falhe ao adicionar rota sem registro.

### A05 — Média / P0 — artefato de build obsoleto quebra `make lint` (novo)

**Observado:** `apps/web/.next-audit-20261006/` (90 MB, não rastreado) gera 406 erros e 5053
avisos do `eslint`. `.gitignore` cobre apenas `**/.next/` e `**/.next-phase3-*/`; o
`eslint.config.mjs` ignora apenas `.next/**`. `npx eslint app components lib middleware.ts
--max-warnings=0` retorna **exit 0**.

**Impacto:** o gate de lint está vermelho por sujeira, não por código; mascara regressões reais.

**Fechamento:** remover o diretório, generalizar os padrões de ignore (`.next*`) em `.gitignore`
e no ignores do eslint; `make lint` verde num checkout limpo.

### A06 — Média / P0 — testes referenciam caminhos legados apagados e quebram a coleta (novo)

**Observado:** `apps/api/tests/test_differential_auth.py` (FileNotFoundError em
`cvg-master-rag-v2/src/services/authorization.py`), `packages/retrieval/tests/test_differential.py`
(`chunker.py`) e `packages/retrieval/tests/test_shadow_quality.py` (`vector_service.py`)
falham na coleta e **interrompem** a execução inteira (`pytest apps/api/tests` retorna exit 2
antes de rodar qualquer teste).

**Fechamento:** remover ou reescrever os testes de paridade legado↔raiz como regressões da
contratualidade atual, mantendo a intenção de verificação.

### A07 — Média / P1 — basenames de teste duplicados entre pacotes (novo)

**Observado:** `pytest packages` falha com `import file mismatch` em
`test_aud03_postgres_live.py` (identity × knowledge) e `test_provider.py` (identity ×
providers) por ausência de `__init__.py`/modo de import único.

**Fechamento:** rodar por pacote no CI (como já faz) **ou** adicionar `__init__.py`/modo
`importlib` com imports irmãos corrigidos; uma única invocação agregada deve funcionar.

### A08 — Alta / P0 — bootstrap não é reproduzível a partir dos locks (novo)

**Observado:** `PYTHONPATH` com 16 entradas existe apenas como `env` do workflow; o Makefile
usa `PYTHON3` do sistema; `.runtime/venvs/cvg` está vazio (`pip list` = 0); `jsonschema` ausente;
`make bootstrap` só prepara o runtime CVG, que não existe mais.

**Impacto:** nenhum checkout novo consegue rodar as suites sem conhecimento implícito.

**Fechamento:** alvo `bootstrap` que instale `requirements/test.lock` num venv raiz e exporte
`PYTHONPATH` via `conftest.py`/`.env`; `make api-test` passa sem export manual.

### A09 — Média / P1 — nenhum type-checker Python configurado (novo)

**Observado:** `make typecheck` declara explicitamente "no Python type checker configured";
167k LOC Python sem `mypy`/`pyright`.

**Fechamento:** introduzir `mypy` (ou `pyright`) em modo gradual por pacote, com baseline
versionada e floor de erros não regressivo no CI.

### A10 — Média / P1 — duas vulnerabilidades HIGH no npm

**Observado:** `sharp <0.35.5` (CVE-2026-96889, librsvg) e `source-map-js 1.0.0–1.2.1`
(GHSA-68fv-2mgg-jv7q), ambas com `npm audit fix` disponível; `pip-audit` do `runtime.lock`
limpo.

**Fechamento:** atualizar e revalidar build/E2E; `npm audit --audit-level=high` com exit 0.

### A11 — Média / P1 — 2 GB de conteúdo não versionado e árvore de 5,1 GB (novo)

**Observado:** `docs/reports/evidence/` 1,86 GB untracked, `.runtime/` 1,3 GB, `artifacts/`
112 MB; apenas **759 arquivos versionados** contra 5,1 GB de árvore. Evidência fora do Git não
é recuperável nem auditable por terceiros.

**Fechamento:** política explícita — versionar sumários/manifests com hash e publicar o resto
como artefato CI, ou mover para armazenamento com proveniência; `git status` limpo.

### A12 — Alta / P0 — baseline não está selada (novo)

**Observado:** 889 mudanças pendentes na árvore auditada. Nenhuma evidência pode ser vinculada
a um candidato identificável.

**Fechamento:** commit ou stash controlado, com HEAD + hash de árvore registrados antes de
qualquer correção.

### A13 — Média / P1 — documentação contradiz o checkout (novo)

**Observado:** README (layout, tabela de comandos, regra de migração), 48 documentos e o INDEX
ainda pressupõem os três legados. 1 link quebrado em `docs/reports/`.

**Fechamento:** 0 links quebrados nos conjuntos primário/plans/reports; README descreve o
estado real; documentos históricos marcados `HISTORICAL`.

### A14 — Alta / P1 — evidência de qualidade de IA insuficiente (novo/confirmado)

**Observado:** `make eval-retrieval-pack` PASSa, mas o pack tem **5 casos sintéticos** e o
corpus adversarial **8 registros**; nenhum provider real executado.

**Fechamento:** campanha com corpus autorizado e representativo, splits, adjudicação e
proveniência — ver `AUD07-19`.

### A15 — Alta / P0 — nenhuma evidência de runtime real (confirmado)

**Observado:** todos os alvos `*-runtime` permanecem `BLOCKED_EXTERNAL`; PostgreSQL, Redis,
Qdrant, object-storage e provider não foram exercitados nesta rodada.

**Fechamento:** golden path end-to-end com serviços reais, identificados e com teardown.

### A16 — Média / P1 — `production_safe` defaulta a `True` sem probe

**Observado:** `ResilientProvider` deriva `production_safe` de `is_test_provider`, e
`health_check()` cai para `readiness_check()` (estado do circuito) quando o provider não
expõe probe — mitigação parcial do achado anterior, mas ainda fail-open para ports customizados.

**Fechamento:** exigir probe ou marca explícita para ports produtivos e falhar fechado quando
ausentes.

### A17 — Média / P1 — skips não classificados

**Observado:** 98 skips em `knowledge`, 18 em `apps/api`, 84 em `infrastructure`, 16 em
`identity`. Não está discriminado quais são obrigatórios para o gate seguinte.

**Fechamento:** inventário de skips com motivo e gate; os obrigatórios para produção executam.

### A18 — Média / P1 — performance, chaos e soak não executados

**Observado:** apenas evidência web local (LCP ≤ 1044 ms, CLS ≤ 0,0022) e benchmarks históricos.

**Fechamento:** `make phase3-performance|chaos|soak` com budgets definidos antes da medição.

### A19 — Alta / P0 — pacote de promoção não pode ser gerado

**Observado:** `make release-evidence` e `make phase3-evidence` dependem de uma cadeia que hoje
está vermelha; a autoridade atual já classifica o estado como `NO-GO`.

**Fechamento:** todos os gates obrigatórios verdes no mesmo candidato identificável, com decisão
Go/No-Go explícita.

### A20 — Média / P2 — lanes raiz de `tests/` são placeholders (novo)

**Observado:** `tests/{contract,integration,regression,security,performance,concurrency,e2e}`
contêm apenas `README.md` (12 arquivos no total; 3 scripts `.mjs` em `phase0`). O README descreve
essas lanes como "root contract, integration, security, regression, and performance lanes".

**Fechamento:** materializar as lanes ou corrigir a descrição para refletir onde as verificações
realmente acontecem.

## 6. Limitações desta rodada

- Não executados: `make test` completo, `make test-integration`, `make test-fast` com ambiente
  consertado, `make ci`, `make release-evidence`, `make triple-aaa-verify`, qualquer alvo
  `*-runtime`, chaos/soak e leitura de leitor de tela.
- O E2E de navegador foi executado uma única vez; a matriz visual não foi revisada
  humanamente.
- Nenhuma análise de dependência transitiva além de `pip-audit` (runtime.lock) e `npm audit`.
- As reproduções A02/A03 usaram o harness in-process do próprio FastAPI; não houve execução
  contra PostgreSQL/Qdrant remotos.
- As notas 1–26 são juízo qualitativo ancorado nos comandos acima, não métricas instrumentadas.

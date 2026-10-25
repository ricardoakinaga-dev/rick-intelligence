# Avaliação independente AVAL24 — documentação × código

**ID:** `AVAL24` · **Data:** 24/10/2026, 22:43 America/Sao_Paulo · **UTC:** 25/10/2026, 01:43
**HEAD:** `dc79ec6f829b5690c6206b6ccba67021a78fcf35` · **Branch:** `archive/local-runtime-20261011` · **Worktree:** limpo, 0 entradas no início da avaliação.
**Veredito:** **78,0/100** de maturidade técnica local — produção **`NO-GO`**.
**Natureza:** avaliação independente read-only, baseada em inspeção do checkout e execução de gates locais. Não é auditoria formal, não é aceite, não altera o controlador e não autoriza release, deploy ou promoção.

**Documentos derivados (propostos):** [plano executivo PRD26](../plans/execplan-prod26-2026-10-24.md), [roadmap PRD26](../roadmap-prod26-2026-10-24.md) e [backlog PRD26](../backlog-prod26-2026-10-24.md).
**Baseline anterior:** [auditoria AUD24](relatorio-auditoria-2026-10-24.md) — 74,7/100 em `48e383c`, com 109 entradas de worktree. A comparação é indicativa: os candidatos e o estado do worktree são diferentes.

## 1. Escopo e método

**Escopo:** API FastAPI, identidade/autorização, worker, packages de ingestão/retrieval/providers/evidence/decision/observabilidade, web Next.js, testes, CI, infraestrutura, migrations e documentação.

**Método:**

1. leitura do `README`, [INDEX](../INDEX.md), arquitetura corrente, ADR-024, relatório AUD24 e evidências M0–M5;
2. inspeção estática conectada de `apps/api` (60 arquivos), `apps/worker` (12), 14 packages implementados, `apps/web`, `infrastructure/` e `docs/`;
3. execução dos gates locais que não exigem serviços externos;
4. leitura das evidências registradas para os gates externos, sem convertê-las em execução desta rodada.

**Fora de escopo executado:** PostgreSQL/Redis/Qdrant/S3 reais, IdP/OIDC, provider pago, restore destrutivo, carga/chaos/soak, Docker runtime, CI remoto, scans de imagem/CVE, assinatura de release e deploy. Esses itens permanecem `NOT_RUN` ou `BLOCKED_EXTERNAL`; nenhum foi contabilizado como `PASS`.

## 2. Inventário do que está construído

| Camada | Entrega verificada | Evidência |
|---|---|---|
| **API** | 61 métodos HTTP em 55 paths: auth/sessão/recuperação, chat SSE, conversas/histórico, documentos/upload, coleções/grants, busca, casos, admin, health, métricas e compatibilidade OpenAI | `apps/api/src/routes/__init__.py`; OpenAPI com 55 paths |
| **Worker** | 12 módulos; fila PostgreSQL com lease/versão, heartbeat, retry, dead-letter, recuperação de crash, reconciliação de auditoria e composição externa | `apps/worker/postgres_jobs.py` (2.023 linhas); gate multi-worker 8/8 |
| **Packages** | 14 domínios implementados (contracts, authorization, identity, jobs, knowledge, ingestion, retrieval, providers, professor, evidence, decision, locking, storage, observability); `audit` e `shared` reservados | ~61 mil linhas Python de produção |
| **Web** | 8 rotas de produto: landing, login, `/app`, documentos/jobs, busca, chat com streaming e citações, casos e admin; Next.js 15 / React 19 | `apps/web/app`; 363 cenários browser |
| **Infra** | 3 Dockerfiles non-root, Compose dev/staging com 16 serviços, Prometheus/Alertmanager/OTel, 11 migrations checksumadas | `infrastructure/`; validações estáticas |
| **Testes** | 1.694 funções de teste; 6.043 testes Python, 265 testes web unitários e 363 cenários E2E | Execuções desta rodada |
| **Documentação** | 267 documentos Markdown pré-existentes (272 após estes artefatos e a evidência da onda 1), 1.145 links válidos no baseline (1.192 após), 24 ADRs, INDEX e política de frescor | `make docs-check` |

O que existe como código, mas **não está provado em runtime real**: composição de produção com IdP/OIDC, provider externo, observabilidade distribuída, restore/DR, performance/chaos/soak e pipeline remoto de release/supply chain.

## 3. Verificações executadas

| Procedimento | Exit | Resultado |
|---|---:|---|
| `make validate` | 0 | Fronteiras, toolchain, Actions, control plane 12/12, quality bar e links |
| pytest núcleo (`apps/api/tests packages apps/worker/tests`) | 0 | **6.043 passed, 137 skipped, 0 failed**, 248 s |
| `make lint` | 0 | Python, fronteiras e ESLint aprovados |
| `make typecheck` | 0 | TypeScript, `compileall` e mypy (14 módulos) sem erros |
| `npm run test:coverage` | 0 | **265 testes**; 91,95% linhas, 80,49% branches |
| `make api-contract` | 0 | OpenAPI com 55 paths |
| `make api-security` | 0 | **182 testes** de rota, negativos e import boundary |
| `make compose-static` | 0 | 16 serviços em dev e 16 em staging |
| `make docs-check` | 0 | 1.145 links no baseline; 1.192 após estes artefatos, 0 erros |
| `make eval-retrieval-pack` | 0 | PASS, mas pack sintético pequeno |
| `make web-build` | 0 | Build de produção aprovado, 10 rotas |
| `make web-e2e` | 0 | **363/363 passed**, 5,0 min; LCP máx. 1.008 ms; CLS 0,0022 |
| `git status --porcelain` | — | 0 entradas; candidato limpo |

Uma execução direta em modo **dev** teve 25 falhas: 15 de LCP sob carga, 7 de duplicidade de efeito do StrictMode e 1 de shell. A lane canônica de produção passou 363/363; a execução dev não foi usada como evidência de produto.

**Artefatos locais ignorados:** `.runtime/avaliacao-core.log`, `.runtime/avaliacao-lint.log`, `.runtime/avaliacao-typecheck.log`, `.runtime/avaliacao-web.log`, `.runtime/avaliacao-webbuild.log`, `.runtime/avaliacao-e2e-prod.log`.

## 4. Notas por item (0–100)

| # | Item | AUD24 | AVAL24 | Δ | Fundamento |
|---:|---|---:|---:|---:|---|
| 1 | Arquitetura e fronteiras | 87 | **87** | 0 | Gate de fronteiras PASS; `apps → packages` respeitado; 14 packages. Custo de revisão alto em `ingestion_service.py` (3.077 linhas) e `postgres_jobs.py` (2.023). |
| 2 | Contratos de API e schemas | 84 | **84** | 0 | 61 métodos/55 paths, OpenAPI PASS e envelope de erro canônico. O web mantém espelho manual de tipos sujeito a drift. |
| 3 | Autenticação e ciclo de sessão | 71 | **80** | +9 | Logout revoga antes da auditoria, reset marca efeito na mesma transação, TTL absoluto, KDF dummy e multi-workspace. IdP/OIDC real e logout OIDC permanecem `NOT_RUN`; OIDC é explicitamente não-logout. |
| 4 | Autorização e isolamento tenant | 84 | **85** | +1 | Escopo server-side, snapshots autoritativos, coleções narrow-only e negativos. Membership de IdP externo não exercitada. |
| 5 | Segurança de entrada e abuso | 70 | **76** | +6 | Limites de corpo, CSRF por nonce, quota antes do KDF e timing dummy. O gate HTTP multi-réplica falhou por divergência de harness; sem carga/abuso representativo. |
| 6 | Auditoria e honestidade | 62 | **80** | +18 | Tabela durável de operações, `UNIQUE(action, request_id)`, reconciler, sink idempotente e `result_indeterminate`. Transação real de reset/outbox ainda não exercitada em PostgreSQL. |
| 7 | Persistência e integridade | 79 | **86** | +7 | 11 migrations checksumadas; gate PostgreSQL real PASS (constraints, índices, 6 planos, fencing, DLQ, replay, crash). Restore de dados não executado. |
| 8 | Ingestão e segurança de documentos | 85 | **86** | +1 | Allowlist, magic bytes, limites de ZIP/texto, parser em processo isolado com deadline e limites de CPU/memória. Corpus hostil externo `NOT_RUN`. |
| 9 | Worker, concorrência e shutdown | 87 | **89** | +2 | Lease/version fencing, heartbeat, dois processos reais e matriz de crash **8/8 PASS**. SIGTERM e shutdown multi-processo ainda não são prova completa. |
| 10 | Providers, streaming e resiliência | 85 | **84** | -1 | Retry/backoff, circuit breaker, budgets, cancelamento e cleanup. Sem provider real nem carga representativa. |
| 11 | Retrieval e proveniência | 84 | **86** | +2 | ACL antes/depois da fusão, proveniência e gate Qdrant real (filtros, alias/rebuild, falha parcial). Corpus sintético pequeno. |
| 12 | Qualidade efetiva de IA/RAG | 44 | **46** | +2 | O harness funciona, mas o pack de 12 casos foi **rejeitado** como representativo; não há corpus clínico, modelo real ou thresholds D04 aprovados. |
| 13 | Frontend e recuperação de UX | 76 | **84** | +8 | 8 rotas, estados de vazio/erro/403, drafts, paginação e recuperação; **363/363 E2E** em produção. O componente de chat ainda tem 1.152 linhas. |
| 14 | Integração frontend ↔ API | 80 | **82** | +2 | Guards de resposta/SSE, `contract-drift.test.ts` e fences de callback. Espelho manual de tipos e mapeamento de erro ainda desigual entre telas. |
| 15 | Acessibilidade | 78 | **75** | -3 | axe sem violações, foco, teclado, `inert` e skip link. AT-SPI foi apenas smoke; não há revisão humana, leitor de tela completo ou WCAG formal. |
| 16 | Testes e força de regressão | 84 | **89** | +5 | 6.043 Python + 265 web + 363 E2E, com 137 skips externos. B01 passou e as regressões AUD24-04/05 têm testes dedicados. |
| 17 | Cobertura e denominadores | 75 | **77** | +2 | API 79,27% statements / 75,65% branch; worker 79,58% / 75,93%; web 91,95% linhas / 80,49% branches. Sem mutation testing. |
| 18 | Tipagem e análise estática | 74 | **75** | +1 | TypeScript integral; mypy cobre apenas 14 módulos, deixando rotas, services e worker fora. |
| 19 | Lint e higiene local | 90 | **90** | 0 | ESLint, `compileall`, whitespace, zero TODO/FIXME no código de produção e worktree limpo. |
| 20 | Build frontend | 88 | **89** | +1 | Build Next.js PASS, 10 rotas e 103–126 kB de first load. Node local 24.20 difere do contrato 22.19. |
| 21 | CI e supply chain | 75 | **74** | -1 | 15 jobs no `quality.yml`, Actions por SHA, locks por hash e workflow com SBOM/cosign. Sem execução remota, scans, assinatura ou SBOM observados. |
| 22 | Documentação e rastreabilidade | 77 | **79** | +2 | 267 documentos no baseline, 1.145 links válidos, 24 ADRs e honestidade explícita de `NO-GO`. 743 citações relativas sem arquivo e documentos atuais defasados em relação à evidência. |
| 23 | Reprodutibilidade do ambiente | 61 | **76** | +15 | Candidato limpo, locks, venv e build/E2E reproduzidos. Node 24 local vs contrato 22, `.runtime/toolchain` ausente, lane VPS bloqueada e dependência de `TMPDIR` curto no Chrome. |
| 24 | Observabilidade e operação local | 73 | **74** | +1 | OTel, métricas, redaction e sinks bounded; coletor distribuído, alertas e burn rate `NOT_RUN`. |
| 25 | Backup, restore e DR | 55 | **55** | 0 | Scripts, checksums, runbook e testes existem; restore integrado `seed → backup → destroy → restore → verify` e RPO/RTO não executados. |
| 26 | Prontidão de produção | 34 | **40** | +6 | Gate fail-closed correto e evidência local forte, mas 80 TODO (48 P0 no total; 26 ainda abertos), gates externos, release packet, CI remoto e aceite humano pendentes. |

**Média simples: 2.028 / 26 = 78,0.** A média não compensa gate obrigatório. Um gate `FAIL`, `NOT_RUN` ou `BLOCKED_EXTERNAL` mantém o candidato em `NO-GO`.

### Escala de referência

| Nota | Interpretação |
|---|---|
| 90–100 | Evidência local muito forte para o recorte, com poucas lacunas |
| 75–89 | Boa implementação, com limitações relevantes |
| 60–74 | Base útil, com fragilidades materiais |
| 40–59 | Parcial; faltam provas ou capacidades importantes |
| 0–39 | Insuficiente para o objetivo, ou bloqueio grave |

## 5. Leitura do resultado

### Forças
- **Fronteiras e arquitetura:** a regra `apps → packages → contracts` é automatizada, não apenas documentada.
- **Worker e fila:** fencing, crash recovery e multi-worker têm prova real em PostgreSQL descartável, não só teste com fake.
- **Ingestão hostil:** allowlist, magic bytes, ZIP pré-analisado, parser isolado e limites explícitos.
- **Identidade e auditoria:** o ADR-024 virou código e testes; B01 e as regressões de chat foram corrigidos.
- **Frontend:** 363 cenários em 375/768/1440, com axe, foco, teclado e performance local.
- **Honestidade documental:** o repositório mantém `NO-GO` explícito e não reivindica `AAA`.

### Lacunas que impedem o `GO`
1. **Qualidade de IA/RAG (46/100):** o pack sintético é tautológico e foi rejeitado como representativo; faltam corpus licenciado, labels de domínio, thresholds D04 e avaliação com modelo real.
2. **Runtime externo incompleto:** IdP/OIDC, provider real, observabilidade distribuída, restore/DR, performance/chaos/soak e supply chain sem prova executada.
3. **Release e CI:** o branch está 14 commits à frente de `origin/archive` e 15 à frente de `origin/main`; o candidato não passou por CI remoto, scans, assinatura ou release packet.
4. **Aceite formal atrasado:** o controlador tem 117 itens — 8 `DONE`, 3 `IN_PROGRESS`, 21 `VERIFY`, 5 `BLOCKED` e 80 `TODO`; dos 48 P0, 26 seguem `TODO`/`IN_PROGRESS`. Há implementação local sem aceite registrado.
5. **Drift documental:** `production-runtime.md` ainda diz que multi-worker/fencing não estão provados; `release-readiness.md` ainda descreve serviços externos como indisponíveis; o roadmap está atrás da evidência M0–M5.
6. **Profundidade de tipos:** mypy restrito a 14 módulos; as superfícies mais críticas de API/worker não estão cobertas.

### Comparação com o AUD24
O salto de **74,7 → 78,0** reflete principalmente:
- auditoria de logout/reset e B01 resolvidos (+18 em auditoria, +9 em autenticação);
- regressões de chat corrigidas e matriz E2E verde (+8 em frontend);
- candidato limpo e toolchain mais reproduzível (+15 em reprodutibilidade);
- gates reais de PostgreSQL/Qdrant/S3 e multi-worker (+7 em persistência, +2 em worker).

As reduções em providers, acessibilidade e CI são de **critério mais estrito**, não regressões funcionais.

## 6. Limitações

- Sem serviços externos, secrets, IdP, provider pago, restore destrutivo, carga/chaos/soak ou CI remoto nesta rodada.
- Os gates de PostgreSQL/Redis/Qdrant/S3 e multi-worker foram lidos da evidência registrada, não reexecutados nesta sessão.
- A nota é julgamento técnico; não substitui gate obrigatório e não autoriza promoção.
- O E2E canônico exige build de produção e `TMPDIR` curto; a execução direta em modo dev não é evidência de produto.
- O `git status` estava limpo no início; este relatório e os documentos derivados adicionam arquivos não rastreados por decisão explícita do solicitante.

## 7. Conclusão

O RICK Intelligence está **substancialmente construído** e tem uma base de engenharia acima da média: arquitetura com fronteiras reais, worker durável com prova de concorrência, ingestão defensiva, API com contratos e testes, frontend com recuperação de estado e documentação rastreável.

O que separa o projeto de produção não é volume de código; é **prova externa, aceite formal e qualidade representativa de RAG**. O caminho mais curto para elevar a nota é: fechar o D04/RAG, executar os gates externos, transformar o candidato local em release commit-bound com CI remoto e quitar o backlog P0 no controlador.

**Nota final: 78,0/100 — boa maturidade local, produção `NO-GO`.**

## 8. Progresso pós-avaliação (24/10/2026)

Após a emissão desta avaliação, a primeira onda local do PRD26 foi executada e
registrada em [onda local 1](<evidence/prd26-2026-10-24/local-wave-1.md>):

- **PRD26-003:** drift documental de `production-runtime.md`, `release-readiness.md`, roadmap/plano AUD24 e INDEX corrigido; `make docs-check` 1.192 links, 0 erros.
- **PRD26-010:** `TMPDIR` curto implementado no Playwright; caminho longo passou 5/5 e a matriz completa de produção passou **363/363** (LCP máx. 916 ms).
- **PRD26-011:** mypy ampliado de 14 para 19 roots, 0/0; `make typecheck` PASS.
- **PRD26-030/041:** PostgreSQL, multi-worker 8/8, Redis, S3/Qdrant e provider fixture passaram em laboratório loopback; `make ci` local também passou. Ver [gates locais](<evidence/prd26-2026-10-24/local-runtime-gates.md>). `production_safe=false`.
- **PRD26-031:** golden path local `upload 202 → worker → published → retrieval 1 evidência → POST /api/v1/chat 200 com citação`, `publication_validation=verified`.
- **PRD26-032:** gate formal de restore `PASS` local, RPO 0,0 s/RTO 3,823 s; `production_safe=false`.
- **File-security:** gate local **PASS 10/10** com parser isolado e casos hostis; `production_safe=false`.
- **Phase 3:** preflight **PASS** e envelopes commit-bound **PASS** para PostgreSQL, multi-worker, Redis, objeto/Qdrant, provider, restore e file-security.

Os três contratos estão em `VERIFY`, não `DONE`. A nota 78,0 não foi recalculada e a decisão de produção continua `NO-GO` até os gates externos e o aceite formal.

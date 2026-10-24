# Auditoria independente — RICK Intelligence (AUD24)

**Data:** 24/10/2026 (America/Sao_Paulo). **Status:** SNAPSHOT observado do checkout; não é nova execução externa nem aceite. **Veredito:** **74,7/100 — produção `NO-GO`.**

**Baseline:** HEAD `48e383c25ca4af32aa7ffe7e2367360ca9742c58`, branch `archive/local-runtime-20261011`, worktree com **109 entradas** (70 arquivos rastreados modificados e 39 não rastreados), incluindo a implementação local AUD15 ainda não commitada. A auditoria foi read-only e preservou esse estado.

**Documentos derivados:** [plano executivo](../plans/execplan-aud24-2026-10-24.md), [roadmap](../roadmap-auditoria-2026-10-24.md) e [backlog](../backlog-auditoria-2026-10-24.md). Eles são `PROPOSTOS` e não adotam tarefas no [controlador](../../.agent/backlog.json).

## 1. Escopo e método

- **Escopo:** API FastAPI, identidade/autorização, worker, packages de ingestão/retrieval/providers/evidence/observabilidade, web Next.js, testes, CI, infraestrutura e documentação.
- **Método:** inspeção estática conectada por amostragem, execução dos gates locais, suíte Python núcleo, cobertura API/worker, suíte web, validação de migrations/compose/contrato/segurança e duas revisões independentes read-only (identidade e web). As revisões não compartilharam contexto com o coordenador.
- **Ambiente:** Python 3.12.3; Node 24.20.0/npm 11.19.0 contra o [contrato](../../toolchain.json) 22.19.0/10.9.3; sandbox `bwrap`. Os testes web exigiram `TMPDIR` dentro do workspace.
- **Fora de escopo executado:** PostgreSQL, Redis, Qdrant, S3, IdP, providers pagos, browser E2E, Docker runtime, CI remoto, scans de CVE/imagem, restore/DR, carga/chaos/soak e deploy. Nada disso foi convertido em PASS.

### Escala

| Nota | Interpretação |
|---|---|
| 90–100 | Evidência local muito forte para o recorte, com poucas lacunas |
| 75–89 | Boa implementação, com limitações relevantes |
| 60–74 | Base útil, com fragilidades materiais |
| 40–59 | Parcial; faltam provas ou capacidades importantes |
| 0–39 | Insuficiente para o objetivo, ou bloqueio grave |

**Média simples: 1.942 / 26 = 74,69 → 74,7.** A média não compensa falha obrigatória. Um gate `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL` ou um defeito P1 aberto mantém o candidato em `NO-GO`.

## 2. Notas por item

| # | Item | Nota | Fundamento / maior limite |
|---:|---|---:|---|
| 1 | Arquitetura e fronteiras | **87** | Gate de fronteiras PASS; `apps → packages` respeitado. Módulos grandes (ex.: `ingestion_service.py`, 3.077 linhas) elevam o custo de revisão. |
| 2 | Contratos de API e schemas | **84** | 61 rotas, OpenAPI PASS, envelopes estáveis. O web mantém espelho manual de contratos sujeito a drift. |
| 3 | Autenticação e ciclo de sessão | **71** | Offload, revogação nativa e CSRF por nonce funcionam. Logout depende da auditoria; OIDC não revoga; não há expiração absoluta. |
| 4 | Autorização e isolamento tenant | **84** | Escopo server-side, permissões autoritativas e negativos locais. Sem IdP/PostgreSQL distribuídos reais. |
| 5 | Segurança de entrada e abuso | **70** | Limites de corpo, CSRF e quota antes de KDF. Enumeração por timing no login; sem prova de carga ou limiter distribuído. |
| 6 | Auditoria e honestidade | **62** | Reset não audita; `access_denied` é engolido; `completed` tardio após 503; `requested` órfão sem reconciliador. |
| 7 | Persistência e integridade | **79** | Stores, lineage, transações e 10 migrations checksumadas. PostgreSQL/S3/Qdrant reais `NOT_RUN`. |
| 8 | Ingestão e segurança de documentos | **85** | Allowlist, magic bytes, limites de ZIP/texto, parser isolado. Corpus hostil externo não executado. |
| 9 | Worker, concorrência e shutdown | **87** | Lease/version fencing, claims em voo, drain e corridas testadas. Sem SIGTERM/multiprocesso real. |
| 10 | Providers, streaming e resiliência | **85** | Budgets, circuit breaker, cancelamento e cleanup. Sem provider real nem carga representativa. |
| 11 | Retrieval e proveniência | **84** | Escopo antes/depois da fusão, ACL negativa e proveniência. Corpus sintético pequeno. |
| 12 | Qualidade efetiva de IA/RAG | **44** | Pack offline de 2 positivos/3 negativos; não mede modelo real, corpus representativo ou qualidade clínica. |
| 13 | Frontend e recuperação de UX | **76** | Drafts, paginação e jobs evoluíram; duas regressões silenciosas no chat perdem a ação do usuário. |
| 14 | Integração frontend ↔ API | **80** | Guardas de resposta/SSE e fences de callback; mapeamento de erro inconsistente entre telas. |
| 15 | Acessibilidade | **78** | Foco, diálogo, `inert`, skip link e axe em testes. Sem leitor de tela/WCAG global. |
| 16 | Testes e força de regressão | **84** | 6.018 PASS no núcleo, 258 web, 84 specs E2E; 1 falha conhecida e lane VPS sem executor válido. |
| 17 | Cobertura e denominadores | **75** | API 79,42%, worker 80,11%, web 90,65% linhas — web em 19 arquivos; Python sem branch coverage. |
| 18 | Tipagem e análise estática | **74** | TypeScript integral; mypy restrito a 10 módulos, sem API/worker/stores. |
| 19 | Lint e higiene local | **90** | ESLint, `compileall`, whitespace e zero TODO/FIXME no código de produção. |
| 20 | Build frontend | **88** | Typecheck atual PASS e build de produção aprovado em evidência anterior; build não reexecutado nesta rodada. |
| 21 | CI e supply chain | **75** | 14 lanes, Actions por SHA e locks por hash. Sem execução remota/scans/SBOM/assinatura; lane CONTRACT não está verde. |
| 22 | Documentação e rastreabilidade | **77** | 1.028 links válidos e NO-GO explícito; três documentos atuais divergem do código e 742 citações não têm arquivo. |
| 23 | Reprodutibilidade do ambiente | **61** | Python canônico funciona; Node/npm divergem do contrato, `TMPDIR` quebra a suíte web e a lane VPS não tem executor compatível. |
| 24 | Observabilidade e operação local | **73** | Redação, sinks bounded e OTel corrigido. Telemetria distribuída e alertas `NOT_RUN`. |
| 25 | Backup, restore e DR | **55** | Ferramentas de checksum e runbook existem; restore integrado, RPO/RTO e recuperação real `NOT_RUN`. |
| 26 | Prontidão de produção | **34** | Gate fail-closed correto, mas 80 itens TODO, worktree sujo, B01 aberto e obrigações externas sem prova. |

## 3. Verificações executadas

| Procedimento | Exit | Resultado |
|---|---:|---|
| `make validate` | 0 | Fronteiras, toolchain, Actions, control plane 12/12, quality bar e 1.028 links/0 erros; aviso de 742 citações relativas. |
| pytest núcleo | **1** | 6.018 passed, 1 failed, 137 skipped, 201,5 s. Falha: `test_logout_completion_must_not_persist_after_http_timeout` (B01). |
| `make api-coverage` | **2** | 79,42% statements; floor 75 atingido; falha pelo B01. |
| `make worker-coverage` | 0 | 80,11%; floor 74. |
| `npm run lint` / `typecheck` | 0 / 0 | ESLint e TypeScript aprovados. |
| `npm run test:coverage` | 0 | 258 testes; 90,65% linhas, 86,3% statements, 79,98% branches, 87,33% funções. |
| `make typecheck` | 0 | TS + `compileall` + mypy (10 módulos) sem erros. |
| `make lint` | 0 | Python/boundaries/lint web aprovados. |
| `make ops-static` | 0 | 10 migrations com checksum; execução `NOT_RUN`; instalações hash-locked. |
| `make compose-static` | 0 | 16 serviços em dev e 16 em staging; runtime não iniciado. |
| `make api-contract` / `api-security` | 0 / 0 | OpenAPI e 181 testes de segurança/rota. |
| `make eval-retrieval-pack` | 0 | PASS offline, apenas 2 casos sintéticos. |
| Lane VPS | 1 | 277 failed, 427 passed, 1 skipped; barreira ambiental, não 277 defeitos independentes. |
| `git diff --check` | 0 | Sem erros de whitespace. |

**Artefatos locais (ignorados pelo Git):** `.runtime/audit-20261024-*.log`.

## 4. Achados AUD24

### P1 — antes de candidatura a produção

#### AUD24-01 — Reset pode efetivar a troca e responder 503, sem auditoria

A rota consome o token, troca a credencial e revoga sessões dentro da transação; o `ensure_identity_operation_current()` posterior ao `consume` pode estourar o deadline e o offload não cancela a thread, que conclui e commita. O cliente recebe 503, o token já foi consumido e não há evento de auditoria de reset em [auth.py](../../apps/api/src/routes/auth.py#L353-L391), [identity_offload.py](../../apps/api/src/services/identity_offload.py#L224-L233) e [postgres_identity.py](../../apps/api/src/services/postgres_identity.py#L891-L935).

- **Impacto:** usuário bloqueado sem retry; ausência de rastro forense em troca pública de credencial.
- **Confiança:** alta (estática; não reproduzida em runtime).
- **Fechamento:** contrato de resultado indeterminado com `request_id`, auditoria idempotente da efetivação e teste que mate o worker após o commit.

#### AUD24-02 — Logout refém da disponibilidade da auditoria

O `emit_required(status="requested")` ocorre antes da revogação em [auth.py](../../apps/api/src/routes/auth.py#L288-L291). Se o sink estiver parcialmente degradado, a sessão continua válida e o usuário não consegue revogar; o teste fixa esse comportamento em [test_logout_revocation_failure.py](../../apps/api/tests/test_logout_revocation_failure.py#L67-L87).

- **Impacto:** perda de um controle de segurança durante indisponibilidade parcial do sink.
- **Fechamento:** revogar primeiro; falha de auditoria vira 503 “efeito aplicado, confirmação pendente”, ou outbox transacional.

#### AUD24-03 — B01: `completed` após HTTP 503, sem estado terminal nem idempotência

O teste aberto em [test_aud15_identity.py](../../apps/api/tests/test_aud15_identity.py#L508-L540) bloqueia o sink e comprova a escrita tardia. A tabela não tem `UNIQUE(action, request_id, status)` nem reconciliador; sobram `requested` órfãos e pares duplicados — [postgres_audit.py](../../apps/api/src/services/postgres_audit.py#L160-L176), [0002_product_schema.sql](../../infrastructure/migrations/0002_product_schema.sql#L203-L216). O lane CONTRACT executa `make api-coverage` ([quality.yml](../../.github/workflows/quality.yml#L146-L148)), que hoje retorna exit 2.

- **Impacto:** trilha ambígua e CI de contrato vermelho. O “CI exit 0” de 15/10 não cobre esse lane.
- **Fechamento:** outbox idempotente com reconciliador **ou** fence prepare/commit/abort, ratificado como decisão material; o teste atual não pode ser removido nem afrouxado.

#### AUD24-04 — Chat silenciosamente morto após “Nova conversa” durante abertura

`startNewConversation` aborta o controller, mas não zera `detailAbortRef` ([chat-workspace.tsx](../../apps/web/components/chat/chat-workspace.tsx#L436-L441)); o `finally` antigo não limpa porque a geração mudou ([L507](../../apps/web/components/chat/chat-workspace.tsx#L507)). O guard de envio ([L717](../../apps/web/components/chat/chat-workspace.tsx#L717)) e o de paginação ([L549](../../apps/web/components/chat/chat-workspace.tsx#L549)) retornam sempre.

- **Impacto:** perda silenciosa de perguntas; recuperação só abrindo outra conversa ou recarregando.
- **Confiança:** alta (regressão introduzida na remediação AUD15).
- **Fechamento:** limpar o ref e teste “abrir conversa em voo → Nova conversa → enviar”.

#### AUD24-05 — Aborto externo durante abertura de conversa deixa spinner permanente

Quando a revalidação de sessão aborta o lease, `openConversation` retorna no ramo `isAbortError` sem atualizar estado ([L496-L497](../../apps/web/components/chat/chat-workspace.tsx#L496-L497)); o painel fica em “Abrindo conversa…” com composer bloqueado e sem retry ([L1041](../../apps/web/components/chat/chat-workspace.tsx#L1041)).

- **Impacto:** alternar de aba durante o carregamento inutiliza o chat até outra navegação.
- **Fechamento:** aborto externo retorna a `ready` com mensagem e retry; teste focus/visibility durante GET.

#### AUD24-06 — Worktree sujo impede integridade de release

Há 70 arquivos modificados e 39 não rastreados (5.384 inserções) sobre `48e383c`. O gate de release exige checkout limpo ([release_integrity.py](../../scripts/state_of_art/release_integrity.py#L621)).

- **Impacto:** nenhuma evidência de release commit-bound é válida no estado atual.
- **Fechamento:** revisar/commitar o candidato, gerar fingerprint e rodar os lanes sobre checkout limpo.

### P2 — próxima rodada de robustez

| ID | Achado | Evidência | Fechamento mínimo |
|---|---|---|---|
| AUD24-07 | OIDC declara `production_safe=True` sem porta de logout | [oidc.py](../../packages/identity/src/rick_identity/oidc.py#L235-L341) | Exigir revogação/broker na composição ou declarar “sem logout” explicitamente, sem manter cookie |
| AUD24-08 | Enumeração de contas por timing no login; multi-workspace não loga | [provider.py](../../packages/identity/src/rick_identity/provider.py#L96-L102), [postgres.py](../../packages/identity/src/rick_identity/postgres.py#L316-L327) | Hash dummy de custo fixo; resolução/ seletor de workspace |
| AUD24-09 | `access_denied` é auditado, mas falha é descartada | [dependencies/identity.py](../../apps/api/src/dependencies/identity.py#L97-L116) | Log/telemetria própria e orçamento separado; nunca silencioso |
| AUD24-10 | Sessão sem vida absoluta; `max_age` 8h hardcoded | [postgres.py](../../packages/identity/src/rick_identity/postgres.py#L801-L808), [auth.py](../../apps/api/src/routes/auth.py#L212-L221) | `absolute_expires_at` e TTL configurável |
| AUD24-11 | 403 de casos vira outage; documentos sem dedupe/cursor; corrida de auto-abertura; composer offline | [case-workspace.tsx](../../apps/web/components/cases/case-workspace.tsx#L23-L28), [page.tsx](../../apps/web/app/app/documents/page.tsx#L153-L166), [chat-workspace.tsx](../../apps/web/components/chat/chat-workspace.tsx#L529-L534) | Mapeamento 403/abort/outage; guards de paginação; decisão de UX offline |
| AUD24-12 | Documentação e ambiente divergem do código | [api-security.md](../architecture/api-security.md#L44-L46), [canonical-web.md](../architecture/canonical-web.md#L48-L53), [README](../../README.md#L28-L31) | Atualizar docs; Node 22/npm 10; `TMPDIR` portátil; lane VPS representativa |

## 5. Inventário do que está construído

| Camada | Entrega | Status |
|---|---|---|
| API | 61 rotas: auth/sessão, chat SSE, conversas, documentos, coleções, busca, casos, admin, health, compatibilidade OpenAI | Implementado localmente |
| Worker | Fila PostgreSQL com lease/versão, claims, retry, DLQ, shutdown e composição de produção | Implementado; runtime externo `NOT_RUN` |
| Packages | 14 domínios (contracts, authorization, identity, jobs, knowledge, ingestion, retrieval, providers, professor, evidence, decision, locking, storage, observability) | Implementado |
| Web | Login, `/app`, documentos/upload/jobs, busca, chat com streaming/citações, casos e admin; 9 páginas | Implementado |
| Infra | 3 Dockerfiles non-root, Compose dev/staging com 16 serviços, monitoramento e tooling VPS | Estático; runtime `NOT_RUN` |
| Migrations | 10 migrations + repair, checksums validados | Aplicação `NOT_RUN` |
| Testes | 6.156 coletados no núcleo, 258 web, 84 specs E2E | 6.018 PASS, 1 FAIL; E2E não reexecutado |
| Documentação | 251 Markdown, 1.028 links válidos | Ampla, com pontos desatualizados |

**Backlog canônico:** 117 itens — **8 DONE, 3 IN_PROGRESS, 21 VERIFY, 5 BLOCKED, 80 TODO**. “Implementado” não equivale a “aceito”.

## 6. Limitações

- Sem serviços externos, secrets, banco real, IdP, provider pago, browser E2E, Docker runtime ou CI remoto.
- AUD24-01/02/03/07/08/10 são achados de inspeção estática; alguns têm teste existente, mas não foram reproduzidos em runtime nesta rodada.
- A lane VPS não foi validada por barreira de ownership/namespace; 277 falhas não equivalem a 277 bugs.
- O E2E de 363 cenários é evidência histórica do candidato 760/6d056, não reexecução desta rodada.
- As notas são julgamento técnico; a média não certifica produto nem autoriza promoção.

## 7. Implicações

O caminho mais curto para elevar a nota não é adicionar funcionalidade: é resolver o contrato de auditoria de logout/reset, corrigir as regressões de chat e transformar o candidato sujo em um release commit-bound com os lanes externos executados. O [plano executivo](../plans/execplan-aud24-2026-10-24.md) converte esses achados em workstreams, o [roadmap](../roadmap-auditoria-2026-10-24.md) em oito marcos e o [backlog](../backlog-auditoria-2026-10-24.md) em 29 contratos novos, sem duplicar as obrigações PROD12.

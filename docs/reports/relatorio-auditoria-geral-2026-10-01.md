# Relatório de reauditoria local — RICK Intelligence

**Data:** 2026-10-01. **Escopo:** checkout local `/home/ricardo/rick-intelligence`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, árvore `b205d9cbd1dcb719b4a8c2f5dcd8ac68009f326f`, branch `main` sincronizada com `origin/main`, worktree compartilhado e sujo (**2.913 entradas** na validação final; eram 2.910 após gravar a baseline e antes destes documentos).

**Método:** leitura de código conectado e documentação normativa/atual; comparação com relatórios anteriores; regressões locais reproduzíveis e checks estáticos. Sem deploy, push, provider real, alteração de estado canônico ou operação destrutiva. A reavaliação de notas foi feita pelo auditor desta rodada; não é uma revisão independente. O corte das notas antecede a edição editorial de índice/roadmap/backlog descrita abaixo; essas edições não foram reavaliadas como aumento de nota.

**Relatório-base preservado:** [`relatorio-auditoria-local-2026-10-01-base.md`](relatorio-auditoria-local-2026-10-01-base.md). **Auditoria anterior mais recente:** [`relatorio-auditoria-geral-2026-09-29.md`](relatorio-auditoria-geral-2026-09-29.md), 80/100 antes das correções RA29 registradas depois dela.

## Parecer executivo

**Nota técnica local reavaliada: 83,3/100** (2.167/2.600; média simples de 26 áreas). **Classificação:** `STATE_OF_ART_CANDIDATE`. **Promoção:** **NO-GO**.

As correções locais posteriores à auditoria de 29/09 fortalecem isolamento do schema, administração/outbox, avaliação sintética, UX focada e cobertura. O aumento da nota não fecha o gate de promoção. Faltam observações atuais do runtime integrado, campanha RAG autorizada, recuperação/capacidade, supply chain de imagens, CI same-SHA e revisão/decisão de release do candidato exato.

Esta é uma nota de engenharia, não o score oficial da barra Triplo AAA e não um percentual de conclusão. Uma nota não compensa um gate obrigatório ausente, falho ou externo.

## Notas por item — 0–100

| # | Item analisado | Nota | Fundamentação e principal limite |
|---:|---|---:|---|
| 1 | Arquitetura e separação de responsabilidades | **88** | `apps → packages → contracts`, composição explícita e legacy preservado; operação conjunta e processo de release ainda sem prova. |
| 2 | Documentação e aderência ao estado atual | **62** | No corte da nota, o índice/roadmap apontavam para 72/100; este pacote agora os reconcilia. O README ainda apresenta versões históricas como toolchain atual e nem todos os snapshots de evidência foram lidos individualmente. |
| 3 | Identidade e sessões | **83** | Snapshots autoritativos, PBKDF2 e lifecycle testado; login recebe tenant, mas não workspace, e o adapter escolhe uma membership com `LIMIT 1`. |
| 4 | Autorização e isolamento | **84** | Escopo validado em rotas/adapters e novas constraints compostas; falta prova de isolamento full-stack em todos os stores e réplicas. |
| 5 | Kernel HTTP e controles defensivos | **91** | Limites, erros redigidos, CSRF, rate limits e JSON estrito têm regressões; gateway e deployment reais não foram exercitados. |
| 6 | Contratos e compatibilidade | **87** | Contratos tipados, OpenAPI, SSE e replay testados; clientes externos reais não foram exercitados. |
| 7 | Knowledge: documentos, versões e proveniência | **91** | IDs e lineage consistentes; migration 0008 acrescenta constraints cross-scope, mas restore e store de produção não foram provados. |
| 8 | Ingestão e reindexação | **88** | Pipeline bounded, publicação protegida e retry binário cobertos; falha intermitente de telemetria em execução paralela permanece sem encerramento demonstrado. |
| 9 | Retrieval e busca híbrida | **91** | O caminho HTTP usa dense+sparse e filtro ACL; Qdrant/corpus integrados e freshness continuam sem campanha atual. |
| 10 | Evidence: fontes e citações | **89** | Evidence é server-issued e revalidada antes de publicar; suporte semântico/entailment não é medido pelo pack sintético. |
| 11 | Decision: responder, abster e escalar | **82** | Política e ações estão integradas; risco clínico exige revisão humana e D04/limiares de domínio permanecem sem aprovação. |
| 12 | Professor e geração fundamentada | **90** | Citações, budgets, leases e deltas provisórios são testados; nenhuma execução de modelo/corpus autorizados nesta reauditoria. |
| 13 | Integração com providers | **84** | Cliente tipado, retries e erros locais; endpoint, orçamento, qualidade e cancelamento live não foram executados. |
| 14 | Avaliação da qualidade RAG | **81** | `rec22-local-v2` passa com 2 positivos/3 negativos; campanha permanece `NOT_RUN`/`BLOCKED`, muito aquém da amostra e representatividade requeridas. |
| 15 | Chat, histórico e apresentação das evidências | **84** | Persistência/replay e contratos locais têm cobertura; resposta útil com provider e stores reais não foi demonstrada ponta-a-ponta. |
| 16 | Documentos, busca e ingestão pela interface | **89** | Upload/retry/erro de coleções têm regressões e revisão visual focada; a matriz completa não foi repetida após os últimos ajustes. |
| 17 | Administração, auditoria e casos | **88** | UI de usuários/sessões e outbox/reconciliador existem; testes PostgreSQL são locais e Q17-17.A segue `VERIFY`. |
| 18 | Containers e composição | **80** | Compose estático renderiza 14 serviços em cada topologia e há hardening; imagens/startup/readiness/teardown do stack não foram executados. |
| 19 | Jobs, PostgreSQL e migrações | **89** | Fila e compatibilidade 0004/0005 têm testes PostgreSQL descartáveis históricos; inventário D02 de bancos instalados continua aberto. |
| 20 | Worker e ciclo de vida | **90** | SIGTERM em subprocesso e 117 testes worker passam; Worker A/B com serviços externos não foi exercitado. |
| 21 | Redis e coordenação distribuída | **78** | Protocolos e adapters owner-safe têm testes locais; Redis real, failover e bucket compartilhado por duas APIs não foram executados. |
| 22 | Storage e inicialização persistente | **84** | Transporte S3, checksum e escopo têm testes; S3/MinIO live, retenção e restore permanecem abertos. |
| 23 | Observabilidade e SLO | **84** | Redaction, sink bounded, métricas e shutdown do worker foram exercitados localmente; collector, alertas e SLO distribuído não. |
| 24 | Recuperação, capacidade e tolerância a falhas | **52** | Runbooks/helpers existem; nenhum RPO/RTO, restore de serviços, carga, chaos ou soak atual foi observado. |
| 25 | CI e promoção de release | **74** | Workflow fail-closed, actions pinadas e release manifest existem; GitHub Actions same-SHA não rodou e há lacunas de dependências/testes na pipeline. |
| 26 | Qualidade global dos testes | **84** | Matriz local ampla e cobertura com pisos registrados; 427 avisos de API, intermitência conhecida e falta de E2E integrado reduzem confiança. |

## Verificações executadas nesta reauditoria

| Comando/conjunto | Resultado | Limite |
|---|---|---|
| `PYTHONDONTWRITEBYTECODE=1 make api16-root` | **755 passaram**, 427 avisos | API hermética, sem serviços externos. |
| `make api16-domain` | **281 passaram, 5 ignorados** | Casos opt-in do Qdrant não equivalem a runtime integrado. |
| `make api16-worker` | **117 passaram**, 7 avisos | Não prova Worker A/B distribuídos. |
| Suites de autorização, identidade, evidence, decision, observabilidade, jobs e storage | **149 passaram** | Adapters/testes locais; contagens sobrepõem-se às suites acima. |
| `make eval-retrieval-pack` | **PASS** | Somente observations sintéticas; provider `NOT_RUN`, campanha produto `BLOCKED`. |
| `make validate` | **PASS**, 10/10 checks | Relata 30 históricos, 35 backlog items, 406 eventos, 408 verificações, 28 gates; worktree DIRTY (2.913 entradas na validação final). |
| `make compose-static` | **PASS**, 14 serviços dev + 14 staging | Nenhum serviço foi iniciado. |
| `make security-adversarial` | **PASS**, 8 registros/8 categorias | Valida corpus sintético; não é pentest. |
| `python3 infrastructure/scripts/migrate.py infrastructure/migrations --check` | **PASS**, 8 migrations/checksums | `execution: NOT_RUN`. |
| `test_composite_scope_migration_static.py` | **2 passaram** | Teste estático, não valida PostgreSQL live. |
| `git diff --check` | **PASS** | A árvore continua suja. |

`make lint` e `make typecheck` passaram em verificações locais anteriores desta mesma sessão; `make typecheck` Python executa compilação, não um type checker Python. Build web de produção também consta como PASS; a saída total de `make build` ficou incompleta e não é declarada integralmente PASS. As contagens de teste não são somadas porque se sobrepõem.

## Achados e lacunas que orientam a próxima rodada

### Auditoria-01 — Índice e documentos “atuais” estão defasados

**Confiança alta; severidade documental média.** No começo desta reauditoria, `docs/INDEX.md` apontava como current a nota 72/100 e o relatório de 07/09; `roadmap-auditoria-atual.md` e `backlog-auditoria-atual.md` ainda eram RA72. Este pacote reconciliou índice e referências e preservou os arquivos antigos como históricos. **Pendente:** o README informa Qdrant 1.7.4/Redis 7.0.15 como versão raiz, enquanto `toolchain.json` separa pins históricos e define Qdrant 1.12.5/Redis 7.4 para o laboratório atual; AUD26-07 mantém essa correção pendente.

### Auditoria-02 — Login não seleciona membership de workspace

**Confiança alta na implementação, média no impacto prático.** `LoginRequest` em `apps/api/src/routes/auth.py` recebe tenant, não workspace. `IdentityProviderImpl.login()` usa `get_by_email_for_tenant`; `PostgresUserStore.get_by_email_for_tenant()` filtra tenant e encerra com `LIMIT 1`, sem exigir workspace nem tratar múltiplas memberships. O schema permite memberships distintas por `(tenant_id, user_id, workspace_id)`. Uma conta em mais de um workspace pode iniciar uma sessão em membership não escolhida explicitamente. Definir escolha explícita ou rejeitar ambiguidade e testar roles/grants diferentes por workspace.

### Auditoria-03 — Colisão de nome de constraint na migration 0008

**Achado estático condicional; não reproduzido em PostgreSQL.** Os blocos que criam constraints em `infrastructure/migrations/0008_composite_scope_constraints.sql` ignoram `duplicate_object`. Se uma constraint homônima já existir com definição divergente, a migration não confirma que ela impõe o mesmo escopo. Os testes cobrem dados incompatíveis e relações inválidas, não essa colisão de schema. Consultar a definição em `pg_constraint` após duplicata ou falhar fechada; acrescentar teste known-bad.

### Auditoria-04 — Cobertura da pipeline CI não corresponde a todas as suites

**Confiança alta por inspeção estática; efeito no runner CI não executado.** `.github/workflows/quality.yml` não invoca explicitamente `make jobs-test`, `make storage-test` ou `infrastructure/scripts/tests`; a lane RAG-EVAL instala versões de `pytest`, `pydantic` e `httpx` diretamente sem `--require-hashes`. A execução local das suites não prova que esses mesmos limites estão protegidos no CI.

### Auditoria-05 — Flakiness e cobertura web final

O relatório de 29/09 registrou uma falha `worker.ingestion.published` em execução paralela que passou isoladamente; a causa não está fechada por uma matriz repetida. Para web, o pack completo de 321 casos antecede os últimos ajustes CSS; a versão final tem prova focada 27/27 e revisão independente de uma única fatia visual, não uma matriz full app pós-ajustes.

## Bloqueadores externos e decisão

Não foi iniciado Docker/Compose ou outro serviço nesta reauditoria. Não foram executados provider real, corpus aprovado, identidade OIDC real, API+worker+PostgreSQL+Redis+Qdrant+S3 integrado, restore, RPO/RTO, carga, chaos, soak, alert routing ou promoção. O plano `.agent/` conserva `Q17-01.A:VERIFY-Q17-19A-DEPLOYED-INVENTORY` como ação ativa dependente de D02; não consultei banco instalado nem alterei ledgers.

**Veredito:** `STATE_OF_ART_CANDIDATE / NO-GO`. O worktree não é limpo; as evidências operacionais e a autoridade de promoção exigidas continuam pendentes. A média 83,3 não altera essa decisão.

## Limitações da leitura documental

Foram lidos os documentos normativos/atuais, ADRs, prompts, planos, relatórios de auditoria/implementação mais recentes, controles, manifests de evidência-chave e capturas mobile/tablet/desktop do caso de erro de coleções. `docs/reports/evidence/` contém muitos snapshots históricos, logs e imagens; nem todos foram abertos individualmente. A documentação corrente e os manifests foram usados como índice desses históricos, sem promovê-los a prova atual.

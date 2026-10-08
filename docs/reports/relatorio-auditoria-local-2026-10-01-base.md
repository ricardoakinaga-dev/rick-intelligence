# Auditoria técnica local — baseline anterior

**Registro:** 2026-10-01. **Origem:** relatório apresentado no chat antes da reauditoria solicitada. **Escopo:** repositório `/home/ricardo/rick-intelligence`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, worktree compartilhado e sujo.

> Este documento preserva o relatório anterior como baseline histórica desta rodada. A reauditoria posterior está em [`relatorio-auditoria-geral-2026-10-01.md`](relatorio-auditoria-geral-2026-10-01.md); roadmap e backlog desta rodada estão nos documentos homônimos em `docs/`.

## Parecer executivo da baseline

**Nota técnica reavaliada:** 83,3/100, média simples de 26 áreas. **Classificação:** `STATE_OF_ART_CANDIDATE`. **Promoção:** `NO-GO`.

A nota era uma reavaliação técnica local, não certificação, percentual de conclusão nem score oficial de promoção. O worktree tinha 2.909 entradas sujas; HEAD estava sincronizado com `origin/main`, mas não era candidato limpo de release.

## Scorecard da baseline — 26 áreas

| # | Área | Nota | Evidência e principal limite |
|---:|---|---:|---|
| 1 | Arquitetura e separação de responsabilidades | **88** | Fronteiras entre apps e packages, composição explícita e preservação dos legados; integração distribuída ainda sem prova. |
| 2 | Documentação e aderência ao estado atual | **62** | Limites honestos, mas índice/roadmap “atuais” ainda indicam 72/100 e README apresenta versões históricas como toolchain atual. |
| 3 | Identidade e sessões | **83** | Snapshots autoritativos, PBKDF2 e testes de persistência; login não escolhe workspace e a consulta por tenant usa `LIMIT 1` apesar de memberships por workspace. |
| 4 | Autorização e isolamento | **84** | Escopo validado nas rotas e adapters; constraints compostas existem, mas o isolamento integrado em todos os serviços não foi provado. |
| 5 | Kernel HTTP e controles defensivos | **91** | Limites, erros redigidos, CSRF, rate limits, JSON estrito e regressões locais; deployment/gateway real não auditado. |
| 6 | Contratos e compatibilidade | **87** | Contratos tipados, OpenAPI e SSE/replay cobertos; consumidores externos reais não exercitados. |
| 7 | Knowledge, versões e proveniência | **91** | Lineage e IDs estáveis; migration 0008 acrescenta constraints compostas; produção/restore não demonstrados. |
| 8 | Ingestão e reindexação | **88** | Pipeline bounded, retry binário e validação de publicação; uma intermitência de evento em execução paralela permanece sem encerramento. |
| 9 | Retrieval e busca híbrida | **91** | Busca HTTP dense+sparse conectada e testes de adapter; corpus, freshness e runtime Qdrant integrado não demonstrados. |
| 10 | Evidence, fontes e citações | **89** | Evidências server-issued e revalidadas; faithfulness depende de anotação, não de entailment semântico. |
| 11 | Decision: responder, abster e escalar | **82** | Política e ações integradas; decisões clínicas dependem de D04 e seguem conservadoras. |
| 12 | Professor e geração fundamentada | **90** | Limites de tool calls, leases, citações e streaming provisório; falta provider/modelo real e corpus aprovado. |
| 13 | Integração com providers | **84** | Contrato resiliente e testes locais; chamadas live, budgets e qualidade permanecem `NOT_RUN`. |
| 14 | Avaliação da qualidade RAG | **81** | Pack sintético v2 passa; tem dois casos positivos e três negativos; campanha real segue `NOT_RUN`/`BLOCKED`. |
| 15 | Chat, histórico e apresentação de evidências | **84** | Histórico, replay e metadados têm regressões locais; experiência integrada com modelo real não provada. |
| 16 | Interface: documentos, busca e ingestão | **89** | Fatia de falha de coleções passou 27 testes e revisão visual independente; matriz completa não repetida após ajustes finais. |
| 17 | Administração, auditoria e casos | **88** | UI de gestão existe; transação/outbox e consumidor têm testes PostgreSQL locais; composição externa permanece aberta. |
| 18 | Containers e composição | **80** | Compose estático valida 14 serviços por ambiente; imagens e startup/teardown reais não observados. |
| 19 | Jobs, PostgreSQL e migrações | **89** | Fila e upgrades checksum-safe têm evidência PostgreSQL local; inventário de instalações aplicadas segue pendente. |
| 20 | Worker e ciclo de vida | **90** | SIGTERM por subprocesso e suite worker passaram; dois workers em composição real seguem sem prova. |
| 21 | Redis e coordenação distribuída | **78** | Adapters e semântica owner-safe têm testes locais; Redis live e duas réplicas não executados. |
| 22 | Storage e inicialização persistente | **84** | Transporte S3, checksum e escopo têm cobertura local; object store live e restore não demonstrados. |
| 23 | Observabilidade e SLO | **84** | Sink bounded, redaction, métricas e shutdown local; collector, alertas e traces distribuídos não executados. |
| 24 | Recuperação, capacidade e tolerância a falhas | **52** | Runbooks e helpers existem; RPO/RTO, restore real, carga, chaos e soak permanecem `NOT_RUN`/`BLOCKED_EXTERNAL`. |
| 25 | CI e promoção de release | **74** | Workflows fail-closed e actions pinadas; CI same-SHA não observada e há lacunas de cobertura/instalação. |
| 26 | Qualidade global dos testes | **84** | Suítes locais amplas e pisos de cobertura registrados; avisos, intermitência e lacunas de E2E/runtime reduzem a confiança. |

**Média simples:** 2.167 ÷ 26 = **83,35**, arredondada para **83,3/100**. A média não substitui nem supera gates obrigatórios.

## Verificações da baseline

| Verificação | Resultado registrado |
|---|---|
| `make api16-root` | 755 passaram, 427 avisos |
| `make api16-domain` | 281 passaram, 5 ignorados |
| `make api16-worker` | 117 passaram, 7 avisos |
| Suítes de autorização, identidade, evidence, decision, observabilidade, jobs e storage | 149 passaram |
| `make eval-retrieval-pack` | PASS somente no pack sintético v2; provider `NOT_RUN` |
| `make validate` | PASS, 10/10 checks; worktree DIRTY (2.909 entradas) |
| `make compose-static` | PASS, 14 serviços em cada composição; nenhum iniciado |
| `make security-adversarial` | PASS, 8 registros sintéticos em 8 categorias |
| `infrastructure/scripts/migrate.py ... --check` | PASS, checksums das migrations; execução reportada como NOT_RUN nesta baseline |
| `test_composite_scope_migration_static.py` | 2 passaram |
| `git diff --check` | PASS |

As suítes se sobrepõem e não devem ser somadas como testes distintos. Não houve, nesta baseline, execução de Docker/Compose integrado, CI GitHub same-SHA, provider, corpus real, restore, RPO/RTO, carga, chaos, soak ou promoção.

## Achados prioritários da baseline

1. **Promoção NO-GO:** serviços distribuídos, recuperação, carga, provider/corpus, revisão independente final e autoridade humana não estão comprovados.
2. **Documentação desatualizada:** `docs/INDEX.md` e `docs/roadmap-auditoria-atual.md` ainda apontam a nota 72/100 e a auditoria de 07/09; o README lista versões antigas para o laboratório atual.
3. **Login com múltiplas memberships:** o payload não escolhe workspace; a busca PostgreSQL por e-mail/tenant seleciona uma membership com `LIMIT 1`. O escopo/ordenação requer aceitação explícita e teste.
4. **Migration 0008:** os handlers de `duplicate_object` ignoram colisões sem validar a definição existente da constraint; o caminho de colisão não está coberto pelo teste estático.
5. **CI de regressão:** a workflow não executa explicitamente todas as suites de migrations/jobs/storage; a lane RAG-EVAL ainda instala dependências diretamente sem hashes.
6. **Matriz web e testes:** os 321 testes E2E citados antecedem os últimos ajustes visuais; a revisão posterior limita-se à fatia de falha de coleções.

## Limitações documentais

Foram lidos documentos normativos e correntes, ADRs, prompts, planos, relatórios recentes e manifests/logs de evidência relevantes. `docs/reports/evidence/` contém muitos snapshots históricos, logs brutos e imagens; nem cada artefato histórico foi aberto individualmente. Eles não foram promovidos a evidência atual apenas pela presença no diretório.

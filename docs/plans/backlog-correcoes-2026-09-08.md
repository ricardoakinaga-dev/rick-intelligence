# Backlog revisado de construção e correções

**Revisão 2 — 08/09/2026.** Derivado da [reanálise](../reports/reanalise-programa-2026-09-08.md). Substitui a proposta COR anterior neste arquivo; novos IDs `REC-*` evitam reaproveitar significados antigos. A execução foi iniciada a pedido do usuário: REC-01–04 são agrupados em `REC-M0`, e REC-05 está ativo no controlador `.agent/`. A tabela abaixo preserva o escopo e as dependências planejadas, não duplica o estado operacional. Consulte o [relatório de execução](../reports/execucao-planejamento-2026-09-08.md).

## Regras de execução

Prioridade indica consequência: P0 bloqueia a entrega correspondente; P1 é complemento necessário ao produto completo. Todos os itens selecionados para o release precisam ser aceitos, inclusive P1 dos quais outro item depende. Não há P2 cosmético no caminho crítico.

Estados desta proposta: READY = pode iniciar; PLANNED = depende dos IDs listados; DECISION = depende de escolha/autoridade/ambiente. Eles não afirmam trabalho em andamento. D01–D05 estão no [plano executivo](plano-executivo-correcoes-2026-09-08.md). Donos são papéis propostos, ainda sem nomeação.

Dependências são exclusivamente IDs explícitos; não usar “todos P0” nem depender do gate do qual a própria tarefa participa. Quando uma dependência foi concluída, vincular sua evidência antes de ativar a tarefa.

## Itens

| ID | Prioridade | Dono | Estado | Dependências | Entrega e local principal | Aceite observável |
|---|---|---|---|---|---|---|
| REC-01 | P0 | QA | READY | — | **Higiene e evidência dos testes** — apps/web/playwright.config.ts; scripts/phase13; apps/api/tests | Executar com processos próprios, origem/build/portas coerentes; registrar sandbox e duração; não reaproveitar API incompatível. API 358 verde é baseline; não presumir bug do worker. |
| REC-02 | P0 | Produto + Eng. | READY | — | **Congelar escopo por persona e rota canônica** — docs/architecture/canonical-web.md; target-system.md | Confirmar root como produto; matriz Super Admin/RAG/clínico; distinguir requisitos mínimos de paridade opcional com OpenWebUI; identificar operações legadas a portar sem imports diretos. |
| REC-03 | P0 | Backend | READY | — | **Unificar configuração e diagnóstico do provider** —  .env.example; apps/api/src/core/config.py; scripts de inicialização | Exemplo realmente seleciona backend/provider/modelo; precedência e aliases documentados; configuração inválida falha explicitamente; diagnóstico exibe modo efetivo e modelos sem segredos. |
| REC-04 | P1 | Web | PLANNED | REC-02 | **Navegação por permissão** — apps/web/components/app-shell.tsx; lib/presentation.ts | Catálogo/ações só aparecem com permissão; acesso direto continua protegido pelo servidor; troca de identidade limpa estado privado; testes dos três papéis. |
| REC-05 | P0 | Ops | DECISION | D01, D02 | **Ambiente de integração reproduzível** — infrastructure/compose; infrastructure/scripts; .github/workflows | Ambiente isolado com serviços escolhidos, secrets injetados, volumes identificados e teardown restrito; fixtures sintéticas tenant A/B; custos e acessos autorizados. |
| REC-06 | P0 | Dados | DECISION | D01, REC-02 | **Schema de produto e estratégia de migração** — infrastructure/migrations; packages/contracts; knowledge/identity | Modelo de usuários/memberships, sessões, coleções, documentos, chunks, jobs, conversas/mensagens e audit; constraints de escopo; publicação/versionamento; contrato de compatibilidade e plano de backfill. |
| REC-07 | P0 | Dados + Ops | PLANNED | REC-05, REC-06 | **Runner e adapters Postgres** — infrastructure/scripts; packages/knowledge; identity; apps/api/services | Checksums e lock de migração; repetir sem corrupção; interrupção recuperável; store adapters exercitados em Postgres; roll-forward/rollback conforme compatibilidade, sem DROP automático. |
| REC-08 | P0 | Segurança | DECISION | D02, REC-07 | **Identidade externa e sessões persistentes** — packages/identity; apps/api/src/services/identity_service.py; routes/auth.py | Login real com issuer/audience/expiry e callback verificados; stores persistentes; sessão sobrevive a restart; revogação entre réplicas; zero fallback demo em ambiente de integração de produção. |
| REC-09 | P0 | Backend | PLANNED | REC-07 | **Auditoria durável de mutações** — apps/api/src/services/audit.py; adapters externos; admin routes | Evento inclui ator/ação/escopo e alvo seguros; política de falha para mutação sensível definida e testada; histórico conversacional separado de audit; paginação tenant-scoped na origem. |
| REC-10 | P0 | Backend | PLANNED | REC-08, REC-09 | **Ciclo de vida de usuários na API** — apps/api/src/routes/admin.py; identity; authorization | Listar/criar/editar/desativar com validação de papel e tenant; nenhuma escalada; impedir perda involuntária do último administrador; desativação revoga sessões; erros e eventos verificáveis. |
| REC-11 | P0 | Web | PLANNED | REC-04, REC-10 | **Console Super Admin utilizável** — apps/web/app/admin; apps/web/lib/api.ts; types/api.ts | Administrador realiza operações REC-10 pela UI com busca/paginação, erros e confirmação; recarregar e reabrir confirma persistência; testes reais com outro tenant negado. |
| REC-12 | P0 | Backend + Web | DECISION | D01, REC-11 | **Tenants e sessões administrativas** — admin routes; identity stores; apps/web/app/admin | Substituir lista de sessões vazia por consulta autorizada; revogar sessão real e observar 401; gestão de tenant/membership conforme D01. Não ampliar implicitamente PLATFORM_ADMIN para todos os tenants. |
| REC-13 | P0 | Segurança + Web | PLANNED | REC-08, REC-09 | **Recuperação de acesso e credenciais** — routes/auth.py; identity/passwords.py; apps/web/app/login | Recuperação via IdP ou entrega real de token único com expiry/replay negativos e respostas anti-enumeração; rehash Argon2id se credenciais locais forem mantidas; se removidas, registrar decisão e retirar fluxo morto. |
| REC-14 | P0 | Backend + Web | PLANNED | REC-04, REC-07, REC-09 | **Coleções e console RAG** — knowledge routes; packages/knowledge; apps/web/app/admin | CRUD/arquivamento e grants de coleção com escopo; versão/publicação explícitas; área RAG reúne corpus e jobs; revogar acesso remove resultados e fontes visíveis conforme política. |
| REC-15 | P0 | Backend | PLANNED | REC-05, REC-07 | **Object storage e staging durável** — packages/storage; apps/api/src/services/ingestion_service.py | Objeto privado com checksum e tamanho; upload autorizado; fonte sobrevive à saída do processo; path/escopo negativos; limpeza de upload parcial e referência ausente sem perda de publicado. |
| REC-16 | P0 | Platform | PLANNED | REC-05, REC-07, REC-15 | **Fila e worker integrados** — apps/worker; packages/ingestion; contracts; API ingestion service | API publica job e worker separado consome; outbox ou reconciliação evita job órfão; idempotência, capacidade, cancelamento, retry finito e DLQ; crash entre gravar/indexar/publicar não duplica publicação. |
| REC-17 | P0 | Platform | PLANNED | REC-05 | **Leases distribuídos** — packages/locking; Professor/worker composition | Redis/Locker real com owner-safe acquire/renew/release; token perdido impede publicação; TTL/renewal/cancelamento com dois workers; serviço não exposto publicamente. |
| REC-18 | P0 | Retrieval | PLANNED | REC-03, REC-05, REC-07, REC-15 | **Embeddings e Qdrant reais** — packages/providers; packages/retrieval; apps/api composition | Mesmo modelo/dimensão nos documentos e queries; named vectors/schema verificados; upsert/query/delete/count live; pós-filtro ACL; indisponibilidade explícita, sem misturar hash e vetor semântico. |
| REC-19 | P0 | Backend + Web | PLANNED | REC-14, REC-16, REC-17, REC-18 | **Ciclo RAG completo e publicação consistente** — ingestion/knowledge/retrieval services; apps/web/app/app/documents | Gestor faz upload→job→publicação→busca→reindex→exclusão; restart retoma; falha não substitui versão válida; progresso/retry/cancel reais; documentos despublicados não reaparecem na busca. |
| REC-20 | P0 | Platform + QA | PLANNED | REC-08, REC-09, REC-19 | **Composition root de integração** — apps/api/src/app.py; dependencies/services.py; infrastructure | Dois processos API e worker usam recursos externos; readiness cai com dependência obrigatória; nenhum demo/stub implícito; recursos pertencem à instância correta; isolamento e shutdown verificados. |
| REC-21 | P0 | Backend | DECISION | D03, REC-03, REC-05, REC-17, REC-18 | **Professor com geração real** — packages/professor; providers; services/professor_backend.py | Chamada autenticada real pelo caminho da UI/API; backend/provider/modelo efetivos comprovados; evidência autorizada e citações válidas; 429/timeout/lease loss; execução limitada por orçamento. |
| REC-22 | P0 | Produto + Retrieval | DECISION | D04, REC-18, REC-21 | **Golden set e avaliação semântica** — docs/evaluation; scripts/state_of_art; fixtures aprovadas | Conjunto versionado, thresholds fixados antes da execução; leakage zero; ausência/baixa evidência e afirmações sem suporte testadas; resultado por caso/modelo/corpus, não apenas média. |
| REC-23 | P0 | Backend | PLANNED | REC-07, REC-09 | **Conversas e mensagens persistentes** — contracts/chat.py; services/chat_history.py; routes/chat.py | Criar/listar/retomar/arquivar conversa com paginação e ownership; mensagens/estado/citações persistem após restart; acesso cross-user/tenant negado; idempotency key evita turno duplicado. |
| REC-24 | P0 | Professor | PLANNED | REC-21, REC-23 | **Memória de conversa e limites de contexto** — services/chat_service.py; professor/orchestration.py | Turno seguinte usa histórico autorizado obtido no servidor; pergunta dependente do turno anterior funciona; limites/truncamento explícitos; mudança de ACL revalida fontes; conteúdo do usuário não altera instruções privilegiadas. |
| REC-25 | P1 | Backend | PLANNED | REC-21, REC-23 | **Streaming incremental e cancelamento** — providers/protocols.py; provider client; chat_service.py; routes/chat.py | Deltas chegam antes do término do provider; medir primeiro token e conclusão separadamente; disconnect cancela geração/lease; partial/error/complete persistidos. Texto em curso identificado como provisório até validar citações. |
| REC-26 | P0 | Web | PLANNED | REC-04, REC-23, REC-24, REC-25 | **Workspace conversacional** — apps/web/app/app/chat; lib/api.ts; types/api.ts | Sidebar/nova/retomar conversa, múltiplos turnos, cancelamento, retry sem duplicar, fontes expansíveis, estados de confiança; reload mantém histórico; API usada sem intercept nos aceites integrados. |
| REC-27 | P1 | Produto + Web | DECISION | D04, REC-22, REC-26 | **Caso clínico e revisão de resposta** — contratos do Professor; apps/web; docs/evaluation | Escopo aprovado de dados do caso, resumo/hipóteses/evidências e revisão humana; agentes/modelos somente de catálogo autorizado; feedback auditável; aceite por responsável de domínio. |
| REC-28 | P0 | QA + Design | PLANNED | REC-12, REC-13, REC-19, REC-20, REC-26 | **Aceite funcional e acessibilidade** — apps/web/tests; tests/integration; evidence visual | Três personas executam journeys reais; teclado, foco, leitor de tela, contraste, reflow/reduced motion; 375/768/1440; críticas independentes atuais conforme Quality Bar >=95; mocks apenas em testes específicos identificados. |
| REC-29 | P0 | Ops | DECISION | D05, REC-09, REC-20, REC-21 | **Telemetria e alertas operacionais** — observability; API telemetry; infrastructure/monitoring | Collector recebe métricas/logs/traces redigidos, labels bounded; alertas chegam ao destino de teste; SLO possui dono; medir queue lag, DLQ, falhas provider, readiness e latência de conclusão. |
| REC-30 | P0 | Ops + Dados | PLANNED | REC-19, REC-20, REC-23, REC-29 | **Backup, restore e retenção** — infrastructure/scripts; runbooks; adapters de armazenamento | Restore em alvo vazio com contagens/checksums/ACL e conversas; RPO/RTO medidos contra D05; purge por política, dry-run e reconciliação entre DB/objetos/vetores/audit. |
| REC-31 | P0 | Segurança + QA | PLANNED | REC-12, REC-13, REC-20, REC-26, REC-29 | **Segurança e concorrência entre réplicas** — rate_limit; identity; security tests; infrastructure | Rate limit distribuído, revoke propagado, CSRF/CORS/cookie em browser real, secrets/redaction, replay e cross-scope; revisão de ameaça e zero achado Critical/High aberto. |
| REC-32 | P1 | Ops + QA | PLANNED | REC-22, REC-26, REC-29, REC-31 | **Carga, falhas e custo** — tests/performance; tests/concurrency; runbooks | Workload/amostras definidos por D05; p50/p95/p99/TTFT/conclusão, memória e custo; soak, kill-worker e dependency-down; backlog escoa após recuperação; orçamento respeitado. |
| REC-33 | P0 | Release | PLANNED | REC-05, REC-07, REC-30 | **Imagens e ensaio de rollout** — infrastructure/docker; compose; release scripts | Build reproduzível, lockfiles, digest, scan e identidade runtime; canary/rollback ensaiados em staging; compatibilidade de migrations provada; secrets injetados; operação em produção aguarda REC-35. |
| REC-34 | P0 | Reviewer | PLANNED | REC-01, REC-22, REC-27, REC-28, REC-30, REC-31, REC-32, REC-33 | **Candidato e parecer final** — docs/progress/release-evidence.json; manifests; reviews | Snapshot identificado, evidências apontam mesmo artefato/configuração; reviews independentes de integração/produto/ops; gaps classificados; alterações invalidam evidências afetadas; nenhum P0 obrigatório aberto. |
| REC-35 | P0 | Produto + Segurança + Ops | DECISION | REC-34 | **Go/No-Go e promoção** — release evidence; gate; runbook | Decisão humana sobre candidato concreto; autorização de rollout, janela e responsáveis; observar canary/rollback; registrar resultado. NO-GO se critério obrigatório falta. |

## Primeira frente executável

1. REC-01: capturar ambiente/commands e corrigir apenas o harness quando necessário; preservar a evidência dos 358 testes já aprovados fora do sandbox.
2. REC-02: matriz de personas, rotas e operações; usar o root já canônico como ponto de partida.
3. REC-03: contrato de configuração verificável sem chave real, incluindo seleção de provider determinístico versus externo.
4. REC-04 após REC-02: navegação coerente com permissões.
5. Preparar propostas D01–D05 em paralelo; levar alternativas, custo e impacto ao responsável antes de provisionar.

## Formato de evidência por tarefa

Ao ativar: registrar owner nominal, revision/configuração, hipótese ou requisito, paths autorizados, comandos de verificação e rollback. Ao entregar: resultado público observado, testes positivos/negativos, código de saída, duração, artefatos seguros, limites e reviewer. `IMPLEMENTED_LOCAL` é avanço parcial; não é aceite live.

Para REC-03: testes de configuração podem usar valores sintéticos; jamais registrar chave verdadeira. Para REC-10–13: executar criação/alteração apenas em identidades sintéticas do ambiente autorizado. Para REC-15–20: nomear recursos temporários por run e validar escopo antes de removê-los. Para REC-25: definir previamente quando a resposta pode ser exibida como provisória e quando é validada.

Reabrir a tarefa quando código/configuração relevante invalidar a evidência. Falha de teste exige reprodução discriminante; não remover assertions, adicionar skip ou elevar timeout apenas para passar.

## Rastreabilidade da proposta anterior

| Proposta anterior | Tratamento nesta revisão |
|---|---|
| COR-001–004 | REC-01/03/34: timeout reclassificado após teste fora do sandbox; fingerprint local diagnóstico separado de candidato de release |
| COR-010–020 | REC-05–09/15–20/30: dados e worker compostos por fatias com recuperação |
| COR-030–036 | REC-08/10–13/31: acrescentados CRUD de usuários, UI, tenants, sessões e recuperação utilizável |
| COR-040–046 | REC-21–27: provider real, embeddings, memória multi-turn e streaming têm aceites distintos |
| COR-050–055 | REC-04/11–14/19/26–28: frontend vinculado a jornadas reais por persona |
| COR-060–070 | REC-29–35: dependências finitas; reviewer precede decisão humana sem ciclo |

## Controle desta revisão

Após a solicitação de implementação: REC-01–04 têm mudanças locais implementadas e verificadas por testes, ainda sem parecer independente; REC-05 tem laboratório preparado, mas não executado. Postgres/fila transacional, S3-compatible e OIDC locais foram aprovados. Docker/Compose estão instalados; a sessão do agente ainda não tem acesso ao daemon. Os demais aceites não estão concluídos; detalhes e decisões pendentes no [relatório de execução](../reports/execucao-planejamento-2026-09-08.md). Estado canônico em `.agent/backlog.json`.

[Plano executivo](plano-executivo-correcoes-2026-09-08.md) · [Roadmap](roadmap-correcoes-2026-09-08.md)

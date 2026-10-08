# Backlog — criações, correções e implementações de qualidade

Data: 2026-09-17. Versão BL17-v1. Estado: **CATÁLOGO PROPOSTO; NÃO É O BACKLOG CANÔNICO DE EXECUÇÃO**.

Fontes: [auditoria preservada](../reports/relatorio-auditoria-2026-09-17.md), [plano executivo](plano-executivo-qualidade-2026-09-17.md), [roadmap](roadmap-qualidade-2026-09-17.md). Baseline de código: `b52f32c`.

## Regras de execução e conclusão

Todos os épicos Q17-01 a Q17-26 correspondem, na mesma ordem, aos itens 1–26 da auditoria. Não são as dimensões oficiais da promoção. Todos os épicos e subtarefas estão **PROPOSTOS / NOT_RUN nesta etapa documental**. Notas são baseline histórico, não metas ou status de execução. Owner é papel a designar, não aprovação atribuída a pessoa inexistente.

- Cada letra A/B/C/D é uma tarefa verificável, que deve receber item canônico na ativação D06. Dependências citadas como `Q17-NN.X` são tarefas; `D01`–`D07` são decisões humanas do plano, não tarefas supostamente concluídas. Dependências em "nenhuma" permitem trabalho após ativação D06 e inspeção de contexto.
- Cada linha descreve escopo de criação, correção ou implementação e aceite. O bloco "Verificação e prova" integra o contrato de todas as subtarefas do épico. Sem resultado fresco no limite indicado não há DONE; quando uma linha exige decisão humana, ela permanece bloqueada até obtê-la.
- P0: bloqueia corretude, integridade, segurança ou entrega básica. P1: funcionalidade/qualidade requerida antes de promoção. P2: fechamento/campanha de aceitação após fundamentos; **não é opcional**. Prioridade não é severidade de vulnerabilidade nem alegação de incidente reproduzido.
- Antes de implementar achado estático: confirmar o caminho, capturar baseline discriminante, preservar falha e adicionar regressão. Se refutado, registrar evidência/disposição e manter histórico, sem alteração artificial para justificar o relatório.
- Evidência mínima por tarefa: ID canônico/Q17, candidato/tree, caminhos/digests, comando/procedimento, resultado/exit, ambiente/janela/amostra, logs sanitizados, testes focados e regressões, reviewer independente, limitações e procedimento de recuperação. Nunca salvar credenciais.
- Recuperação padrão: desfazer apenas patch próprio ainda não integrado ou rollback/roll-forward aprovado; alterações persistentes precisam de estratégia específica. Não modificar migration aplicada, apagar dados/volumes, reescrever histórico ou tocar legado protegido. Templates e schemas existentes são reutilizados, não duplicados sem necessidade.

## Q17-01 — Arquitetura e separação de responsabilidades

**Item 1; nota 85; P1; owner Lead/arquitetura; marcos M0/M7.** Fontes: `README.md:72`, `docs/architecture/dependency-boundaries.json`, `.agent/state.json`. Aproveitar direção de dependências e adapters existentes, sem reescrita geral.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-01.A | Criar mapa de ownership e reconciliação Q17→tarefas canônicas; capturar HEAD e preservar alterações; cada trabalho tem owner funcional e nenhum duplicado em execução | D06 |
| Q17-01.B | Corrigir acoplamentos apenas quando identificados por regra/fluxo; registrar contrato de autoridade, publicação, adapters e fronteiras de transação, incluindo alternativa/recovery | Q17-01.A |
| Q17-01.C | Verificar mapa final, migração por equivalência e ausência de imports proibidos; registrar diferenças planejado→entregue sem remover legado por conveniência | Q17-25.C, Q17-26.C |

**Verificação e prova:** `make validate`, análise dos callers e testes do boundary checker com violação sintética controlada; revisão arquitetural conectada. Mapa sem caller/teste não prova implementação. Não adotar separação cosmética como critério de qualidade.

## Q17-02 — Documentação e aderência ao estado atual

**Item 2; nota 65; P1; owner documentação/Lead; marcos M0/M7.** Fontes: `docs/architecture/current-system.md:3`, `packages/contracts/README.md:3`, auditoria runtime e quality bar.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-02.A | Criar matriz das 64 seções do prompt atual, 26 itens da auditoria, 26 dimensões oficiais, gates e tarefas canônicas; enumerar cada caso obrigatório, sem requisito órfão | Q17-01.A |
| Q17-02.B | Corrigir status e navegação de docs vigentes, CSRF, roles e contratos; marcar retratos históricos sem alterar snapshots protegidos; resolver divergência de prompts por decisão rastreada | Q17-02.A |
| Q17-02.C | Publicar manual de uso/operação/recuperação e relatório final com estado observado, evidências e limitações; sem sucesso ou score inventado | Q17-01.C, Q17-25.C |

**Verificação e prova:** links locais e IDs íntegros, `make validate`, walkthrough dos comandos em ambiente correspondente; diff sem edição de histórico protegido. A cópia de 17/09 permanece imutável, correções posteriores são adendos separados.

## Q17-03 — Identidade e sessões

**Item 3; nota 80; P1; owner identidade/backend; marco M3.** Fontes: `packages/identity/src/rick_identity/provider.py:119`, `apps/api/src/routes/auth.py:152`, `packages/identity/src/rick_identity/passwords.py:14`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-03.A | Corrigir contrato de TTL ocioso/absoluto e cookie; renovação, expiração e revogação coerentes entre navegador e servidor, sem ampliar sessão silenciosamente | Q17-06.A |
| Q17-03.B | Implementar formato versionado de hash/custo e migração/rehash compatível após decisão de política; revisar atualização de credenciais, permissões e invalidar snapshots antigos | Q17-03.A, Q17-19.B |

**Verificação e prova:** testes com relógio controlado e browser para limite ocioso/absoluto, logout, troca de senha/papel, usuário desativado e tenant; persistência/restart em PostgreSQL; benchmark de custo de hash antes de alterar política. Preservar logins antigos válidos e nunca reduzir custo para passar performance.

## Q17-04 — Autorização e isolamento

**Item 4; nota 83; P0; owner autorização/security; marco M3.** Fontes: `packages/authorization/src/rick_authorization/policy.py:239`, `docs/architecture/authorization.md:16`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-04.A | Especificar e implementar ausência versus lista vazia versus wildcard nas concessões, com migração compatível aprovada; matriz de papéis reflete cases e permissões efetivas | Q17-06.A, D01 |
| Q17-04.B | Completar matriz de isolamento tenant/workspace/coleção em API, busca, stores, histórico, audit e caches; negar escopo inválido sem exposição indevida | Q17-04.A, Q17-07.B, Q17-22.A |

**Verificação e prova:** unit tests da álgebra e testes defensivos com identidades sintéticas e payloads válidos; `make phase3-tenant-evidence-runtime` no lab autorizado. Verificar status/corpo/IDs/metadados pertinentes, não apenas recurso escondido na UI. Alteração de concessões exige rollback de política e revogação de snapshots conforme contrato.

## Q17-05 — Kernel HTTP e controles defensivos

**Item 5; nota 84; P0; owner API/security; marco M3.** Fontes: `apps/api/src/core/csrf.py:83`, `apps/api/tests/test_route_policy.py:30`, `apps/api/src/app.py:643`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-05.A | Corrigir testes de route policy para usar corpos válidos e rejeição correta de autenticação/autorização; HTTP 422 não satisfaz gate de acesso | Q17-26.A, Q17-06.A |
| Q17-05.B | Reconciliar CSRF/origin, cookies, CORS, exposição de metrics, health/readiness e lifecycle real; definir política de proxy/TLS sem abrir exceções de produção | Q17-05.A, Q17-18.B, Q17-03.A, D02 |

**Verificação e prova:** `make api-security`, `make api16-root`, requests no lab aprovado com configurações permitidas/negadas; shutdown e limites finitos observados. Testes defensivos limitados ao sistema próprio e fixtures controladas; nenhuma campanha contra terceiros.

## Q17-06 — Contratos e compatibilidade

**Item 6; nota 65; P1; owner contratos/API/frontend; marcos M0/M3.** Fontes: `packages/contracts/src/rick_contracts/base.py:6`, `apps/web/lib/api.ts:79`, `apps/api/tests/test_dual_equivalence.py:30`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-06.A | Criar especificação versionada JSON/SSE/histórico/retry binário e erros, inclusive metadata e idempotência; acordar campos opcionais, compatibilidade e evolução | Q17-01.B |
| Q17-06.B | Implementar validação consistente nas fronteiras restantes, dados recebidos no cliente e um parser de chat canônico; substituir tautologias por equivalência de respostas reais | Q17-06.A, Q17-26.A |

**Verificação e prova:** `make api15-contracts`, `make api-contract`, `make api16-root` e typecheck web; contrato bom passa e payload malformado/desconhecido falha de modo explícito. Testar cliente anterior durante rollout; não esconder JSON inválido sob cast TypeScript.

## Q17-07 — Knowledge: documentos, versões e proveniência

**Item 7; nota 81; P0; owner conhecimento/dados; marco M2.** Fontes: `packages/knowledge/src/rick_knowledge/store.py:86`, `sqlite_store.py:323`, `postgres_store.py:315` no mesmo diretório.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-07.A | Corrigir paridade de exclusão terminal entre memória/SQLite/PostgreSQL, inclusive upsert e reingestão; tombstone não é apagado por adapter alternativo | Q17-01.B |
| Q17-07.B | Implementar suíte comum de contrato de identidade, escopo, corrupção/JSON, versão e restart para todos os stores; executar persistentes em ambiente apropriado | Q17-07.A, Q17-19.B |

**Verificação e prova:** `make api16-domain` e integração PostgreSQL real; excluir→upsert→reingestão rejeita ressurreição conforme política; isolamento e linhagem preservados. Não mudar IDs legados sem contrato de equivalência e migração.

## Q17-08 — Ingestão e reindexação

**Item 8; nota 76; P0; owner ingestão/RAG; marco M2.** Fontes: `packages/ingestion/src/rick_ingestion/pipeline.py:549`, `:593`, `apps/api/src/services/external_composition.py:166`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-08.A | Implementar lotes limitados de embeddings com contagem/ordem/dimensão verificadas e cancelamento; erro determinístico de lote não é indisponibilidade transitória | Q17-06.A |
| Q17-08.B | Corrigir reindexação de mesmo conteúdo com novo embedding/modelo/versão e verificação de cada ponto/versão; preservar versão publicada até a substituição ser válida | Q17-08.A, Q17-07.B, Q17-22.A |
| Q17-08.C | Executar matriz completa de falhas de ingestão/parsing isolado e golden path com publicação/recovery; todos os doze casos do prompt têm evidência individual | Q17-08.B, Q17-20.B, Q17-18.B, D01, D03 |

**Verificação e prova:** arquivos de 255/256/257+ chunks, falha em lote intermediário, dimensões inválidas, cancelamento, replay e reindexação; `make api16-domain`, `make phase3-golden-runtime`, `make phase3-file-security-runtime` quando autorizados. Corpus adverso controlado apenas no worker isolado com limites; nenhuma simulação conta como live. Não apagar versão válida para recuperar uma tentativa falha.

## Q17-09 — Retrieval e busca híbrida

**Item 9; nota 69; P1; owner retrieval; marco M3.** Fontes: `packages/retrieval/src/rick_retrieval/backends.py:143`, `:201`, `pipeline.py:167` no mesmo diretório.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-09.A | Implementar sparse+dense no caminho Qdrant real e compatibilidade de schema/indexação; aplicar escopo nas duas modalidades antes da fusão/rerank | Q17-08.B, Q17-04.A |
| Q17-09.B | Corrigir fallback para falha de backend conforme política explícita, e contrato de fonte persistente ou remoção da promessa de disco não atendida; provar ganho e custo por ablação | Q17-09.A, Q17-14.A |

**Verificação e prova:** integração Qdrant real com caso lexical e semântico, coleção negada e indisponibilidade controlada; fallback_used observado; comparar dense/sparse/híbrido/reranker no conjunto aprovado. Não reivindicar melhoria estatística com duas fixtures nem alterar threshold pós-resultado. Reconstruir projeção a partir da autoridade verificada.

## Q17-10 — Evidence: fontes e citações

**Item 10; nota 81; P0; owner evidence/RAG; marco M3.** Fontes: `packages/evidence/src/rick_evidence/validator.py:163`, `apps/api/src/services/professor_backend.py:364`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-10.A | Criar contrato de consistência temporal e implementar revalidação de fonte/chunk/checksum/versão antes de publicação final; fonte revogada durante geração não recebe aprovação | Q17-07.B, Q17-06.A |
| Q17-10.B | Especificar e implementar composição multi-coleção autorizada ou resultado explicitamente limitado com política aprovada; não descartar fontes silenciosamente | Q17-10.A, Q17-09.A, D04 |

**Verificação e prova:** alterar/excluir fonte entre recuperação e finalização com sincronização determinística; testar normal e SSE; propriedade imutável dos bundles e IDs emitidos pelo servidor. Suporte lexical não é entailment; avaliação semântica independente em Q17-14.B.

## Q17-11 — Decision: responder, abster e escalar

**Item 11; nota 70; P0; owner RAG/domínio; marco M3.** Fonte: `apps/api/src/services/professor_backend.py:317`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-11.A | Criar política aprovada de risco/intenção/sinais e implementar estados unknown/ambíguo sem assumir LOW/CLEAR; incorporar suporte/faithfulness observado quando requerido | Q17-14.A, Q17-10.A, D04 |
| Q17-11.B | Conectar ANSWER/RETRIEVE_AGAIN/CLARIFY/ABSTAIN/ESCALATE à API; retry limitado altera estratégia quando indicado; razão e ação não colapsam sempre em NO_EVIDENCE | Q17-11.A, Q17-09.B, Q17-06.B |

**Verificação e prova:** tabela decisão→inputs→saída com positivos/negativos, risco alto, sinal ausente, intenção ambígua e budget esgotado; conferir resposta pública e efeito de retries. Domain owner aprova política; teste de enum não basta para provar triagem real. Não automatizar decisão clínica por simples score de retrieval.

## Q17-12 — Professor e geração fundamentada

**Item 12; nota 70; P0; owner Professor/RAG; marco M3.** Fonte: `packages/professor/src/rick_professor/orchestration.py:1097`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-12.A | Corrigir aprovação sem marcador/citação ou suporte válido; produzir abstenção/erro tipado conforme contrato, sem label APPROVED_EVIDENCE indevido | Q17-06.A, Q17-10.A |
| Q17-12.B | Implementar orçamento preventivo e cancelamento em streaming, preservar caráter provisório e incorporar decisões e revalidação final | Q17-12.A, Q17-11.B, Q17-13.A |

**Verificação e prova:** `make api15-professor`, `make api16-root`; casos sem marcador, marcador inválido, fonte revogada, teto atingido, lease perdido, cancelamento e resposta correta. Medir consumo real quando provider autorizado; delta já emitido não pode ser descrito como retroativamente removido da rede.

## Q17-13 — Integração com providers

**Item 13; nota 83; P1; owner providers; marco M3.** Fontes: `packages/providers/src/rick_providers/client.py:446`, `:462`, `resilience.py:115` no mesmo diretório.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-13.A | Corrigir controle de emissão para tool deltas e limites de buffering antes de linha SSE completa; especificar orçamento/retry/cancel e avaliar fase half-open sem tempestade | Q17-06.A |
| Q17-13.B | Implementar/executar matriz real limitada de chat/embedding/tool/JSON/429/500/timeout/cancel/reconexão com modelo, dimensão e custo aprovados | Q17-13.A, Q17-18.B, D03 |

**Verificação e prova:** `make api15-provider` com transportes controlados para limites e sequência; `make phase3-provider-runtime` para limite real autorizado. Nenhum retry após saída parcial que duplique conteúdo/ferramenta; não alegar execução duplicada de tools no Professor sem caller real. Observar memória/tempo e redação; desligar provider com abstenção explícita ao exceder budget.

## Q17-14 — Avaliação de qualidade RAG

**Item 14; nota 63; P1; owner avaliação/RAG/domínio; marco M3.** Fontes: `docs/evals/rag-evaluation.md:9`, `scripts/state_of_art/evaluate_pack.py`, pack `rec22-local-v1`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-14.A | Implementar MRR/nDCG/ganho reranker/relevância/abstenção e thresholds por grupo; distinguir métrica ausente de zero/PASS; testar avaliador com valores conhecidos | Q17-02.A |
| Q17-14.B | Criar conjunto licenciado/representativo estratificado por risco/tenant/modelo/corpus, separar calibração e holdout, congelar limiares antes de avaliar; executar fluxo real e revisão qualificada | Q17-14.A, Q17-09.B, Q17-12.B, Q17-13.B, D04 |

**Verificação e prova:** `make eval-retrieval-pack` mantém baseline sintético; testes do harness rejeitam grupo abaixo do limiar mesmo com agregado bom. Medir cinco métricas de citação, falsos aprovados, abstenção e relevância com labels/rubrica; declarar tamanho amostral, incerteza e licença. Comparação externa só se autorizada e com protocolo justo; não prometer "melhor do mercado".

## Q17-15 — Chat, histórico e apresentação das evidências

**Item 15; nota 72; P1; owner frontend/API; marco M4.** Fontes: `apps/api/src/services/chat_service.py:448`, `apps/web/components/chat/chat-adapter.ts:174`, `chat-workspace.tsx:195` no mesmo diretório.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-15.A | Implementar metadata canônica em completion/replay/SSE buffered e parser único; a resposta exibida e o histórico têm classificação/fontes equivalentes | Q17-06.B, Q17-12.A |
| Q17-15.B | Implementar paginação de conversas/mensagens, descarte de resposta obsoleta e estados incrementais; preservar leitura/scroll e pergunta durante erro/retry | Q17-15.A |

**Verificação e prova:** testes HTTP/SSE e browser API-backed com approved/weak/none/provisional/interrupted, mais de 50 conversas e 100 mensagens; nenhuma duplicação ou mistura de escopo. Render em 375/768/1440 e teclado/leitor de tela na matriz Q17-26.C. Sem metadata não há inferência otimista de aprovação.

## Q17-16 — Documentos, busca e ingestão pela interface

**Item 16; nota 68; P1; owner frontend/ingestão; marco M4.** Fonte: `apps/web/app/app/documents/page.tsx:125`, `:157`, `:225`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-16.A | Corrigir destino de upload com seleção explícita entre coleções autorizadas; implementar retry multipart/referência autorizada preservando bytes, MIME e origem | Q17-06.B, Q17-04.A, Q17-08.A |
| Q17-16.B | Implementar acompanhamento limitado com backoff/cancelamento/retomada, reconciliação após reload e atualização do catálogo; timeout significa estado não confirmado | Q17-16.A, Q17-20.B |

**Verificação e prova:** upload para coleção não-default, 403, TXT/PDF/DOCX com checksum antes/depois do retry, job acima da janela atual, troca de escopo e falha de rede. `make web-e2e` com API real e catálogo/objeto/job conferidos; estados e touch targets na matriz Q17-26.C. Não exibir percentual inventado ou sucesso local sem servidor.

## Q17-17 — Administração, auditoria e casos

**Item 17; nota 71; P0; owner backend/frontend/dados; marco M4.** Fontes: `apps/api/src/routes/admin.py:90`, `:112`, `apps/web/lib/api.ts:172`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-17.A | Especificar consistência mutação/audit (transação/outbox/intenção+reconciliação) e implementar create/update/deactivate/reset com resultado correto sob falha do sink | Q17-01.B, Q17-19.B, Q17-03.B |
| Q17-17.B | Implementar chave estável por intenção nas mutações de casos e retry UI; conflito explícito quando mesma chave tem payload diferente | Q17-06.B, Q17-17.A |
| Q17-17.C | Corrigir falhas isoladas por painel, paginação de casos/audit e detalhes sanitizados; preservar dados do formulário em resultado incerto | Q17-17.B |

**Verificação e prova:** falha do audit antes/depois de persistir, timeout pós-commit e retry; uma intenção produz um efeito e trilha reconciliável. Inspecionar PostgreSQL e API; UI com permissões parciais não some por 403 de painel independente. Revisão humana de casos não deve parecer diagnóstico automatizado.

## Q17-18 — Containers e composição do ambiente

**Item 18; nota 52; P0; owner plataforma/SRE; marco M1.** Fontes: `apps/worker/deployment_composition.py:120`, `docker-compose.dev.yml:201`, `:224`, staging correspondente.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-18.A | Corrigir contrato do factory API versus RICK_WORKER_ID, carregar regras Prometheus na configuração correta e testar defaults/env exigidos nas imagens | Q17-01.B |
| Q17-18.B | Construir e iniciar stack isolada com migração/bootstrap/health/readiness, API/Web/Worker A/B/OTel; registrar inventário/digests e desligamento próprio seguro | Q17-18.A, Q17-19.A, Q17-20.A, Q17-21.A, Q17-23.A, D01, D02 |

**Verificação e prova:** `make compose-static`, build/import/startup real e `make up` somente com daemon/env autorizados. Verificar o factory efetivamente selecionado e não generalizar defeito do default para toda composição customizada. Falta de Docker é bloqueio, não permissão para mudar host ou usar produção.

## Q17-19 — Jobs, PostgreSQL e migrações

**Item 19; nota 66; P0; owner banco/jobs; marco M1.** Fontes: `infrastructure/migrations/0005_rewrite_legacy_jobs.sql:148`, `infrastructure/scripts/migrate.py:60`, `apps/worker/deployment_composition.py:36`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-19.A | Reproduzir migration com jobs legados, corrigir função JSON incompatível; inventariar instalações/checksums e definir migration corretiva ou reparo pré-aplicação seguro, sem reescrever aplicada | Q17-01.B |
| Q17-19.B | Alinhar transação por arquivo versus contrato do runner, timeouts query/lock, rollback e restart; provar claim/attempt/outbox/audit com PostgreSQL real | Q17-19.A, D01, D02 |

**Verificação e prova:** base vazia, legada não vazia, falha intermediária, repetição e concorrência; `make ops-static`, `make phase3-postgres-runtime`. Não tratar fake rollback como atomicidade. Guardar backup/checksum e recovery autorizado antes de operação em dados persistentes; forward-fix se rollback de schema não preservar semântica.

## Q17-20 — Worker e ciclo de vida

**Item 20; nota 65; P0; owner worker/runtime; marcos M1/M2.** Fontes: `infrastructure/docker/worker-entrypoint.py:158`, `:187`, `apps/worker/runtime.py:1039`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-20.A | Corrigir healthcheck para observar processo principal e shutdown para usar início do encerramento, não uptime; readiness reflete polling/fatalidade/saturação conforme contrato | Q17-01.B |
| Q17-20.B | Completar publicação sob fencing/outbox e matriz real Worker A/B, incluindo oito pontos de crash, stale ACK/publish, reclaim e cancelamento | Q17-20.A, Q17-19.B, Q17-22.A |

**Verificação e prova:** `make api16-worker`, `make jobs-test`, `make phase3-multi-worker-runtime`; uptime >29s não encurta arbitrariamente shutdown; worker principal travado não fica saudável por factory nova. Contar publicação externa e autoridade durável, não só retorno do handler. Respeitar limites de thread cooperativa e manter dependências vivas enquanto ainda usadas.

## Q17-21 — Redis e coordenação distribuída

**Item 21; nota 71; P1; owner Redis/SRE; marcos M1/M2.** Fontes: `packages/locking/src/rick_locking/redis_config.py:597`, `docker-compose.staging.yml:60`, `apps/worker/deployment_composition.py:149`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-21.A | Resolver topologia TLS de staging (Redis embarcado TLS ou serviço aprovado coerente) e ownership do cliente async/event loop; não relaxar produção para HTTP/plaintext | Q17-01.B, D02 |
| Q17-21.B | Provar lease/rate limit em API A/B, compartilhamento do bucket, expiração/reconnect/owner-safe release, namespace e orçamento de retries | Q17-21.A, Q17-18.B |

**Verificação e prova:** `make api15-lock`, `make phase3-redis-runtime`, `make phase3-redis-multi-replica-runtime`; duas instâncias alternadas compartilham limite sem vazamento de tenant. Validar certificado/auth e lifecycle async real, não supor bug ou correção só pela inspeção.

## Q17-22 — Storage e inicialização persistente

**Item 22; nota 66; P0; owner storage/dados; marco M2.** Fontes: `packages/storage/src/rick_storage/s3_object_store.py:260`, `apps/worker/external_ingestion.py:121`, `infrastructure/compose/bootstrap_object_store.sh:27`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-22.A | Corrigir leitura do worker para exigir integridade e comparar digest esperado da origem/job; rejeitar checksum ausente/divergente e escopo inválido antes do parsing | Q17-06.A |
| Q17-22.B | Implementar bootstrap convergente e política aprovada de rotação/versionamento/retenção; reconciliar usuário/policy existentes e alias/rebuild Qdrant com observação real | Q17-22.A, Q17-18.B, D01, D02 |

**Verificação e prova:** `make storage-test`, `make phase3-object-qdrant-runtime`; bytes iguais ao aprovado, objetos alterados/ausentes recusados, restart idempotente, rotação de credencial sem imprimir segredo. Mudanças de retenção/versionamento exigem owner; teste nunca destrói dados do host.

## Q17-23 — Observabilidade e SLO

**Item 23; nota 55; P1; owner observabilidade/SRE; marcos M1/M5.** Fontes: `packages/observability/src/rick_observability/events.py:128`, `infrastructure/compose/prometheus.yml`, `docs/operations/slo.md:48`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-23.A | Corrigir entrega a sink bloqueado com fila/concorrência/capacidade finitas, descarte/timeout observável e shutdown limitado; não gerar thread ilimitada por evento | Q17-01.B |
| Q17-23.B | Completar exporter, scrape worker, regras/alertas e SLI reais; propagar trace e redigir campos aninhados sem cardinalidade por tenant/usuário/conteúdo | Q17-23.A, Q17-18.B, Q17-08.C, D05 |

**Verificação e prova:** emissão sustentada com sink bloqueado dentro de orçamento, CPU/RAM/thread count, métricas de perda; `make phase3-observability-runtime`; observar trace entre processos e alerta recebido em destino autorizado. Campos no_data não são saúde; janelas dev/staging/produção permanecem separadas.

## Q17-24 — Recuperação, capacidade e tolerância a falhas

**Item 24; nota 45; P1; owner SRE/dados; marco M5.** Fontes: `infrastructure/scripts/backup_restore.py:1`, `scripts/state_of_art/phase3_lane.py:127`, runbooks SLO/DR.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-24.A | Criar harness concreto de restore dos serviços e executar seed→backup→destroy→restore→rebuild→verify em cópia autorizada; medir RPO/RTO e reconciliação completa | Q17-22.B, Q17-20.B, Q17-23.B, D01, D05 |
| Q17-24.B | Criar workloads production-shaped, baseline de capacidade/custo e congelar budgets/janelas antes de aceitação; cinco workloads, concorrências 1/10/50/100 | Q17-24.A, Q17-14.B, Q17-26.C, D03, D05 |
| Q17-24.C | Implementar/executar matriz chaos de treze faults/cinco invariantes e soak curto/estendido com limites aprovados; não aceitar corrupção, duplicação ou crescimento sem limite | Q17-24.B |

**Verificação e prova:** `make phase3-restore-runtime`, `make phase3-performance`, `make phase3-chaos`, `make phase3-soak` ligados aos harness reais; p50/p95/p99/throughput/erros/CPU/RAM/custo, janela, amostra e environment. RPO≤15min/RTO≤60min conforme contrato aprovado; p95 retrieval≤1,5s na janela definida, sem extrapolar fixture. Harness externo ausente significa tarefa incompleta, não passagem do gate.

## Q17-25 — CI e promoção de release

**Item 25; nota 63; P0; owner QA/release; marcos M6/M7.** Fontes: `scripts/state_of_art/triple_aaa_verify.py:513`, `:541`, `:544`, `.github/workflows/quality.yml`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-25.A | Corrigir fluxo das lanes sem comando para consumir observações/reviews/autoridade verificáveis; caso completo autorizado pode passar e missing/stale/tampered/self-approved falha | Q17-02.A, Q17-26.A |
| Q17-25.B | Implementar CI/runtime/lab/evidência na ordem causal correta, oito lanes e provisionamento aprovado; remover dependência circular de pacote/autoridade sem remover gates | Q17-25.A, Q17-18.B, Q17-26.B |
| Q17-25.C | Completar SBOM/licenças/auditoria de dependências/secrets/imagens, hardening, digest e assinatura por autoridade; ligar a reviews e fontes exatas | Q17-25.B, Q17-24.C, D02 |
| Q17-25.D | Reexecutar aceitação integral no candidato limpo autorizado, scorecard oficial ≥96 e gates PASS, zero Critical/High; selo e decisão humana independente | Q17-02.C, Q17-26.D, D07 |

**Verificação e prova:** testes do promotion engine e end-to-end do verifier com fixtures autorizadas/inválidas; não confundir fixture good com promoção real. `make triple-aaa-verify`, logs CI same-SHA, pacote/digests/reviews assinados; preservar frescor24h/tolerância5min e resolver janelas longas em D05. D07 autoriza decisão; deployment é ação separada. Esta entrega não cria commit para fabricar checkout limpo.

## Q17-26 — Qualidade global dos testes e verificação visual

**Item 26; nota 74; P1; owner QA/design/revisores; marcos M0/M4/M6/M7.** Fontes: `apps/api/tests/test_dual_equivalence.py:30`, `test_auth.py:117` no mesmo diretório, `scripts/phase11/runner.py:704`, `apps/web/tests/`.

| Tarefa | Tipo / escopo e aceite | Dependências |
|---|---|---|
| Q17-26.A | Auditar asserções tautológicas, fixtures golden não ligadas à API e falso E2E; criar reproduções focadas dos achados e provas known-bad/good de cada harness crítico | Q17-01.A |
| Q17-26.B | Integrar suites canônicas no fluxo CI, cobertura por requisito, lint/typecheck/build/test; avaliar checker Python incremental e atualizar depreciações sem esconder falhas | Q17-26.A, Q17-06.B |
| Q17-26.C | Implementar matriz browser API-backed e pacote visual/acessibilidade conforme PE17: todos os estados e 375/768/1440, screenshots nativas, console/network, teclado/leitor de tela e crítica visual | Q17-15.B, Q17-16.B, Q17-17.C, Q17-18.B |
| Q17-26.D | Revisão independente final dos doze escopos/dezoito checks e regressão integrada, com critic distinto e sentinela; nenhuma lacuna required fica omitida | Q17-25.C, Q17-26.C |

**Verificação e prova:** `make validate`, `make lint`, `make typecheck`, suites API/domínio/provider/worker e `make web-validate` no ambiente adequado. Coverage report registra linhas/branches e mapa de requisitos sem inventar porcentagem mínima; casos críticos precisam rejeitar falha sem mocks na fronteira julgada. Q17-26.C exige visual≥95/confiançaHIGH, WCAG AA aplicável, sem barreira essencial, dois críticos frescos cegos e adjudicação se necessário. Se browser/reviewer/corpus ausente: BLOCKED/NOT_RUN, nunca PASS por quantidade de testes.

## Matriz de vínculo aos critérios existentes

Esta tabela cobre os 26 itens da auditoria frente aos IDs do quality bar atual. Não substitui a matriz integral por seção/dimensão/gate que Q17-02.A deve produzir antes da construção substancial. Requisitos adicionais do prompt de 10/09 continuam obrigatórios.

| Item Q17 | Critérios de qualidade existentes |
|---|---|
| Q17-01 | P0-CONTROL, P1-REVIEWS-PROMOTION |
| Q17-02 | P0-CONTROL, P0-RELEASE |
| Q17-03 | P1-TENANT-EVIDENCE |
| Q17-04 | P1-TENANT-EVIDENCE |
| Q17-05 | P0-LAB, P1-TENANT-EVIDENCE |
| Q17-06 | P0-CONTROL, P1-RAG-PROVIDER |
| Q17-07 | P0-DURABILITY, P1-TENANT-EVIDENCE |
| Q17-08 | P0-DURABILITY, P1-RAG-PROVIDER |
| Q17-09 | P0-REDIS-STORAGE, P1-RAG-PROVIDER |
| Q17-10 | P1-TENANT-EVIDENCE, P1-RAG-PROVIDER |
| Q17-11 | P1-RAG-PROVIDER |
| Q17-12 | P1-RAG-PROVIDER |
| Q17-13 | P1-RAG-PROVIDER |
| Q17-14 | P1-RAG-PROVIDER |
| Q17-15 | P1-FRONTEND, P1-RAG-PROVIDER |
| Q17-16 | P1-FRONTEND, P0-DURABILITY |
| Q17-17 | P1-TENANT-EVIDENCE, P1-FRONTEND, P0-DURABILITY |
| Q17-18 | P0-LAB, P1-SUPPLY-CHAIN |
| Q17-19 | P0-DURABILITY |
| Q17-20 | P0-DURABILITY, P0-LAB |
| Q17-21 | P0-REDIS-STORAGE |
| Q17-22 | P0-REDIS-STORAGE, P0-DURABILITY |
| Q17-23 | P1-OBSERVABILITY |
| Q17-24 | P1-RECOVERY |
| Q17-25 | P0-CONTROL, P0-RELEASE, P1-SUPPLY-CHAIN, P1-REVIEWS-PROMOTION |
| Q17-26 | P0-CONTROL, P1-FRONTEND, P1-REVIEWS-PROMOTION |

## Handoff

Owner de status futuro: `.agent/backlog.json` após reconciliação D06; não manter duas listas de progresso. Nenhuma subtarefa está DONE por existir nesta tabela. Produto mantém NO-GO. Próxima ação: Q17-01.A; backlog não concede autorização a operações externas ou destrutivas descritas para fases futuras.

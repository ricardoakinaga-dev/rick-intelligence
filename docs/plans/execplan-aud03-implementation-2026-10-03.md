# ExecPlan AUD03 — implementação integral do roadmap

## Purpose / Big Picture

Implementar as 36 tarefas do [backlog AUD03](../backlog-auditoria-2026-10-03.md), segundo os oito marcos do [roadmap](../roadmap-auditoria-2026-10-03.md). A conclusão exige correções locais, CI reproduzível, integração real, operação e decisão verificável de promoção. O escopo permanece integral mesmo quando uma dependência externa impedir um marco.

## Context and constraints

Repositório: `/home/ricardo/rick-intelligence`. Trabalho brownfield T4, com autorização do usuário para implementar o plano e coordenar agentes. Preservar a árvore local preexistente e os três projetos legacy. Não há AGENTS aplicável aos diretórios canônicos; `cvg-master-rag-v2/AGENTS.md` é restrito ao legado. Usar dados sintéticos e isolados para regressões. Implantação, assinatura e decisões de domínio dependem da autoridade e dos inputs reais previstos no próprio backlog.

Os registros `.agent/` e `.gauntlet/` existentes pertencem ao programa anterior, com uma ação de inventário instalado pendente. Não sobrescrever esse histórico nem concluir gates por inferência. Esta rodada tem contrato e evidência próprios, sem transformar uma correção local em aceite de produção.

## Current state and evidence

Baseline capturada antes das alterações AUD03: 4.008 arquivos, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, árvore com alterações locais. O snapshot, o histórico da auditoria e a barra v1 estão em [evidence/implementation-aud03-2026-10-03](../reports/evidence/implementation-aud03-2026-10-03/). O arquivo `baseline.json` preserva hashes e status; `audit-baseline/` preserva os resultados originais. Nota 76/100 e verdict NO-GO descrevem a baseline, não a versão corrigida.

## Architecture and contracts

Identidade e autorização pertencem aos packages correspondentes; rotas devem validar actor/resource/action. Pipeline e worker devem conservar posse da operação e estado terminal. Encoding de IDs deve ser inequívoco com leitura/compatibilidade de dados existentes. Provider precisa de conclusão explícita; cliente web precisa invalidar respostas após mudança de autoridade e encerrar streams. CI deve exercer o candidato a partir de inputs declarados e recuperáveis, com pins imutáveis.

Responsabilidade inicial: um builder de identidade/autorização (packages e regressões dessas áreas); um de ingestão/knowledge/worker (pipeline e stores); um de web (parser, sessão, modal, testes e render); Lead integra API, providers, retrieval, SLO, CI, documentação e evidências. Sem edições concorrentes em arquivos compartilhados. Builders não aprovam o próprio trabalho nem criam descendentes. Revisores novos usam contexto não herdado e permanecem read-only.

## Milestones and acceptance

M0 conserva baseline e reproduções. M1 fecha autorização e auditoria; M2 fecha integridade; M3 fecha geração/UI; M4 prova CI e candidato integrado. M5 prova serviços reais e avaliação representativa; M6 prova coleta, recuperação, capacidade e duração; M7 reaudita e vincula promoção ao mesmo candidato. Os critérios obrigatórios são exatamente os 36 critérios em `quality-bar-v1.json`, extraídos dos aceites do backlog. Alteração de medição deve preservar o critério original e ter motivo registrado; resultados ruins não justificam reduzir a barra.

## Concrete Steps

1. Preservar e conferir reproduções; executar regressões de autorização, integridade e web antes dos respectivos fixes; atribuir ownership disjunto.
2. Implementar M1–M3 e bootstrap de M4 em paralelo, integrando arquivos compartilhados sequencialmente.
3. Executar testes focados, suites afetadas, lint/typecheck/build e inspeção em browser a 375/768/1440; obter revisão independente do artefato atual.
4. Corrigir lacunas indicadas pelo reviewer, repetir o teste discriminante e regressão; só depois avançar o aceite local.
5. Revalidar disponibilidade de runtime/inputs externos; executar as tarefas 27–35 no escopo autorizado e identificado, preservando bloqueios reais.
6. Reauditar todos os critérios e produzir o pacote de promoção da tarefa 36. Nenhuma evidência ausente conta como PASS.

## Validation strategy

Python: executar pytest com `--import-mode=importlib -p no:cacheprovider`, PYTHONPATH do root, API/src, worker e todos os packages/src. O ambiente da auditoria em `/tmp/rick-audit-20261002-618htkqr/testenv` permite reproduzir os defeitos; a prova final da CI precisa de ambiente instalado apenas dos locks corrigidos. Web: comandos de `apps/web/package.json`, Playwright com Chromium para render/teclado (fallback quando não houver browser interativo), estados de revogação/SSE/busy e screenshots. CI: executar make validate em uma cópia nova com os inputs formalizados e validar fixtures conhecidamente incorretas. Toda evidência vincula comando, resultado, versão e limitações.

## Progress

- 03/10/2026: baseline de 4.008 arquivos e 49 artefatos históricos preservada; barra v1 com 36 aceites congelada. Implementação ainda precisa de testes e revisão independente.
- 03/10/2026, rodada local seguinte: corrigidos escopo de mutação de coleção, admissão de retrieval vazio, SLO inválida, término JSON/stream do provider e permissões originais na publicação. As primeiras críticas rejeitaram lacunas; reproduções e resultados anteriores permanecem em `lead/review-zeno/` e `lead/review-copernicus/`.
- Identidade: migração legacy agora respeita autoridade atual e limites históricos; validação conserva o teto do snapshot e estreita grants sem depender de aumento de versão. Nova crítica I1 observou 322 regressões públicas e 169 probes aprovados. O Lead executou 16 casos em PostgreSQL descartável, com os 20 hashes de identity/authorization estáveis; IdP instalado permanece não observado.
- Ingestão: tentativa persistida e guard compartilhado protegem efeitos/compensação; encoding inequívoco conserva lookup legacy; catálogo arquivado e tombstone são preservados. Após a crítica de exceções tipadas na saída do guard, o builder entregou tratamento único após commit e 52 regressões novas. Nova crítica independente está em execução.
- Integração API: seeds de demonstração usam grants explícitos; novos usuários vazios continuam negados. Delete mantém fence do store antes do lock da aplicação e usa restauração explícita de metadata/chunks quando existe tombstone. O teste de perda de acknowledgement compara documento, chunks e vetores completos antes/depois.
- CI: lock regenerado e instalado sozinho em ambiente Python 3.12 novo com hashes e `pip check` aprovado. Fixture de campanha tinha imports sem namespace e falhava na coleta; imports corrigidos sem alterar assertions. Checkers usam steps executáveis e parser TypeScript, com negativos; Action continua pinada por SHA. Bundle autêntico v2 restaura controles em checkout novo sem importar aprovações antigas; workflows agora executam o restore antes da validação. Nova crítica CI está em execução.
- Frontend: crítica I1 aprovou invalidação de respostas privadas, fechamento SSE e foco do modal em 375/768/1440. A integração do resumo de cobertura foi corrigida e revista separadamente: dez módulos, 744/788 linhas, piso de 85% preservado; o comando `make web-coverage` passa. Fixtures sintéticas não comprovam backend/IdP externo. Lead inspecionou três renders e conserva o parecer da matriz independente em `lead/review-ptolemy/`.
- Checks locais com comando, exit code e hashes em `lead/`: API 775 aprovados antes da implementação AUD03-06; domínio/worker 1.068 aprovados e 25 opt-in pulados; tooling 588 aprovados e 74 opt-in pulados; migrations/restore PostgreSQL 147 aprovados; knowledge live quatro aprovados; comandos reais UNIT e validate/ops-static/compose-static aprovados. Contagens são por execução e possuem sobreposição; não representam um total único nem aceite global.
- AUD03-06 está em implementação separada, nas fronteiras API de auditoria obrigatória. As evidências anteriores de arquivos que mudarem ficam stale; repetir a regressão integrada e a crítica após a entrega. Política clínica, inventário instalado, corpus autorizado, IdP/provider reais, budgets de operação e autoridade de promoção continuam pendentes no escopo integral.
- Nova crítica de ingestão rejeitou AUD03-09/11: exceções tipadas após commit ainda eram propagadas em reindex, e archive concorrente podia vencer a leitura final do catálogo. AUD03-08/10/12 passaram no recorte observado, inclusive PostgreSQL. Rework do mesmo builder em andamento; relatório e fontes preservados em `lead/review-pascal/`.
- Nova crítica I1 de provider/retrieval/SLO aprovou AUD03-15 e rejeitou 13/14/19. O serviço público ainda reidratava com ACL vazia; conclusão tipada sem motivo assumia sucesso; ferramenta após terminal era consumida; contagens extremas podiam ser healthy por arredondamento. Relatório e 43 artefatos em `lead/review-locke/`. Correções de 13/19 têm 150 testes aprovados e cinco integrações Qdrant puladas. Correções de 14 têm 415 regressões e 74 probes preservados aprovados; uma crítica nova dos quatro critérios está em execução. Reexecutar probes antigos é regressão, não nova independência.
- CI: crítica I1 aprovou 21/22/23, mas rejeitou 24 por heredoc e import TypeScript usado em tipos. Correções focadas tiveram 20 testes aprovados; a crítica seguinte encontrou texto entre aspas multiline contado como comando e wrapper inexistente aceito por basename. O builder de CI está corrigindo esses casos e condições desabilitadas. Evidências anteriores de checkers ficam stale após a entrega; não registrar AUD03-24 como PASS enquanto faltar revisão válida.
- Toolchain: Node 22.19.0/npm 10.9.3 instalados apenas em `/tmp`, com SHA256 do archive conferido contra o manifesto oficial. Typecheck e build do frontend passaram nessas versões, com 59 hashes estáveis. O host Node 24 não serve de prova de paridade; a nova execução está em `lead/web-pinned-toolchain-{check,build}.command.json`.
- Redis descartável: sete verificações reais aprovadas, incluindo pause/unpause do próprio container, negação com circuit open e recuperação. Resultado `PASS` é restrito à semântica local; `production_safe=false`, sem TLS, inventário instalado ou aceite distribuído. Logs, configuração pública e observações ficam em `runtime/` e `lead/redis-live-fault-corrected.command.json`.
- Qdrant descartável v1.12.5: o ensaio real revelou descompasso do harness com índice híbrido e wire de cleanup, além de negativo que tratava ponto autorizado como vazamento. Corrigidos payloads sintéticos com texto, remoção de alias, comprovação de ausência e negativo que rejeita todos os IDs estrangeiros. FAIL agora prevalece sobre dependência ausente no resumo. Dez regressões do gate aprovadas; 17 verificações reais aprovadas, com timeout/retry ainda pendentes nesse primeiro corte. Todos os resultados anteriores permanecem preservados; não há object store ou golden path completo observado.
- Qdrant, corte seguinte: wrapper do laboratório pausa somente o container identificado no início da função original de fault policy, preserva todos os HTTP calls/assertions e o recupera antes de cleanup. Retry/circuit e timeout passaram; a faixa vetorial termina em PASS, enquanto o gate combinado mantém BLOCKED_EXTERNAL por ausência de object store. Pausa observada de 10,35 s e unpause confirmado em `runtime/qdrant-fault-observations.json`. Isto é instrumentação explícita de falha local, não golden path/chaos instalado.
- Documentação: 197 arquivos Markdown autorais sob docs, 459 links locais inline conferidos, zero destinos quebrados e hashes anteriores/posteriores iguais. Evidência em `lead/docs-link-check-current.json`; exclui archives de evidência e exemplos em blocos de código e não valida URLs externas ou toda a gramática Markdown. INDEX agora aponta para o checkpoint das 36 tarefas, preservando os estados congelados do backlog e a baseline 76/100.
- Nova crítica I1 da fronteira pública aprova AUD03-13/15/19, com 79 hashes estáveis, 592 regressões aprovadas e 131 probes aprovados. Rejeita AUD03-14 por seis negativos: frames após DONE ignorados e SSE vazio/whitespace sem erro tipado equivalente a JSON. Rework4 do provider em andamento; relatório, probes, sentinels e histórico do harness preservados em `lead/review-maxwell/`. A aprovação dos três critérios é local e não fecha a integração global.
- Entregas seguintes: checker rework3 tem 118 regressões próprias, três probes anteriores e workflow atual aprovados; Lead conferiu hashes das duas fontes e de todos os artefatos declarados. Provider rework4 tem 472 regressões aprovadas, dez controles diretos antigos aprovados e um probe público antigo ainda retorna exit 1 por esperar resultado em vez do erro tipado seguro. Essa divergência está preservada e depende do novo crítico. Gauss e Aquinas são revisores novos, sem histórico herdado, respectivamente de CI e provider; nenhuma entrega recebe autoaprovação.
- AUD03-06 entregue: 884 regressões API aprovadas e seis opt-in puladas; execução separada com seis casos PostgreSQL reais aprovada, em schemas isolados. Reviewer Aristotle está verificando atomicidade, workflow, idempotência e reconciliação. Lead executou o gerador canônico `make api-contract`: 55 paths, incluindo os três novos endpoints de operação. Somente `apps/api/openapi.json` mudou entre os 73 inputs conferidos. Seu conteúdo anterior está preservado em `lead/openapi-before-audit06.json`; geração é uma mutação esperada, não sentinel de fontes estáveis.
- Crítica I1 de ingestão seguinte rejeitou 09/11/12 e aprovou 08/10 no recorte observado. Dos 126 probes independentes finais, 103 passaram e 23 produziram contraexemplos materiais: callback de conclusão após commit, alias público de catálogo em memória e restore com linhagem alterada. Houve 319 regressões, 25 PostgreSQL e dois Qdrant aprovados, com correções de harness registradas separadamente. Os 35 hashes permaneceram estáveis; 40 artefatos foram arquivados em `lead/review-dirac/`. Builder Faraday corrige os três grupos em rework3 usando o ambiente instalado exclusivamente dos locks. Arquivos API permanecem congelados durante a crítica de auditoria.
- Object store: pulls do release MinIO declarado no Docker Hub e no Quay falharam; o cliente HTTP real também recebeu 410 ao consultar o checksum do binário oficial legado. O browser tinha apresentado conteúdo cacheado, que não comprova disponibilidade atual para download. Não houve binário baixado, container MinIO iniciado, autenticação nova ou substituição de versão. `runtime/object-store-image-discovery.json` e `lead/minio-binary-lab.command.json` preservam essa dependência externa; object store e golden path permanecem não demonstrados.
- Nova crítica independente de auditoria: AUD03-03 aprovado e AUD03-06 rejeitado por reconciliação concorrente ao callback em execução. O status podia terminar `reconciled_no_effect` apesar de delete efetivado depois. Quatro probes reproduziram a corrida em memória, SQLite, PostgreSQL e HTTP local; 19 probes positivos e 45 regressões passaram. Os 41 hashes primários ficaram estáveis e os 15 dependencies conferidos separadamente. Trinta e dois artefatos arquivados em `lead/review-aristotle/`; Jason implementa exclusão/fencing real para execução versus reconciliação, sem substituir a barreira por uma afirmação de operador.
- Tooling atual aprovado: 701 testes e 74 opt-in pulados, com 153 hashes estáveis. `make ops-static compose-static` aprovado com 75 hashes estáveis, oito checksums de migrations e 14 serviços renderizados em cada Compose; não iniciou runtime instalado. Corpus adversarial sintético passou na validação estrutural de oito categorias; isso não constitui execução de ataques contra modelos reais. O runner foi corrigido para vincular arquivos explicitamente declarados independentemente da extensão, pois o primeiro manifesto desse corpus omitiu JSONL; repetir esse pequeno check com o input efetivamente incluído.
- Quatro entregas posteriores conferidas por hash: ingestão rework3 resolve os 23 contraexemplos de Dirac e passa nos 126 probes; auditoria rework2 resolve os quatro de Aristotle e passa nos 23 probes; provider rework5 rejeita envelopes contraditórios de erro e passa nos 119 probes de Aquinas; CI rework4 resolve os dez falsos aceites de Gauss e corresponde a 87/87 expectativas. Esses replays não substituem novas críticas. Os quatro reviewers novos são Confucius, Laplace, Huygens e Fermat, read-only, contexto fresco e sem descendentes.
- Integração do catálogo: Lead corrigiu somente o setup dos três modos de archive em `test_decision_policy_publication.py`, persistindo o estado pelo writer público. As assertions foram mantidas e os três passaram. API completa atual: 1.062 aprovados e 18 opt-in pulados, 278 hashes estáveis; domínio/worker: 1.250 aprovados e 74 opt-in pulados, 181 hashes estáveis. Contagens se sobrepõem; arquivos de comando/raw logs em `lead/*integrated-wave4*`.
- O comando Make canônico encontrou uma lacuna de integração apesar dos pytest amplos: três novos módulos de teste de package importam helpers da API que `api16-domain` corretamente não declara no PYTHONPATH. Contracts/providers/locking/professor passaram; domínio falhou na coleta. Preservado em `lead/unit-make-integrated-wave4.log`. Após término da crítica de ingestão, mover esses testes de integração para `apps/api/tests`, mantendo conteúdo/assertions e repetir Make/API; não ampliar implicitamente dependências dos packages.
- Redis, duas réplicas HTTP: corrigido setup que chamava create_user sem actor e depois criava IDs diferentes para o mesmo email em cada processo. O ensaio agora usa a seam explícita de seed do store canônico dev para representar o mesmo principal, com grants vazios preservados; não altera a política de bucket. Nove testes de contrato/setup passaram e o gate real terminou PASS com 124 hashes estáveis, `production_safe=false`. IdP real e revogação distribuída seguem pendentes. O harness inicialmente reutilizou um filename de output; o resultado inicial foi reconstruído explicitamente como observação, sem hash de bytes originais, e o resultado intermediário foi preservado. Outputs novos exigem nome único e recusam overwrite. O erro de campo no primeiro teste novo foi corrigido para o contrato `allowed_collection_ids`; nenhum negativo foi removido.
- Checkout novo: 4.063 arquivos projetados com hashes, Node 22.19.0/npm 10.9.3 e `npm ci` real. Antes do restore, controles ausentes falharam; depois, validate/check-clean/idempotência passaram. Corrupção/ausência de fonte ou controle restaurado continuou falhando e preservando a corrupção para inspeção. Artefatos em `lead/control-restore-final-projection/`. Esse ensaio demonstra restore/validação do candidato local; ainda não comprova todos os jobs remotos nem a integração Make que falhou acima.
- Novo controle Gauntlet criado somente em clone sintético próprio `/tmp/rick-aud03-gauntlet-final-qpln9041/candidate`, com os 36 aceites originais e budgets/capabilities de concorrência 4. O run preserva os históricos anteriores e não importa suas aprovações. Zero rounds e verificação ausente na inicialização; nenhum PASS decorre desse bootstrap. Ajustes posteriores de teste/documentação exigem recaptura e binding atual antes da crítica final, como registrado em `lead/gauntlet-final-init.json`.
- Críticas seguintes preservadas: Fermat rejeita 24 por declarações ambient que escondem loaders, variantes Module.createRequire e wrapper inválido antes das suites; Huygens rejeita 14 por SSE UTF-8 inválido reparado e publicado como evidência aprovada, enquanto JSON rejeita; Confucius aprova 08/10/12 e rejeita 09/11 por CancelledError nas fronteiras de publicação e aliases públicos arquivados que normalizam para coleção canônica ativa. Arquivos em `lead/review-{fermat,huygens,confucius}/`. Reworks CI5/provider6/ingestão4 em andamento; anteriores positivos ficam stale no recorte alterado.
- Laplace declarou sua revisão I1 INVALID: abriu por engano o documento arquitetural escrito pelo builder, que continha racional e resultados anteriores. Seus 119 probes e 66 regressões positivos são observações recuperáveis, sem aceite independente. Trinta e nove arquivos em `lead/review-laplace-invalid/`; uma nova crítica de auditoria será criada após a integração API de ingestão. Não inferir aprovação de ausência de falhas reproduzidas por esse contexto contaminado.
- Após fechamento de Laplace, ownership do builder de ingestão foi ampliado explicitamente para `knowledge_service.py` e `ingestion_service.py`, só para canonicalização de aliases e cancelamento do refresh após commit; rotas/helpers de audit e identity permanecem fora do recorte. Os três módulos de integração podem ser relocados com bytes/assertions preservados para API/tests. Euclid revisa a instrumentação local de runtime em contexto fresco; só configuration manifests de laboratório são permitidos, sem relatórios anteriores e sem pause Qdrant enquanto builder o utiliza.
- Fonte MinIO: a API oficial do GitHub confirmou o tag anotado assinado/verificado `e56c69a9d192e22ab20632b051f73b116c9a10f7`, commit `8c2c92f7afdc8386b000c0cb57ecec2ee1f5bcb0`, com toolchain Go 1.23.6. A fonte está disponível, embora OCI/binário oficial tenham falhado. Host não tem Go; tentativa limitada de obter a toolchain exata para fixture local está em andamento. Nenhum build de fonte terá paridade presumida com a imagem declarada, nem fechará provider/IdP/corpus ou promoção.
- Build MinIO local, tentativa inicial: SDK Go 1.23.6-alpine obtido por digest `f8113c4b13e2a8b3a168dceaee88ac27743cc84e959f43b9dbd2291e9c3f57a0`; archive do commit exato tem 23.941.760 bytes e SHA `e407cbe4385bc51128f99fdfe94fb255330042e3c88a8fc0d8da0c4a7eded3d0`. Build readonly com módulos pinados falhou por falta de espaço no tmpfs de 256 MiB, após 142 s, não por falha do adapter S3. Fonte/go.mod/go.sum e o primeiro log foram preservados. Retry usa GOTMPDIR em cache/scratch próprio no disco, limite agregado 3 GiB, CPU/RAM/tempo inalterados e shutdown do próprio builder em excesso. Não altera thresholds de produto ou presume sucesso; arquivos `runtime/minio-source-build*`.

## Discoveries and decisions

- Os ledgers anteriores apontam para inventário externo e não comprovam a resolução dos 24 novos achados. Preservar a autoridade anterior e usar execução AUD03 rastreável.
- A disponibilidade de ambiente não será inferida do estado antigo: conferir processos, ferramentas e configuração sem expor credenciais.
- Visual: conservar identidade, tokens e componentes atuais; corrigir privacidade, término, foco e recuperação. Não há necessidade de novos assets raster. O aceite visual deriva de renders e interação, nunca só da leitura de TSX.
- Harness Python: a primeira execução ampla com importlib inferiu um rootdir de package e produziu nomes de módulo não importáveis nos processos filhos do parser. Os dois casos foram repetidos com `--rootdir=.` e aprovados, seguidos da regressão de 1.068 casos e dos comandos canônicos Makefile sem mudança no parser. Falha do harness permanece registrada em `lead/domain-locked-wave2.log`.
- Docker está disponível neste corte. PostgreSQL, Redis e Qdrant do Lead são laboratórios descartáveis próprios, identificados em `runtime/`, com credenciais sintéticas guardadas em arquivos privados fora do repositório quando utilizadas. Eles não substituem o inventário de dados instalado. O bloqueio inicial do circuit breaker Redis foi posteriormente exercitado com falha real e recuperação; ambas as evidências são conservadas.
- SLO: budgets são interpretados pela representação decimal configurada (0.3 significa 30%). A decisão compara frações exatas de contagens inteiras; o `error_rate` exibido continua aproximação float e não determina healthy/breach. Preservar as bordas decimais comuns e distinguir no_data de ausência de coleta externa.
- Controle de recursos: houve sobreposição breve de cinco agentes ao agendar nova crítica. O revisor recém-criado foi fechado sem parecer aceito; quatro builders/revisores constituem o envelope atual. Registro explícito em `lead/resource-reconciliation.json`. A inicialização Gauntlet anterior em projeção de controle ainda não é um run de produto válido, nem comprova PASS; criar um run vinculado ao candidato estável com envelope correto antes da crítica final.

## Risks and external boundaries

Concorrência e compatibilidade de IDs exigem revisão independente e ensaios determinísticos. Atomicidade do audit exige confirmação de transações/outbox, incluindo persistência. Política de feedback e corpus/limiares são decisões pendentes quando não houver autoridade atual. Inventário de dados instalados, IdP, serviços, collector, budgets e assinatura continuam no escopo; indisponibilidade é BLOCKED_EXTERNAL e não conclusão.

## Recovery and rollback

Reler este plano, backlog, barra e evidências atuais; comparar arquivos com baseline para distinguir alterações AUD03 de trabalho preexistente. Conferir os handles vivos antes de retomar comandos/agentes; um timeout não prova término. Reverter apenas patches AUD03 identificados quando necessário, preservando alterações anteriores. Nunca reaplicar migration ou ação externa com base apenas na ausência de log. Próxima ação: integrar a entrega de AUD03-06, validar a unidade atômica e obter crítica independente antes da nova regressão integrada. Enquanto o builder trabalha, concluir as críticas disjuntas de provider, ingestão e CI e preparar os ensaios próprios de runtime.

## Results and retrospective

Em andamento. Resultado global não demonstrado; registrar provas e lacunas ao concluir cada unidade.

## Continuação de 03/10/2026

Retomada a partir do checkpoint v1 e dos arquivos entregues após seu timestamp;
o estado anterior em `.agent/` permanece preservado. As relocations de três
testes para API/tests já estavam concluídas. Make UNIT passou, e API passou em
1.172 testes, mas uma medição paralela misturou o arquivo `.coverage` do worker
com o da API. A reprodução original permanece em
`lead/continuation-20261003-api.command.json`. Arquivos de coleta separados no
Makefile corrigem a colisão; a execução real `make -j2 api-coverage
worker-coverage` passou com os mesmos pisos de 75/74. Essa observação precede
as próximas alterações funcionais e não é evidência integrada delas.

Novas críticas read-only, sem histórico herdado, reprovaram AUD03-06 por
revogação administrativa sem unidade auditável, replay de reset e reconciliação
inacessível após falha de outcome; AUD03-14 por recusa ignorada e tool calls
descartadas no fallback; AUD03-24 por loaders/prefixos/dependências de job que
produzem falso aceite; AUD03-09 por cancelamento concorrente à recuperação de
acknowledgement após commit. Relatórios e bytes originais estão preservados em
`lead/continuation-{audit,provider,ci,ingestion}-review/`. Revisores que passaram
a implementar são builders dessa correção; seus replays não constituem nova
aprovação independente. Ownership atual: Descartes em admin/audit operations,
James em checkers, Bernoulli em pipeline/job stores, Lead em provider/S3/Make.
Boyle revisa provider e S3 no artefato corrigido, sem editar fontes.

O MinIO compilado do commit exato estava pronto após a interrupção. Um harness
novo, `runtime/minio_source_object_gate.py`, identifica o build, cria apenas
container/bucket sintéticos em loopback e remove o próprio container em todas
as saídas. A primeira tentativa falhou no setup; a segunda revelou DELETE
204 para chave ausente contrariando o boolean prometido pelo adapter. A
correção verifica HEAD antes de DELETE, explicita o limite de concorrência e
preserva fechamento/erros. Trinta e oito testes de storage/gate e 72 testes de
integração afetada passaram. O ensaio real seguinte passou em 12 verificações,
com cleanup observado em `runtime/minio-source-object-908e713609a815b9.json`.
Fonte compilada localmente não demonstra paridade OCI, sistema instalado ou
golden path completo.

Frontend: 76 testes unitários, typecheck e build passaram em Node 22.19.0/npm
10.9.3, com 59 hashes autorais estáveis. O resumo canônico mede 744/788 linhas
(94,42%), piso 85. A matriz browser final ainda será repetida após estabilizar
os builders. Próxima ação desta continuação: integrar as três correções
pendentes, obter críticas independentes novas e repetir regressão/contrato
sobre o artefato final. Promoção continua NO-GO.


### Fechamento local desta continuação

Os contraexemplos adicionais foram corrigidos em ownership separado e as
críticas finais frescas aceitaram os recortes locais: AUD03-06 (69 probes),
AUD03-14 (123), AUD03-08..12 (20 probes/175 regressões, 12 condicional) e AUD03-24
(16 controles TS de runtime/434 regressões, contrato estático limitado).
Arquivos de crítica, falhas de harness, recusas originais e replays dos builders
foram preservados. A crítica CI que expôs resumos anteriores é INVALID como
aceite independente; as posteriores não herdaram esse contexto. A revisão de
ingestão mantém binding do seu recorte; duas alterações administrativas
posteriores no manifesto amplo são divulgadas separadamente.

Resultado final: API 1.305/18 skips, worker 154, ferramentas 1.100/74 skips,
browser de produção 339 sem skips; pisos API/worker/web 75/74/85 preservados,
medições 76,92/75,32/94,42. São contagens sobrepostas, não total único. Lint,
typecheck, validate, controles e Compose estático passaram; OpenAPI preserva
os mesmos bytes e 55 rotas. O Lead observou 15 testes próprios de auditoria em
schemas PostgreSQL sintéticos e 53 testes de conhecimento/ingestão em tenants
únicos do laboratório já migrado. MinIO próprio passou 12 verificações S3,
sem paridade OCI ou aceite de produção.

A composição Make API/worker declara storage para não depender da ordem de
coleta de outro teste. A reprodução isolada passou nos 126 casos após a
correção. O destino antigo de web-e2e sobrescreveu 251 arquivos de controles
históricos; as novas observações foram arquivadas e os bytes autenticados
originais recuperados. Agora o destino padrão é `.runtime/qa/web-e2e`; uma
nova execução browser de 339 casos e validate confirmam o isolamento.

O [checkpoint v2](../reports/evidence/implementation-aud03-2026-10-03/execution-checkpoint-v2.json)
e o [relatório desta continuação](../reports/continuacao-melhorias-2026-10-03.md)
registram fontes, comandos, hashes, binding das críticas e limitações. V1,
barra original e controles anteriores estão preservados. Rodada local validada;
promoção permanece NO-GO e nenhum dos 36 aceites integrais é declarado.
Próxima ação: conferir v2/hash antes de retomar e avançar AUD03-27..36 com
inventário instalado D02, IdP/provider/corpus, collector, budgets de
carga/DR/soak e autoridade de assinatura efetivamente fornecidos. AUD03-07
segue fechado até definição da política clínica; não inferir aprovação desses
insumos de fixtures ou de laboratórios descartáveis.

### Unidade local de 04/10/2026 — preflight executável de 0008

Retomada pelo checkpoint v2 e pelo complemento de bytecode do relatório de
03/10. O plano antigo em `.agent/` continua apontando para inventário externo
D02 e permanece preservado. Esta unidade prepara AUD03-27 localmente, sem
acessar uma base instalada nem alterar migrations. Perfil brownfield, atividade
BUILD/VERIFY, escopo de ferramenta operacional somente de leitura.

Aceite congelado: (P1) PostgreSQL impõe READ ONLY e REPEATABLE READ; tentativa
de escrita é rejeitada; (P2) JSON contém somente os quatro totais agregados,
identificador explícito de snapshot e metadados da execução/fontes, sem DSN ou
conteúdo de linhas; (P3) quatro zeros retornam 0, conflito retorna 1, resultado
incompleto ou erro retorna 2; (P4) conexão, consultas e espera por locks têm
limites e erros do driver são redigidos; (P5) testes em container próprio
cobrem estado anterior a 0008, dados incompatíveis e preservação de dados,
constraints e histórico. Revisão separada será autorrevisão, pois não há
capacidade de subagentes disponível nesta sessão.

Implementação: aproveitar o SQL agregado existente em
`docs/operations/0008-scope-preflight.sql`, criar CLI e alvo Make, documentar
uso e limites. Verificação: testes unitários de contrato e subprocesso,
PostgreSQL descartável opt-in e regressões de migrations. Nenhum sucesso
desses ensaios encerra AUD03-27 ou autoriza aplicar a migration.

Unidade concluída localmente: CLI, alvo Make e runbook implementados. Passaram
20 testes unitários, regressão de 154 casos de migrations/preflight, ops-static
com 297 testes de CI e 27 verificações finais após arquivar as saídas JSON
sintéticas. As contagens se sobrepõem. O PostgreSQL 16.15 descartável impôs
READ ONLY, rejeitou escrita, limitou espera por locks e preservou histórico,
dados e constraints. Autorrevisão e teardown estão vinculados no
[relatório de 04/10](../reports/continuacao-melhorias-2026-10-04.md).

Próxima ação para AUD03-27: obter a história instalada e constraints do snapshot
autorizado D02 e executar o preflight nele. Esse aceite externo permanece
pendente; NO-GO global e controles históricos permanecem preservados.

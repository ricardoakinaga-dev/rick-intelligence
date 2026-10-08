# Relatório de reauditoria — RICK Intelligence

**Data:** 24/09/2026. **Nota geral:** 72/100. **Referência anterior:** 70/100 em 17/09/2026.

**Parecer técnico:** a implementação evoluiu, mas a entrega ainda contém bloqueadores funcionais, dependências com vulnerabilidades conhecidas e lacunas de validação integrada. Não há evidência suficiente para aprovar produção ou atribuir qualidade AAA ao produto completo. Este parecer não altera gates, aprovações ou o estado do projeto.

## 1. Escopo e método

A revisão cobre o checkout local de `/home/ricardo/rick-intelligence`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, **incluindo as alterações não commitadas já existentes**. Portanto, a nota não descreve exclusivamente esse commit nem uma instalação em produção. No início havia 50 arquivos rastreados modificados, além de documentos e outros arquivos não rastreados.

Foi retomada a [auditoria de 17/09](reports/relatorio-auditoria-2026-09-17.md), comparando seus achados com as correções atuais, os pontos de integração, testes executáveis e o [estado de implementação anteriormente registrado](reports/estado-implementacao-2026-09-17.md). As áreas alteradas receberam inspeção direcionada; áreas sem mudanças relevantes foram revalidadas principalmente pelas respectivas suítes. Não foi uma revisão integral de cada linha ou dos três sistemas legados.

Mantive os 26 itens e os pesos da auditoria anterior:

| Dimensão considerada na nota de cada item | Peso |
|---|---:|
| Implementação frente ao escopo documentado | 40 |
| Correção e tratamento de falhas | 25 |
| Qualidade das evidências e testes | 20 |
| Integração e comprovação operacional | 15 |

As notas são julgamentos técnicos orientados por essas dimensões, não uma medição automática, certificação ou percentual de conclusão. A média simples é **1.877 / 26 = 72,19**, arredondada para **72/100**. A evolução de dois pontos não significa que os bloqueadores restantes sejam pequenos.

**Confiança:** alta nos resultados de testes, na falha de navegador e nos caminhos de código citados; moderada na extrapolação para operação distribuída, que não foi executada. Não houve revisão independente por outro auditor nesta rodada.

Os logs desta execução foram preservados em [evidências da auditoria](reports/evidence/auditoria-2026-09-24/manifest.json), com hashes SHA-256 e versões Python observadas.

## 2. Notas por item

| Nº | Item analisado | 17/09 | 24/09 | Fundamentação e principal limite |
|---:|---|---:|---:|---|
| 1 | Arquitetura e separação de responsabilidades | 85 | **85** | Aplicações e pacotes possuem fronteiras verificáveis; `make validate` passou. A consolidação com três legados ainda exige manutenção de interfaces e caminhos paralelos. |
| 2 | Documentação e aderência ao estado atual | 65 | **64** | Os relatórios registram pendências com transparência, mas há referências históricas e mensagens de bloqueio que não refletem a nova observação do Docker. Evidências antigas não comprovam o checkout atual. |
| 3 | Identidade e sessões | 80 | **80** | Os testes atuais de autenticação, identidade e revogação passaram. O fluxo completo de sessões sobre PostgreSQL real não foi exercitado nesta rodada. |
| 4 | Autorização e isolamento | 83 | **83** | Suítes de permissões e negativos passaram; o retrieval revalida escopo. Falta demonstrar a mesma proteção em uma matriz integrada com todos os armazenamentos externos. |
| 5 | Kernel HTTP e controles defensivos | 84 | **76** | Há autenticação, limites e tratamento de erros testados. Entretanto, a API fixa e utiliza versões de dependências cobertas por avisos oficiais de negação de serviço. Ver A24-01. |
| 6 | Contratos e compatibilidade | 65 | **82** | Contratos de chat, metadados e `tool_calls` foram fortalecidos, com regressões passando. Persistem limites de comprovação com consumidores externos reais. |
| 7 | Knowledge: documentos, versões e proveniência | 81 | **81** | A suíte de domínio passou, preservando a base de identificação, escopo e proveniência. Não foi demonstrada equivalência operacional completa entre os armazenamentos externos. |
| 8 | Ingestão e reindexação | 76 | **85** | Embeddings e indexação agora usam lotes limitados, validam contagem e dimensões e verificam cancelamento. Falta execução integrada com documentos e embeddings representativos. |
| 9 | Retrieval e busca híbrida | 69 | **74** | O caminho por SDK ganhou busca sparse e dense. O caminho HTTP usado na composição canônica continua dense-only. Ver A24-05. |
| 10 | Evidence: fontes e citações | 81 | **84** | Validações estruturais, proveniência e contratos passaram nos testes. Uma citação estruturalmente válida ainda não comprova apoio semântico a cada afirmação. |
| 11 | Decision: responder, abster e escalar | 70 | **45** | O motor existe, mas o adaptador canônico fixa risco e intenção como desconhecidos, levando à escalação inclusive com boas evidências. Ver A24-02. |
| 12 | Professor e geração fundamentada | 70 | **80** | A resposta sem qualquer marcador de citação passou a ser rejeitada; 60 testes do pacote passaram. A integração de decisão continua bloqueando o caminho útil de geração. |
| 13 | Integração com providers | 83 | **86** | Streaming, erros e contratos de ferramentas receberam correções; 76 testes passaram. Não houve chamada a modelo real nesta auditoria. |
| 14 | Avaliação da qualidade RAG | 63 | **55** | A verificação por grupo é mais rigorosa, mas o pacote atual exige uma meta impossível para um de seus casos. O comando de avaliação falha. Ver A24-04. |
| 15 | Chat, histórico e apresentação das evidências | 72 | **82** | A conclusão de streaming e seu replay preservam metadados canônicos; a suíte da API passou. A geração útil ponta a ponta não foi comprovada. |
| 16 | Documentos, busca e ingestão pela interface | 68 | **64** | A seleção de coleção foi adicionada, mas o upload inicial envia uma coleção vazia; o teste em navegador falhou. Retry de arquivo binário ainda usa texto. Ver A24-03. |
| 17 | Administração, auditoria e casos | 71 | **73** | A intenção administrativa é registrada antes da alteração e falhas de conclusão são explicitadas. Falta reconciliar registros pendentes e garantir recuperação consistente. Ver A24-06. |
| 18 | Containers e composição do ambiente | 52 | **68** | Foram corrigidos o encaminhamento da identidade exigida pelo factory e a configuração de regras do Prometheus. As duas topologias renderizam 14 serviços; a stack completa não foi iniciada. |
| 19 | Jobs, PostgreSQL e migrações | 66 | **68** | Testes de filas passaram e expressões da migração foram corrigidas. Alterar a migração 0005 deixa pendente o upgrade de instalações que já a aplicaram. Ver A24-07. |
| 20 | Worker e ciclo de vida | 65 | **73** | O encerramento agora recebe orçamento integral e respeita o resultado assíncrono. A suíte passou; comportamento com processos reais, falhas e reinício permanece sem prova integrada. |
| 21 | Redis e coordenação distribuída | 71 | **71** | Os 54 testes de locking passaram. Não houve validação real de múltiplas réplicas, leases e falhas de rede nesta rodada. |
| 22 | Storage e inicialização persistente | 66 | **66** | Os 26 testes locais de storage passaram. Integração S3, inicialização e restauração do conjunto persistente não foram demonstradas. |
| 23 | Observabilidade e SLO | 55 | **67** | A entrega padrão de eventos ganhou fila e concorrência limitadas, contadores e shutdown. O caminho explícito `timeout=None` permanece síncrono; coletor e alertas não foram exercitados. |
| 24 | Recuperação, capacidade e tolerância a falhas | 45 | **45** | Os testes locais de backup passaram. Não há novas medições de RPO/RTO, carga, caos ou estabilidade prolongada. |
| 25 | CI e promoção de release | 63 | **60** | Verificadores locais são conservadores, mas existem etapas obrigatórias sem executor conectado, uma avaliação falhando e alterações sem commit. A CI remota não foi consultada. Ver A24-09. |
| 26 | Qualidade global dos testes | 74 | **80** | A suíte oferece regressões úteis e o navegador capturou uma falha concreta. Ainda há dependência de mocks, compilação Python tratada como typecheck e lacunas operacionais. |

As notas de interface avaliam implementação e comportamento observado no teste delimitado, não uma aprovação geral de aparência, acessibilidade ou responsividade.

### Evidências da tabela

| Áreas | Fontes diretamente verificáveis |
|---|---|
| Arquitetura e documentação | [README](../README.md), [validação atual](reports/evidence/auditoria-2026-09-24/validate.log), [relatório anterior de implementação](reports/estado-implementacao-2026-09-17.md). |
| Identidade, autorização e kernel | [rotas de autenticação](../apps/api/src/routes/auth.py), [resultado da API](reports/evidence/auditoria-2026-09-24/api16-root-host.log), [suíte de fundamentos](reports/evidence/auditoria-2026-09-24/foundation-release-tests.log), A24-01. |
| Contratos, providers e Professor | [contratos](../packages/contracts/src/rick_contracts/providers.py), [cliente provider](../packages/providers/src/rick_providers/client.py), [orquestração](../packages/professor/src/rick_professor/orchestration.py), [resultados por pacote](reports/evidence/auditoria-2026-09-24/remaining-tests-host.log). |
| Knowledge, ingestão e retrieval | [pipeline](../packages/ingestion/src/rick_ingestion/pipeline.py), [backends](../packages/retrieval/src/rick_retrieval/backends.py), [232 testes de domínio](reports/evidence/auditoria-2026-09-24/api16-domain.log). |
| Evidence e Decision | [adaptador canônico](../apps/api/src/services/professor_backend.py), [motor de decisão](../packages/decision/src/rick_decision/layer.py), [regressões do gate](../apps/api/tests/test_evidence_decision_gate.py). |
| Chat e documentos | [serviço de chat](../apps/api/src/services/chat_service.py), [página de documentos](../apps/web/app/app/documents/page.tsx), [falha no navegador](reports/evidence/auditoria-2026-09-24/browser-upload.log). |
| Administração e persistência | [rotas administrativas](../apps/api/src/routes/admin.py), [auditoria SQLite](../apps/api/src/services/sqlite_audit.py), [testes de auditoria](../apps/api/tests/test_audit_factory.py). |
| Containers, worker e migrações | [Compose](../docker-compose.dev.yml), [entrypoint](../infrastructure/docker/worker-entrypoint.py), [runner de migração](../infrastructure/scripts/migrate.py), [verificação de topologia](reports/evidence/auditoria-2026-09-24/compose-static.log), [verificação operacional estática](reports/evidence/auditoria-2026-09-24/ops-static.log). |
| Redis, storage e recuperação | [resultados de locking, storage, jobs e backup](reports/evidence/auditoria-2026-09-24/remaining-tests-host.log). Esses resultados não comprovam operação distribuída. |
| Observabilidade, CI e testes | [entrega de eventos](../packages/observability/src/rick_observability/events.py), [verificador de promoção](../scripts/state_of_art/triple_aaa_verify.py), [workflow](../.github/workflows/state-of-art-quality.yml), [typecheck executado](reports/evidence/auditoria-2026-09-24/typecheck.log). |

## 3. Achados prioritários

Prioridade P0 significa correção necessária antes de exposição operacional ou de declarar o fluxo principal utilizável. P1 significa fechamento necessário para uma entrega integrada confiável. A prioridade considera este produto; não substitui a classificação dos avisos de segurança.

### A24-01 — Dependências com avisos oficiais de negação de serviço

**Prioridade P0; risco alto; confirmado por versões e avisos, sem exploração.** O manifesto fixa `python-multipart==0.0.9` e `fastapi==0.109.2` em `apps/api/pyproject.toml:6`; o Dockerfile repete esses pins em `infrastructure/docker/api.Dockerfile:43–46`. No Python utilizado nesta auditoria estão instalados `python-multipart 0.0.9` e `starlette 0.36.3`, conforme o manifesto de evidências.

O aviso oficial [GHSA-59g5-xgcq-4qw3 / CVE-2024-53981](https://github.com/Kludex/python-multipart/security/advisories/GHSA-59g5-xgcq-4qw3) inclui versões de python-multipart anteriores a 0.0.18 e descreve consumo excessivo de CPU ao processar multipart malformado. O aviso [GHSA-f96h-pmfr-66vw / CVE-2024-47874](https://github.com/Kludex/starlette/security/advisories/GHSA-f96h-pmfr-66vw) inclui a versão de Starlette observada e registra correção em 0.40.0 para consumo de memória com campos multipart.

Há um caminho de parsing em `apps/api/src/routes/knowledge.py:757`, com guardas anteriores. Portanto, a constatação é de componentes afetados em um caminho relevante, não de exploração anônima demonstrada nem de ausência total de proteção. Não foi executado ataque, scanner completo ou inspeção de uma imagem em produção.

**Fechamento:** atualizar o conjunto compatível FastAPI/Starlette/multipart, verificar dependências resolvidas e imagem final, e repetir regressões de upload, limites e autenticação. As versões corrigidas citadas nos avisos não são apresentadas como as versões mais recentes disponíveis.

### A24-02 — Caminho canônico de decisão não libera a resposta útil

**Prioridade P0; risco funcional alto; código e testes confirmam.** `apps/api/src/services/professor_backend.py:20–22` fixa risco e clareza de intenção como `UNKNOWN`. `_decision_input` usa essas constantes, e `packages/decision/src/rick_decision/layer.py:151–153` retorna `ESCALATE/risk_unknown` para o risco não admitido pela política.

O teste `apps/api/tests/test_evidence_decision_gate.py:90` demonstra escalação mesmo com boas evidências. Esse comportamento é conservador quanto ao risco, porém deixa o fluxo de geração canônico indisponível para consultas que deveriam ser respondíveis. A conclusão não abrange automaticamente stubs e serviços legados.

**Fechamento:** implementar a política real de classificação e demonstrar consultas permitidas chegando a `ANSWER`, mantendo desconhecidas e de risco em revisão. Não substituir novamente todas as consultas por risco baixo apenas para habilitar respostas.

### A24-03 — Coleção exibida e enviada no upload divergem; retry binário permanece inadequado

**Prioridade P0 para o fluxo principal de upload; risco funcional alto; falha reproduzida.** Em `apps/web/app/app/documents/page.tsx:57`, `uploadCollectionId` começa vazio. O seletor usa `uploadCollectionValue`, que apresenta a primeira coleção disponível, mas `upload` envia o estado original em `:158`. O cliente coloca esse valor diretamente no FormData em `apps/web/lib/api.ts:200`.

O teste existente `apps/web/tests/document-state.spec.ts:36` foi executado em desktop e falhou na linha 60: esperava a coleção `a`, mas recebeu valor vazio com separadores do multipart. A interface declarou publicação porque a requisição estava interceptada pelo fixture; isso não demonstra sucesso da ingestão real.

Além disso, `retryWithFile`, na mesma página, ainda chama `file.text()` e envia JSON. O botão pode reutilizar o arquivo original, inclusive PDF/DOCX. A conversão de fonte binária em texto permanece um achado estático; não foi realizada uma campanha de retry de PDFs nesta rodada.

**Fechamento:** usar a mesma coleção efetiva para exibição, validação e envio; repetir o teste sem interação no seletor, com escolha explícita e após atualização das coleções. Preservar bytes ou referência durável da fonte nos retries e testar PDF/DOCX.

### A24-04 — Meta do pacote RAG é incompatível com um dos casos

**Prioridade P1; risco de validação alto; falha e causa confirmadas.** `make eval-retrieval-pack` falhou. O caso `alpha-positive` possui dois itens relevantes em `docs/evaluation/packs/rec22-local-v1/cases.json:19`, mas `manifest.json:22–25` exige Recall@1 de pelo menos 0,75 por grupo.

Pela fórmula implementada — relevantes recuperados no primeiro resultado divididos pelo total de relevantes — o máximo desse caso é **1/2 = 0,50**. O resultado observado foi alpha 0,50, beta 1,00 e média agregada 0,75. A verificação mais rigorosa por grupo identifica a incompatibilidade que a média ocultava.

O pacote tem apenas cinco casos sintéticos, dois positivos e três negativos. Esta falha não mede a qualidade de um LLM real nem a adequação clínica de suas respostas.

**Fechamento:** versionar e justificar uma combinação coerente de métrica, k, casos e limiares, com regressões para resultados realmente ruins. Corrigir o contrato de avaliação não equivale a reduzir silenciosamente a exigência para obter aprovação.

### A24-05 — Busca híbrida não está conectada no caminho HTTP principal

**Prioridade P1; risco funcional médio/alto; inspeção estática confirmada.** A composição cria `QdrantHttpVectorStore` em `apps/api/src/services/external_composition.py:411` e o fornece ao backend em `:446`. Esse caminho retorna `dense, []` em `packages/retrieval/src/rick_retrieval/backends.py:147`.

A nova busca sparse do caminho SDK existe, mas não comprova a capacidade híbrida do caminho efetivamente composto. A correção anterior foi parcial.

**Fechamento:** ligar os vetores sparse e a consulta híbrida ao adapter HTTP canônico, com schema/migração compatível, e demonstrar ambas as modalidades sob filtros de tenant, workspace e coleção em Qdrant real.

### A24-06 — Auditoria administrativa pendente não possui reconciliação conectada

**Prioridade P1; risco de rastreabilidade alto; inspeção e testes locais confirmam os caminhos de falha.** O registro `requested` precede a mutação, o que melhora o comportamento anterior. Quando a auditoria final falha, `apps/api/src/routes/admin.py:195–207` devolve HTTP 202, `reconciliation_required=true` e status `pending` ou `registration_failed`.

A tentativa de gravar a pendência usa o mesmo sink. Na busca por consumidores em aplicações, pacotes e infraestrutura, foram encontrados o escritor, os testes e a regra de retenção, mas nenhum worker que finalize essas pendências. `apps/api/src/services/sqlite_audit.py:349–356` as preserva fora do corte normal de retenção.

**Fechamento:** definir o contrato durável de operação e auditoria, implementar reconciliação idempotente e demonstrar falha do sink, reinício, retomada e ausência de duplicação. Os testes devem incluir o caso em que nem a pendência consegue ser persistida.

### A24-07 — Migração 0005 corrigida sem upgrade comprovado para histórico já aplicado

**Prioridade P1; risco de atualização alto, condicionado à existência de instalações anteriores.** As expressões de contagem de propriedades e as regex foram alteradas em `infrastructure/migrations/0005_rewrite_legacy_jobs.sql`. O runner rejeita divergência de checksum em `infrastructure/scripts/migrate.py:105–107`.

Se uma instalação já registrou o checksum anterior, a versão modificada não será aceita pelo runner atual. Não foi comprovada a existência de tal instalação, nem executada uma migração em banco. `make ops-static` apenas calculou os seis checksums atuais e marcou execução como `NOT_RUN`.

**Fechamento:** elaborar uma estratégia de atualização compatível com o histórico e testá-la em banco descartável com a migração antiga aplicada. Não reescrever registros de checksum para simular consistência.

### A24-08 — Limite da telemetria não cobre a opção síncrona explícita

**Prioridade P1; risco de disponibilidade médio; inspeção estática.** A entrega padrão em `packages/observability/src/rick_observability/events.py` agora tem pool fixo, fila finita e contadores. Porém, no ramo `if timeout is None`, `deliver()` executa na thread chamadora, sem o limite do pool.

Um sink bloqueado nesse ramo ainda pode bloquear o chamador. Isso não significa que o caminho padrão seja ilimitado. Exportação real ao coletor, alertas e cumprimento de SLO não foram testados.

**Fechamento:** explicitar e testar os contratos dos dois modos, limitar o modo usado em operação e validar saturação, recuperação do coletor e entrega dos alertas.

### A24-09 — Promoção tem etapas obrigatórias sem execução conectada

**Prioridade P1; risco de entrega alto; inspeção estática.** `scripts/state_of_art/triple_aaa_verify.py:513`, `:541` e `:544` declaram `lab-readiness`, `independent-reviews` e `production-runtime` sem comando. O tratamento de comando ausente em `:387–395` as mantém bloqueadas. O fluxo inspecionado do pacote de aprovação atualiza as etapas de selo e decisão final, sem fechar essas três observações.

Além disso, a mensagem fixa de indisponibilidade do Docker não descreve toda a situação atual: o daemon respondeu à consulta autorizada fora do sandbox. O controle conservador impede aprovação indevida, mas precisa de um caminho real de obtenção e consumo das evidências.

**Fechamento:** conectar produtores e consumidores dessas evidências com vínculo ao candidato revisado, sem trocar bloqueios por aprovações sintéticas. Executar a CI e os testes necessários no candidato final. Esta auditoria não executou a promoção completa.

### A24-10 — Operação distribuída e recuperação continuam sem validação nesta rodada

**Prioridade P1; lacuna de evidência, não incidente observado.** Os testes locais não substituem PostgreSQL, Redis, Qdrant, S3, provider, API e worker funcionando juntos. Não foram realizados restore do conjunto, medições de RPO/RTO, carga, caos, estabilidade prolongada ou validação de um corpus representativo.

**Fechamento:** executar em ambiente descartável um fluxo upload → fila → worker → índices → recuperação autorizada → resposta/citações → histórico, seguido dos cenários de recuperação e falha definidos para o produto.

## 4. Melhorias efetivamente verificadas desde a auditoria anterior

| Melhoria | Evidência atual | O que ainda não demonstra |
|---|---|---|
| Lotes limitados de embeddings e indexação | `packages/ingestion/src/rick_ingestion/pipeline.py:63`, `_embed_in_batches`, integração em `:656` e planejamento de upsert em `:714`; suíte de domínio passou. | Qualidade e custo com embeddings reais, documentos representativos e serviços externos. |
| Rejeição de resposta sem marcador de citação | `packages/professor/src/rick_professor/orchestration.py:1106`; 60 testes passaram. | Fundamentação semântica de todas as afirmações e fluxo integrado liberado pelo Decision. |
| Metadados de chat preservados em conclusão e replay | `apps/api/src/services/chat_service.py`, eventos `completion` normalizados por `ChatResponse`; 599 testes da API passaram. | Experiência completa de geração usando um modelo real. |
| Contratos e streaming de providers fortalecidos | Cliente e contratos atuais; 76 testes de provider e 12 de contratos passaram. | Compatibilidade operacional com cada provider pretendido. |
| Composição e encerramento do worker corrigidos | `RICK_WORKER_ID` encaminhado à API, regras do Prometheus configuradas, shutdown com orçamento de 30 segundos e resultado assíncrono respeitado. | Readiness, encerramento e retomada de uma stack real. |
| Entrega padrão de eventos limitada | Pool fixo, capacidade de fila, contadores e shutdown; suíte de observabilidade passou no conjunto de fundamentos. | Limites no ramo síncrono e operação real de coletor/alertas. |

## 5. Verificações executadas

| Comando ou conjunto | Resultado desta rodada | Evidência |
|---|---|---|
| `make api16-root`, fora do sandbox | **599 passaram**, 369 avisos; exit 0. | [Log API](reports/evidence/auditoria-2026-09-24/api16-root-host.log) |
| `make api16-domain` | **232 passaram**; exit 0. | [Log domínio](reports/evidence/auditoria-2026-09-24/api16-domain.log) |
| `make api16-worker` | **89 passaram**, 7 avisos. | [Log dos pacotes](reports/evidence/auditoria-2026-09-24/remaining-tests-host.log) |
| `make api15-provider` | **76 passaram**. | Mesmo log dos pacotes. |
| `make api15-professor` | **60 passaram**. | Mesmo log dos pacotes. |
| `make api15-contracts` | **12 passaram**. | Mesmo log dos pacotes. |
| `make api15-lock` | **54 passaram**. | Mesmo log dos pacotes. |
| `make storage-test` | **26 passaram**. | Mesmo log dos pacotes. |
| `make jobs-test` | **44 passaram**. | Mesmo log dos pacotes. |
| `make ops-backup-test` | **7 passaram**. | Mesmo log dos pacotes. |
| Identidade, autorização, evidence, decision, observabilidade, scripts de qualidade e infraestrutura | **494 passaram**, com `pytest --import-mode=importlib`. | [Log dos fundamentos e verificadores](reports/evidence/auditoria-2026-09-24/foundation-release-tests.log) |
| `make validate` | Passou: fronteiras, plano de controle e estrutura dos critérios de qualidade. | [Log validate](reports/evidence/auditoria-2026-09-24/validate.log) |
| `make lint`, `make typecheck`, `make web-lint`, `make web-typecheck` | Passaram. | [Resultados dos checks](reports/evidence/auditoria-2026-09-24/check-results.json) |
| `make compose-static` | Passou: 14 serviços em cada topologia; nenhum foi iniciado por esse comando. | [Log Compose](reports/evidence/auditoria-2026-09-24/compose-static.log) |
| `make ops-static` | Passou: seis checksums e verificações estáticas; SQL não executado. | [Log operacional estático](reports/evidence/auditoria-2026-09-24/ops-static.log) |
| `make security-adversarial` | Passou a validação estrutural de oito registros sintéticos em oito categorias. | [Log adversarial](reports/evidence/auditoria-2026-09-24/security-adversarial.log) |
| `make eval-retrieval-pack` | **Falhou**: alpha Recall@1 0,50 < 0,75; exit 2 do make. | [Log RAG](reports/evidence/auditoria-2026-09-24/eval-retrieval-pack.log) |
| Playwright, teste existente de coleção de upload, desktop | **1 teste falhou**, assertion na linha 60; exit 1. | [Log navegador](reports/evidence/auditoria-2026-09-24/browser-upload.log) |
| `docker version --format '{{.Server.Version}}'`, consulta autorizada fora do sandbox | Daemon respondeu **29.1.3**; exit 0. | Observação direta da ferramenta nesta sessão; sem alteração de containers. |

Os resultados somam **1.693 execuções de testes aprovadas com sobreposição**, não 1.693 testes distintos. A falha de navegador e a falha do pacote RAG permanecem abertas.

### Limitações e intercorrências

A primeira execução da API dentro do sandbox atingiu o limite de 240 segundos, sem resultado de testes; o lote foi posteriormente interrompido. A execução autorizada fora do sandbox passou. O acesso ao Docker também foi negado no sandbox e respondeu fora dele. Esses episódios foram tratados como limitações do ambiente, sem classificar o produto como falho a partir deles.

O teste de navegador iniciou serviços locais de teste e usou respostas interceptadas para as operações do cenário. Não representa uma campanha visual completa, auditoria de acessibilidade, build de produção ou execução integrada de ingestão. Os logs preservam referências a traces temporários, que não fazem parte do pacote durável desta entrega.

O `make typecheck` Python executa compilação, conforme `scripts/phase11/runner.py:736`; não foi transformado em uma garantia de tipagem estática. O check adversarial valida um corpus; não é evidência de ataques executados contra o sistema. A pesquisa de segurança foi direcionada a versões observadas e avisos oficiais, não um inventário exaustivo de vulnerabilidades.

## 6. Ordem de correção proposta

| Ordem | Entrega verificável | Critério de encerramento |
|---:|---|---|
| 1 | Atualização compatível das dependências expostas ao parsing de formulários | Pins, dependências resolvidas e imagem verificados; regressões HTTP e upload passam. |
| 2 | Upload funcional e fonte preservada no retry | O teste atualmente vermelho passa; seleção padrão/alternativa e retry binário têm prova de comportamento. |
| 3 | Política de decisão de domínio conectada | Casos respondíveis geram resposta fundamentada; casos incertos continuam bloqueados ou escalados. |
| 4 | Contrato coerente de avaliação RAG | Meta matematicamente alcançável, versão e justificativa registradas, casos ruins continuam sendo rejeitados. |
| 5 | Busca híbrida no adapter canônico e reconciliação administrativa | Provas dos caminhos realmente usados, incluindo isolamento, falha e retomada idempotente. |
| 6 | Atualização de banco e operação completa | Migração antiga → nova versão, fluxo ponta a ponta, restore e ensaios operacionais com evidências atuais. |
| 7 | Candidato revisável e promoção | Código consolidado em revisão, CI do candidato, consumo de evidências e decisões independentes de aprovação. |

## 7. Entrega e preservação

Foram adicionados somente este relatório e o diretório de evidências desta auditoria. O conteúdo dos **1.198 arquivos rastreados** foi comparado por SHA-256 com o início da análise, sem alterações introduzidas pela auditoria. As modificações anteriores, os relatórios anteriores e o plano de controle foram preservados. Não foi criado commit, enviado push, implantada versão ou chamado provider pago.

**Próxima ação na fotografia de 24/09:** preparar a atualização compatível das dependências de formulários, acompanhada das regressões de upload e autenticação. A continuação local de 25/09 avançou para Q24-19/Q24-20 e está registrada no checkpoint posterior abaixo; o estado atual do programa permanece aberto.

## Atualização posterior da implementação — 25/09/2026

A nota geral **72/100** e as 26 notas por item acima são a fotografia da auditoria de 24/09 e não foram recalculadas com evidência posterior. Desde então, Q24-19/Q24-20 receberam transação/outbox administrativa e reconciliação PostgreSQL; a verificação atual registra API 706, worker 116 e PostgreSQL descartável 108. Uma crítica independente encontrou lacunas de restart, rollback de update, concorrência real e semântica do fallback; as regressões foram acrescentadas e a revisão final está pendente. Consulte o [checkpoint de implementação](reports/estado-implementacao-q24-2026-09-24.md) para comportamento, escopo e limitações. Esses resultados não encerram os achados de operação integrada nem alteram a decisão de promoção.

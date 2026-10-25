# Phase 3 — fechamento do laboratório e preparação de produção

## Purpose / Big Picture

O pedido de 25/10/2026 autoriza concluir o laboratório local e preparar um
pacote revisável de produção. Não concede GO, credenciais, revisão independente
ou implantação. O controlador PROD12/AUD15 permanece histórico; este plano
delimita o trabalho solicitado sem aceitar itens daquele backlog.

## Progress

### Continuação após `d655815`

Baseline limpa confirmada em `d655815108e4f93228243f3aa09b9191c7269c47`.
O pedido mantém laboratório primeiro, sem ratificar critérios de produção.
Contrato desta unidade: implementar harnesses locais de performance/soak
com workloads reais, tenant próprio, concorrências 1/10/50/100 e amostras
por operação; CPU/RAM/FD/conexões observados em /proc e fila/attempts no PG.
Perf inclui API, retrieval, chat, ingestão e throughput do worker. Soak terá
perfis locais curto/estendido com duração explícita, não equivalentes à janela
de produção aprovada. Ausência/erro/timeout e qualquer matriz incompleta não
recebem PASS; todos os recursos próprios são fechados também em falha.
Chaos exige dependências realmente isoladas antes de interromper serviços;
nunca encerrar a pilha compartilhada. Frontend deve observar ações reais e
preservar falhas de zoom/estados até haver prova, sem browser route fixtures.
Aceite do golden exige avaliador/corpus aprovado fornecido pelo dono. O usuário
confirmou que esses materiais não existem e autorizou seguir com o laboratório;
a aprovação continua pendente, sem inventar um avaliador aprovado.

Relatório desta continuação:
`docs/reports/evidence/prd26-2026-10-24/operational-closure.md`.

- [x] Performance 20/20, 1.610 operações, geração citada e recarga persistida;
  tenant/evidence 16/16 com quatro atores e 327 respostas de carga HTTP 200.
- [x] Soak 30/120 s PASS, 27/79 ciclos, limites locais explícitos; não é soak de produção.
- [x] Chaos isolado 13/13; frontend PASS inclusive na imagem final por digest,
  três viewports, axe, reflow e zoom nativo. Três imagens/SBOMs locais verificados.
- [x] Observabilidade: trace causal 28 spans/nove estágios, 17/18 grupos e
  alertas/SLO locais PASS; suporte semântico segue ausente sem avaliador aprovado.
- [x] Regressão e relatório atualizados; handoff PREPARED_NO_GO sem aprovação
  fabricada. Árvore alterada para revisão, sem commit/push automático.

### Continuação após `5d66225`

O novo pedido autoriza implementar os bloqueios técnicos restantes no lab,
preservando produção/GO/revisão independente. Baseline confirmada limpa em
`5d66225`. Próxima unidade: composição formal de tenant/evidence sobre HTTP,
PostgreSQL, Qdrant/S3/Redis reais e sessões persistidas. Aceite: controle positivo
de tenant A e B antes dos negativos; cada um dos 16 casos executa uma fronteira
real e conserva medição; timing tem amostra/limite explícitos apenas para o lab;
cleanup encerra somente processos próprios mesmo em erro. O gate inteiro deve
falhar ao aceitar/levar dados indevidos, perder um caso ou não limpar recursos.
Implementação e revisão própria não concedem `production_safe`.

- [x] Composição formal tenant/evidence implementada: 16/16 PASS em execuções
  anteriores; 15/16 sob contenção concorrente, com FAIL de timing preservado.
  Sessões persistidas e cleanup também nos caminhos de erro.
- [ ] Estabilidade/medição de timing sob carga; não há aprovação robusta.
- [x] Composição golden e execução das 11 falhas em escopos independentes:
  45/47 checks PASS; professor BLOCKED_EXTERNAL e stage trace incompleto.
- [x] Trace real entre API/worker em processos separados: 49 spans, nove
  categorias e vínculo causal obrigatório de enqueue para worker.
- [x] Regressão principal: 478 testes PASS; pacote passa a indexar observações
  formais e raw artifacts por hash, mantendo PREPARED_NO_GO.
- [ ] Avaliador/corpus aprovado e observação completa de professor/decisão/response.
- [ ] Métricas/alertas/cardinalidade/SLO; matrizes operacionais completas.
- [ ] Dez estados restantes do frontend, zoom/reflow e supply chain completo.

- [x] Checkout inicial limpo em `1641a28`; Compose dev saudável.
- [x] Identificados envelopes locais e a rejeição correta da promoção.
- [x] Humano selecionou concluir primeiro o laboratório e preparar o pacote.
- [x] Implementar e executar ingestão/autoridade/isolamento com stores reais:
  16 checks PASS; exportação Collector/Jaeger acrescenta o 17º check, 13 spans.
- [x] Preparar inventário de bloqueios e pacote com hashes, sem alterar inputs
  canônicos ou declarar aprovação.
- [x] Regressão focada e revisão própria separada do diff; resultado final no
  relatório de evidência desta rodada.
- [x] `make validate` PASS (1.198 links, zero erros); `make compose-static` PASS.
  Input de browser autêntico restaurado e execução real com diretório isolado
  verificada; gate frontend continua FAIL, preservado explicitamente.

## Context and Orientation

Os gates formais ficam em `scripts/phase11/*runtime_gate.py`; os envelopes
commit-bound em `scripts/state_of_art/phase3_runtime_adapter.py`. Os inputs
canônicos sob `.runtime` são restaurados pelo controlador: relatórios desta
rodada usam `.runtime/phase-3/local-closure/` para preservar os anteriores.

## Scope and Constraints

Usar dados sintéticos isolados por execução e serviços já autorizados do lab.
Não encerrar containers compartilhados, não modificar permissões do host, não
expor segredos, não fabricar métricas, não marcar revisão própria independente.
Um probe parcial não satisfaz o gate golden completo (11 falhas), nem representa
TLS/auth ou capacidade de produção. SHA e hash do código sujo são registrados
separadamente de evidência de release commit-bound.

## Architecture and Interfaces

Reutilizar `build_external_providers` e os adaptadores PostgreSQL/S3/Qdrant/
Redis/provider existentes. Um probe do laboratório observa upload, replay,
worker, objetos, documentos/chunks, recuperação e autoridade de evidência.
Um preparador lê artefatos e produz um índice verificável com pendências.
Não substituir esses serviços por implementações em memória para alegar runtime.

## Milestones

1. Probe real reproduzível: sucesso normal e mutações de evidência rejeitadas.
2. Pacote preparatório: inventário de todos os gates, integridade e decisões
   ausentes explícitas, sem mudança em critérios de promoção.
3. Verificação: casos negativos do harness, execução no lab, `make validate`.

## Plan of Work

Implementar composição/harness e preparação, corrigindo defeitos reproduzidos
no produto e na invocação/cleanup dos gates. Preservar a quality bar congelada.
Evidência inclui resultado por asserção e limitações; nenhuma operação
não observada recebe PASS. Isolar tenants por run e fechar os recursos abertos.

## Concrete Steps

1. Construir o probe sobre a composição externa existente, executar no lab e
   corrigir falhas reproduzidas.
2. Indexar envelopes e seus raw artifacts em pacote diagnóstico não-promovível.
3. Rodar regressões pertinentes e registrar limites e próxima ação.

## Validation and Acceptance

- Upload/replay preservam job; worker publica; bytes/checksum e projeção Qdrant
  coincidem com a autoridade PostgreSQL.
- Cross-tenant, coleção indevida, versão/checksum/chunk alterados e evidência
  forjada não passam pelo validador de produção ligado ao PostgreSQL.
- Falha de serviço e ausência de configuração não viram PASS.
- Pacote rejeita artifacts fora do repo, symlinks, hashes errados e resultados
  incompletos; nenhuma revisão/GO é gerada pelo builder.
- Gates formais e qualidade existentes não são enfraquecidos.

## Idempotence and Recovery

Cada execução usa UUID e escopo próprio. Dados de prova ficam retidos no lab
para inspeção; fechar clientes não remove volumes nem dados alheios. Após
interrupção, executar novamente com outro UUID. Nenhum commit/push automático.

## Artifacts and Notes

Saídas em `.runtime/phase-3/local-closure/`; relatório versionado em
`docs/reports/evidence/prd26-2026-10-24/phase3-local-closure.md`.

## Surprises & Discoveries

O `.agent/state.json` ainda descreve AUD15, enquanto o checkout e a pilha atual
contêm avanços PRD26. Não reescrever esse histórico para conceder aceite.
O gate golden exige observação explícita de parse/normalize, 11 crash points,
métricas de suporte e publicação verificada; um happy path não o substitui.
O probe encontrou dimensão ausente na API dos dois Compose; corrigida e
rejeitada pelo check estático quando ausente/divergente. A API dev foi recriada
com dimensão 2 e está saudável. O gate frontend ainda falha em estados não
exercitados e proxies de acessibilidade; evidência de container ausente.
Mesmo com `--output` alternativo, esse gate sobrescrevia o browser control-input:
preservados bytes/hash da execução, restaurado input autêntico e implementado
`--evidence-dir` isolado com teste de regressão. Nada recebe aceite por isso.

## Decision Log

- 25/10: humano escolheu laboratório primeiro e preparação do pacote.
- Reutilizar o grafo real é menor e mais fiel que criar outro pipeline.
- Preservar inputs canônicos e registrar novos artefatos em diretório distinto.
- Continuação: o caso de falha após commit exige recibo committed e um único
  sucesso/replay, não rollback de publicação já confirmada. Before-publish
  recuperado exige ainda preservação da baseline durante pending. Testes
  negativos conservam a rejeição de evidência incompleta. A correção do gate
  precisa de revisão independente; não altera a barra congelada nem concede GO.
- Corrigido vetor Cosine enviado ao Qdrant para representação unitária binary32
  estável, permitindo recuperação por manifesto exato sem tolerância arbitrária.
- Restringir eventos globais de telemetria pela permissão tenants.read; métricas
  agregadas continuam disponíveis a observability.read.

## Outcomes & Retrospective

Preparação e probe local entregues; fechamento global permanece PARTIAL.
Produção permanece NO-GO até evidência atual de todos os gates, revisão
independente, perfil seguro e decisão humana. Tenant formal tem execuções PASS e FAIL de timing sob contenção preservado;
trace entre processos tem observação local PASS. Golden tem 11/11 falhas PASS e depende do
avaliador aprovado para fechar o restante; as matrizes operacionais e o frontend
completo seguem abertos. A projeção do timestamp publicado no Qdrant tem uma
reconciliação explícita no harness, que não demonstra cobertura automática em
produção. O novo relatório é
`docs/reports/evidence/prd26-2026-10-24/formal-runtime-closure.md`.

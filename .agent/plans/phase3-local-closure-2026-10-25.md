# Phase 3 — fechamento do laboratório e preparação de produção

## Purpose / Big Picture

O pedido de 25/10/2026 autoriza concluir o laboratório local e preparar um
pacote revisável de produção. Não concede GO, credenciais, revisão independente
ou implantação. O controlador PROD12/AUD15 permanece histórico; este plano
delimita o trabalho solicitado sem aceitar itens daquele backlog.

## Progress

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

Implementar somente composição/harness e preparação. Manter o gate formal
intacto. Evidência inclui resultado por asserção e limitações; nenhuma operação
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

## Outcomes & Retrospective

Preparação e probe local entregues; fechamento global permanece PARTIAL.
Produção permanece NO-GO até evidência atual de todos os gates, revisão
independente, perfil seguro e decisão humana. As composições formais golden/
tenant, trace entre processos, matrizes operacionais e frontend completo ainda
exigem implementação/evidência; não são declarados fechados por este plano.

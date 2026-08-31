# 0023 — Plano da Rodada de Convergência Final

## Objetivo

Preservar o plano detalhado da rodada corretiva aberta em 2026-04-16. Este documento agora é histórico: a rodada foi concluída e o Gate F0 foi liberado.

---

## Contexto de Abertura

### Problemas confirmados na abertura

1. `pytest -q` falhava no baseline anterior
2. validação de `Qdrant = disco` estava pendente sem runtime de Qdrant ativo
3. a avaliação sem rastreabilidade por pergunta (`question_results`) foi corrigida nesta rodada
4. contrato de erro e observabilidade ainda precisa alinhamento final para produção

### Regra principal da rodada

Nada premium entra antes do fechamento desses quatro pontos.

### Status final

- `D1` concluído
- `D2` concluído
- `D3` concluído
- `D4` concluído
- Gate F0: `LIBERADO`

---

## Como Executar Esta Rodada

### Regras gerais

1. executar os sprints em ordem
2. atualizar o `0020-master-execution-log.md` ao fim de cada sprint
3. não declarar “concluído” sem evidência executada
4. se um sprint descobrir um novo bloqueio crítico, reabrir o backlog antes de avançar

### Formato de fechamento por sprint

Cada sprint deve terminar com:

- resumo do que foi feito
- arquivos alterados
- evidência de validação
- bugs conhecidos restantes
- decisão: avançar, repetir ou abrir novo item

---

## Sprint D1 — Baseline e Integridade do Corpus

### Objetivo

Restaurar a consistência entre testes, disco e índice vetorial.

### Problemas que este sprint corrige

- `pytest -q` com falhas
- alinhamento Qdrant/disco pendente até validação em runtime
- drift de corpus canônico
- log mestre narrando um estado mais avançado do que o runtime

### Escopo

- identificar por que historicamente ocorreu divergência (ex.: `35` chunks vs `21` pontos) entre disco e índice
- decidir se o problema é reindex pendente, corpus extra indevido ou bug de fluxo
- corrigir o estado operacional
- voltar a suíte para verde
- atualizar o `0020`

### Tarefas detalhadas

1. Inventariar `src/data/documents/default/`.
   Deve responder:
   - quais documentos são canônicos
   - quais documentos estão indexados
   - quais documentos estão faltando no índice
2. Reexecutar o processo correto:
   - reindexação completa, ou
   - limpeza do corpus indevido, ou
   - correção do pipeline que deixou o estado inconsistente
3. Fechar os testes de consistência:
   - `test_qdrant_point_count_matches_disk`
   - `test_each_document_indexed_in_qdrant`
4. Atualizar o `0020` para remover qualquer número antigo.

### Entregáveis

- baseline verde
- disco e índice coerentes
- explicação curta do que causou o desvio

### Critérios de aceite

- `pytest -q` passa
- pontos no Qdrant = chunks no diretório canônico
- `0020` reflete os números reais

---

## Sprint D2 — Fechamento dos Contratos de API

### Objetivo

Alinhar metadata e retrieval ao contrato final adotado para a Fase 0.

### Problemas que este sprint corrige

- metadata abaixo do contrato
- retrieval sem campos prometidos
- parâmetros documentados que ainda não produzem efeito útil

### Escopo

- revisar `GET /documents/{document_id}`
- revisar `/search` e `/query`
- decidir explicitamente o que é suportado agora e o que fica fora do contrato da fase

### Tarefas detalhadas

1. Completar o payload de metadata.
   Tratar especialmente:
   - `created_at`
   - `tags`
   - `embeddings_model`
   - `indexed_at`
2. Completar a resposta de retrieval.
   Tratar especialmente:
   - `document_filename`
   - `include_raw_scores`
   - `scores_breakdown`
3. Revisar filtros.
   Critério:
   - filtros suportados devem funcionar
   - filtros não suportados devem ser removidos dos docs ou rejeitados claramente
4. Atualizar os docs que descrevem o contrato final.

### Entregáveis

- metadata coerente com docs
- retrieval coerente com docs
- contrato final sem ambiguidade

### Critérios de aceite

- endpoint de metadata passa a refletir o contrato final
- retrieval devolve os campos prometidos
- docs e runtime deixam de divergir

---

## Sprint D3 — Avaliação e Observabilidade Auditáveis

### Objetivo

Fechar o pacote de evidência que ainda impede leitura séria de qualidade.

### Problemas que este sprint corrige

- `/metrics` abaixo do contrato
- qualidade visível só por inferência indireta

### Escopo

- corrigir `EvaluationResponse`
- revisar agregações de telemetry
- registrar métricas úteis no `0020`

### Tarefas detalhadas

1. Corrigir o retorno de avaliação.
   Critério:
  - `question_results` deve permanecer preenchido (não vazio)
  - o aggregate final não pode esconder a evidência individual
2. Expandir `/metrics`.
   Prioridade mínima:
   - `hit_rate_top3`
   - `hit_rate_top5`
   - métrica útil de score/confiança
   - agregações coerentes de retrieval e answer
3. Adicionar ou ajustar testes.
4. Atualizar docs de observabilidade e execução.

### Entregáveis

- avaliação auditável
- métricas minimamente úteis
- docs coerentes

### Critérios de aceite

- `question_results` não vem vazio
- `/metrics` cobre o mínimo operacional da fase
- `0020` passa a resumir qualidade com base em dados reais

---

## Sprint D4 — Gate Rehearsal Final

### Objetivo

Encerrar a rodada com uma decisão formal e curta sobre o Gate F0.

### Escopo

- reexecutar o pacote mínimo de validação
- atualizar o `0020`
- decidir se a fundação fechou ou não

### Tarefas detalhadas

1. Reexecutar:
   - `pytest -q`
   - validação do dataset
   - `GET /documents/{document_id}`
   - comparação Qdrant vs disco
   - `/metrics`
   - `/evaluation/run`
2. Registrar a evidência em formato curto.
3. Tomar uma decisão formal:
   - `Gate F0 liberado`
   - ou `nova rodada corretiva necessária`

### Entregáveis

- pacote final de evidência
- `0020` atualizado
- decisão formal de gate

### Critérios de aceite

- o estado do projeto pode ser lido sem interpretação informal
- a decisão final bate com a evidência executada

---

## Checklist do Executor por Sprint

- O objetivo do sprint foi cumprido integralmente?
- Existe evidência objetiva, não só narrativa?
- Os docs relevantes foram atualizados?
- Os testes necessários foram ajustados?
- O `0020` foi atualizado?
- Há bloqueio crítico aberto que deveria impedir avanço?

Se houver um “não” relevante, o sprint não fecha.

---

## Definição de Sucesso da Rodada

Esta rodada só termina com sucesso se:

1. `pytest -q` estiver verde
2. `Qdrant = disco` validado com runtime ativo
3. `question_results` permanecer preenchido
4. `metadata` e `retrieval` permanecerem coerentes com o contrato final
5. `/metrics` entregar o mínimo operacional da fase
6. o `0020` puder declarar o estado do projeto sem contradições

---

## Próximo Passo

Consultar `0015-roadmap-executivo.md` e `0016-backlog-priorizado.md` para o backlog pós-gate.

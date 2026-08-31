# 0022 — Plano da Rodada Complementar

> Status: documento histórico. A rodada complementar descrita aqui foi superada pela auditoria completa de 2026-04-16. O plano vigente agora é `0023-plano-da-rodada-de-convergencia-final.md`.

## Objetivo

Fornecer um plano detalhado para a rodada complementar pós-Phase A. Este documento existe para fechar as pendências objetivas que ainda impedem uma leitura limpa do Gate F0.

---

## Como Executar Esta Rodada

### Regras gerais

1. Executar os sprints em ordem
2. Não puxar item premium antes de fechar os bloqueios da fundação
3. Atualizar o `0020-master-execution-log.md` ao fim de cada sprint
4. Não declarar “concluído” sem evidência executada
5. Se um sprint revelar nova inconsistência crítica, reabrir o backlog antes de avançar

### Formato de fechamento por sprint

Cada sprint deve terminar com:

- resumo do que foi feito
- arquivos alterados
- evidência de validação
- bugs conhecidos restantes
- decisão: avançar, repetir ou abrir novo item

---

## Sprint C1 — Limpeza da Suíte e da Evidência

### Objetivo

Garantir que a suíte principal e o execution log contem a mesma história, sem ruído estrutural.

### Problemas que este sprint corrige

- números conflitantes no `0020`
- teste legado sendo coletado indevidamente
- warnings evitáveis na suíte
- caso válido de `low_confidence` sem assert real

### Escopo

- revisar `pytest -q` como baseline oficial
- corrigir o log mestre
- retirar `src/test_pipeline.py` da coleta ou convertê-lo em teste legítimo
- adicionar assert explícito no caso válido de `low_confidence`
- classificar melhor o que é teste offline e o que é integração

### Tarefas detalhadas

1. Rodar `pytest -q` e congelar o número real de testes como evidência do sprint.
2. Corrigir o `0020` para uma única narrativa, sem totais conflitantes.
3. Tratar `src/test_pipeline.py`.
   Alternativas aceitáveis:
   - mover para `src/scripts/`
   - renomear para não ser coletado
   - transformar em teste verdadeiro com asserts
4. Fechar o caso válido de `low_confidence`.
   Critério:
   - deve falhar se a query válida passar a ser marcada como baixa confiança

### Entregáveis

- suite principal limpa
- execution log coerente
- cobertura real dos 4 cenários de `low_confidence`

### Critérios de aceite

- `pytest -q` passa
- o log não se contradiz
- o caso válido de `low_confidence` possui assert real

### Evidência esperada

- saída documentada de `pytest -q`
- diff do `0020`
- diff dos testes

### Armadilhas comuns

- “deixa o warning, o importante é passar”
- “já funciona no runtime, não precisa assert”

Se isso acontecer, o sprint não fechou.

---

## Sprint C2 — Convergência de Contratos e Scripts Auxiliares

### Objetivo

Fazer os scripts operacionais seguirem o mesmo contrato que já vale para dataset, schema e API.

### Problemas que este sprint corrige

- uso residual de `documento_fonte`
- scripts de benchmark/tuning quebrando com o dataset atual
- documentação afirmando mais convergência do que realmente existe

### Escopo

- revisar scripts em `src/scripts/`
- revisar scripts legados de apoio
- migrar contrato para `document_id`
- ajustar textos de docs que afirmem “não resta legado”

### Tarefas detalhadas

1. Corrigir `benchmark_controlado.py`.
   Deve:
   - ler `document_id`
   - usar o dataset atual sem fallback errado
2. Corrigir `tune_chunking.py`.
   Deve:
   - parar de depender de `documento_fonte`
   - usar o corpus oficial
3. Revisar qualquer outro script operacional que consuma o dataset.
4. Fazer uma busca final por `documento_fonte`.
   Critério:
   - legado só pode permanecer em contexto histórico/documental, nunca como dependência operacional ativa

### Entregáveis

- scripts auxiliares compatíveis com o contrato oficial
- documentação ajustada para o estado real

### Critérios de aceite

- scripts principais de apoio não quebram com o dataset atual
- `rg documento_fonte` não encontra uso operacional ativo

### Evidência esperada

- diff dos scripts
- execução mínima de cada script relevante
- busca final por termo legado

---

## Sprint C3 — Consolidação do Corpus Operacional

### Objetivo

Eliminar ambiguidade entre corpus ativo e corpus legado, deixando rebuild e reindex auditáveis.

### Problemas que este sprint corrige

- coexistência de `data/documents/default` e `src/data/documents/default`
- operador sem clareza sobre qual árvore usar
- risco de auditoria ou rebuild olhando para o diretório errado

### Escopo

- definir diretório canônico
- decidir destino do diretório legado
- documentar fluxo de rebuild/reindex
- revalidar Qdrant versus disco após a decisão

### Tarefas detalhadas

1. Confirmar o diretório oficial via config e docs.
2. Tratar o diretório legado.
   Alternativas aceitáveis:
   - remover
   - mover para arquivo morto
   - marcar explicitamente como histórico
3. Documentar o fluxo operacional:
   - onde fica o raw
   - onde ficam os chunks
   - como reconstruir o índice
   - como validar contagem
4. Reexecutar a comparação entre chunks persistidos e pontos no Qdrant.

### Entregáveis

- convenção única de corpus
- instrução curta de rebuild/reindex
- validação Qdrant versus disco com base no diretório oficial

### Critérios de aceite

- qualquer operador entende qual diretório é o ativo
- a contagem Qdrant versus disco bate no diretório canônico

### Evidência esperada

- diff de docs/config
- listagem final do diretório oficial
- contagem final de pontos e chunks

---

## Sprint C4 — Gate Rehearsal Final

### Objetivo

Encerrar a rodada complementar com uma decisão formal e limpa sobre o Gate F0.

### Problemas que este sprint corrige

- risco de entrar em Phase B com a fundação ainda ruidosa
- ausência de pacote de evidência curto e confiável

### Escopo

- reexecutar o pacote mínimo de validação
- atualizar o `0020`
- decidir Gate F0 ou nova rodada corretiva

### Tarefas detalhadas

1. Reexecutar:
   - `pytest -q`
   - validação do dataset
   - verificação do endpoint `GET /documents/{document_id}`
   - verificação Qdrant versus disco
   - casos de `low_confidence`
2. Registrar a evidência em formato curto e consistente.
3. Tomar uma decisão formal:
   - Gate F0 liberado
   - ou nova rodada necessária

### Entregáveis

- pacote de evidência final
- update do `0020`
- decisão formal de gate

### Critérios de aceite

- o projeto não depende de interpretação informal para saber seu estado
- o `0020` fecha com uma decisão explícita

### Evidência esperada

- comandos executados
- resultados resumidos
- status final do gate

---

## Checklist do Executor por Sprint

- O objetivo do sprint foi cumprido integralmente?
- Existe evidência objetiva, não só observação verbal?
- Os docs relevantes foram atualizados?
- Os testes necessários foram adicionados ou ajustados?
- O `0020` foi atualizado?
- Há algum bug crítico aberto que deveria impedir avanço?

Se a resposta final for “sim”, o sprint não fecha.

---

## Definição de Sucesso da Rodada

Esta rodada é bem-sucedida se entregar:

1. execution log coerente
2. scripts auxiliares convergidos ao contrato final
3. corpus canônico documentado sem ambiguidade
4. decisão honesta sobre Gate F0

Não é necessário entregar:

- features premium
- novas interfaces
- novas camadas arquiteturais

---

## Próximo Passo

Sprint C1–C4 já foram executadas e documentadas.  
Próximo passo: abrir e priorizar os itens de **P1** em `0016-backlog-priorizado.md` (ajustes operacionais imediatos pós-fundação), e, com gate formal mantido, seguir o roadmap de **Phase B**.

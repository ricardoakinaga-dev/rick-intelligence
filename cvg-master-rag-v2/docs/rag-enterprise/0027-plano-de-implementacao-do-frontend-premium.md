# 0027 — Plano de Implementação do Frontend Premium

## Objetivo

Definir um plano executável para implementar o frontend premium do programa em sprints, com:

- telas
- backend necessário
- contratos esperados
- critérios de aceite
- dependências entre sprints

Este documento é a referência operacional da **Fase 2 — Produto Premium**.

---

## Premissas

### Estado de partida

O backend atual já possui:

- upload de documentos
- metadata de documentos
- busca híbrida
- query com resposta pronta
- métricas
- avaliação
- groundedness e sinais de confiança

O repositório também já possui uma implementação de frontend em `frontend/` com cobertura material dos módulos principais da Fase 2.

### O que este plano assume

- a fundação técnica está pronta para sustentar uma camada visual
- a interface atual é predominantemente técnica
- o objetivo da Fase 2 é transformar isso em produto web robusto
- `frontend/` é o app canônico
- não existe base paralela ativa de frontend fora de `frontend/`

### Leitura honesta do estágio atual

- `F1-F8` já aparecem implementados de forma material no frontend canônico
- `F7` está consolidado no código com persistência de contexto, responsividade e hardening transversal
- `F8` foi executado e aprovado como gate visual formal
- o restante da Fase 2 é documentação de conclusão e consolidação de evidências

### Stack sugerida

- frontend: `Next.js`
- design system: componente próprio ou base utilitária
- autenticação inicial: opcional na Fase 2, obrigatória na Fase 3
- integração principal: REST sobre os endpoints já existentes

---

## Resultado Esperado ao Final da Fase 2

Ao final da implementação, o produto deve entregar:

- painel de documentos
- upload visual
- lista de documentos
- tela de busca com evidências
- chat web
- dashboard operacional
- tela de auditoria de respostas
- navegação consistente
- experiência visual forte

### Estado real observado em 2026-04-16

- o frontend premium canônico já cobre os módulos principais da Fase 2
- os fluxos de documentos, busca, chat, dashboard e auditoria já abrem e executam localmente
- o backend principal e a UI estão integrados nos contratos centrais da fase
- a implementação da Fase 2 já foi fechada e o gate visual foi aprovado

---

## Ordem Recomendada dos Sprints

```text
Sprint F1 ─ Base do frontend e layout
Sprint F2 ─ Painel de documentos
Sprint F3 ─ Tela de busca e validação
Sprint F4 ─ Chat web
Sprint F5 ─ Dashboard operacional
Sprint F6 ─ Auditoria de respostas
Sprint F7 ─ Hardening de UX, navegação e estado
Sprint F8 ─ Gate visual da Fase 2
```

---

## Sprint F1 — Base do Frontend e Layout

### Objetivo

Criar a estrutura base do frontend premium.

### Telas / áreas cobertas

- shell principal
- layout com navegação
- header
- sidebar
- dashboard inicial placeholder
- estados globais básicos

### Entregáveis

- app frontend inicial
- estrutura de rotas
- tema visual base
- tokens visuais
- componentes base:
  - botão
  - input
  - tabela
  - card
  - badge
  - modal
  - toast
  - loading states
  - empty states

### Backend necessário

Nenhum endpoint novo obrigatório.

Usa apenas:

- `GET /health`

### Critérios de aceite

- frontend sobe localmente
- layout responsivo básico funciona
- existe navegação entre páginas placeholder
- sistema visual base está definido
- tela inicial não parece protótipo cru de engenharia

---

## Sprint F2 — Painel de Documentos

### Objetivo

Entregar a primeira tela operacional forte do produto.

### Telas / áreas cobertas

- lista de documentos
- upload visual
- drawer/modal de metadata
- status de processamento
- estados de erro de upload

### Funcionalidades

- upload por arquivo
- feedback visual de sucesso/erro
- listagem de documentos
- visualização de metadata
- filtros básicos
- paginação local ou remota
- reprocessamento preparado visualmente

### Backend necessário

Obrigatório já existente:

- `POST /documents/upload`
- `GET /documents/{document_id}`

Backend complementar recomendado:

- `GET /documents?workspace_id=...`

Se ainda não existir:

- criar endpoint de listagem de documentos
- retornar ao menos:
  - `document_id`
  - `filename`
  - `source_type`
  - `chunk_count`
  - `status`
  - `created_at`
  - `indexed_at`

### Critérios de aceite

- usuário consegue subir documento pela interface
- documento aparece na lista sem inspeção manual de filesystem
- metadata pode ser aberta visualmente
- erros de upload são compreensíveis
- tela suporta corpus pequeno e médio sem colapsar visualmente

---

## Sprint F3 — Tela de Busca e Validação

### Objetivo

Dar ao operador uma tela visual para validar retrieval.

### Telas / áreas cobertas

- página de busca
- painel de filtros
- lista de resultados
- painel lateral de evidências

### Funcionalidades

- caixa de busca
- envio de query
- visualização de chunks retornados
- score por resultado
- `document_filename`
- filtros por:
  - `document_id`
  - `source_type`
  - `tags`
  - faixa de página
- breakdown de score

### Backend necessário

Obrigatório já existente:

- `POST /search`

Backend complementar recomendado:

- endpoint ou payload com lista de documentos/tags para popular filtros

### Critérios de aceite

- operador consegue validar retrieval sem Swagger
- chunks e evidências são legíveis
- filtros suportados no backend estão acessíveis pela UI
- `scores_breakdown` aparece quando solicitado
- página ajuda debug operacional real

---

## Sprint F4 — Chat Web

### Objetivo

Entregar a principal interface de uso diário.

### Telas / áreas cobertas

- página de chat
- lista de conversas ou sessão única
- área de resposta com citações
- estados de loading e erro

### Funcionalidades

- envio de pergunta
- resposta pronta
- exibição de citações
- exibição de `document_filename`
- exibição de:
  - `low_confidence`
  - `grounded`
  - `citation_coverage`
  - `needs_review`
- histórico local de perguntas na sessão

### Backend necessário

Obrigatório já existente:

- `POST /query`

Backend complementar recomendado:

- persistência opcional de histórico

### Critérios de aceite

- usuário consegue perguntar sem interface técnica
- resposta mostra de onde veio
- baixa confiança é visível
- grounding fica visualmente claro
- UX da resposta é superior ao JSON cru

---

## Sprint F5 — Dashboard Operacional

### Objetivo

Tornar a operação do sistema visual e monitorável.

### Telas / áreas cobertas

- dashboard principal
- cards de KPI
- gráficos simples
- alertas operacionais

### Funcionalidades

- exibir métricas de:
  - retrieval
  - answer
  - evaluation
  - ingestion
- destacar:
  - hit rate
  - groundedness
  - citation coverage
  - low confidence
  - latência
  - falhas de parse

### Backend necessário

Obrigatório já existente:

- `GET /metrics`

Backend complementar recomendado:

- shape estável para séries temporais
- endpoint opcional de resumo por período

### Critérios de aceite

- operador entende o estado do sistema visualmente
- groundedness e low confidence aparecem de forma acionável
- ingestão, retrieval e answer ficam separados com clareza
- dashboard serve para rotina diária, não apenas demo

---

## Sprint F6 — Auditoria de Respostas

### Objetivo

Entregar uma tela de auditoria para validação de qualidade.

### Telas / áreas cobertas

- tela de auditoria
- lista de queries auditáveis
- detalhe de resposta
- detalhe de grounding

### Funcionalidades

- visualizar:
  - pergunta
  - resposta
  - chunks usados
  - citações
  - `grounding.reason`
  - `uncited_claims`
  - `needs_review`
- filtrar respostas mais frágeis
- priorizar casos com:
  - baixa confiança
  - grounding fraco
  - baixa cobertura de citação

### Backend necessário

Obrigatório já existente:

- `POST /query`
- `GET /metrics`

Backend complementar recomendado:

- endpoint de listagem de logs de query auditáveis

Sugestão:

- `GET /queries/logs?workspace_id=...`

### Critérios de aceite

- operador consegue revisar respostas problemáticas sem ler logs em arquivo
- grounding e claims sem citação ficam visíveis
- tela suporta triagem de qualidade real

---

## Sprint F7 — Hardening de UX, Navegação e Estado

### Objetivo

Fechar a experiência premium antes do gate visual.

### Escopo

- navegação consistente
- estados de loading melhores
- tratamento de erro consistente
- persistência básica de filtros/sessão
- empty states bons
- responsividade
- refinamento visual

### Backend necessário

Nenhum endpoint novo obrigatório.

Pode exigir ajustes menores de contrato para estabilidade de UI.

### Critérios de aceite

- experiência coerente entre páginas
- estados de erro não quebram a operação
- produto parece software utilizável, não conjunto de telas isoladas
- versão mobile/tablet ao menos funcional para consulta

---

## Sprint F8 — Gate Visual da Fase 2

### Objetivo

Validar que o frontend premium realmente existe como produto.

### Escopo de validação

- documentos
- busca
- chat
- dashboard
- auditoria

### Checklist

- [ ] painel de documentos funcional
- [ ] upload visual funcional
- [ ] tela de busca com evidências funcional
- [ ] chat web funcional
- [ ] dashboard operacional funcional
- [ ] tela de auditoria funcional
- [ ] groundedness e baixa confiança visíveis
- [ ] operador não precisa de Swagger para rotina principal

### Critério de aceite

A Fase 2 só fecha se o sistema já puder ser demonstrado como produto premium, e não apenas como backend com páginas superficiais.

### Status atual

- a Fase 2 foi validada como produto premium no gate visual formal

---

## Dependências de Backend por Tela

| Tela | Backend obrigatório | Backend recomendado |
|---|---|---|
| Layout base | `GET /health` | endpoint de perfil/config no futuro |
| Painel de documentos | `POST /documents/upload`, `GET /documents/{id}` | `GET /documents` |
| Busca | `POST /search` | lista de documentos/tags para filtros |
| Chat | `POST /query` | histórico persistido |
| Dashboard | `GET /metrics` | resumo por período / séries temporais |
| Auditoria | logs / telemetry | `GET /queries/logs` |

---

## Ordem Recomendada de Backend Complementar

Se for necessário fechar lacunas para o frontend:

1. `GET /documents`
2. `GET /queries/logs`
3. estabilização de payloads para filtros
4. resumo de métricas por período

Observação:

- os dois primeiros itens já foram implementados e validados no frontend canônico e no backend

---

## Definição de Pronto da Fase 2

A Fase 2 é considerada pronta quando:

1. existe frontend robusto
2. chat web está funcional
3. documentos e busca podem ser operados visualmente
4. groundedness e evidências estão claros
5. dashboard operacional existe
6. auditoria de respostas existe
7. a rotina principal não depende da interface técnica

### Evidência executada

- `pnpm -C frontend lint`: passou
- `pnpm -C frontend exec tsc --noEmit`: passou
- `pnpm -C frontend build`: passou
- `next start` local em `frontend/`: passou
- smoke local em `/`, `/documents`, `/search`, `/chat`, `/dashboard` e `/audit`: `200`

### Decisão atual

- Fase 2 concluída

---

## Próximo Passo

Usar `0028-backlog-por-sprint-do-frontend-premium.md` para quebrar a implementação em tickets por sprint e por tela.

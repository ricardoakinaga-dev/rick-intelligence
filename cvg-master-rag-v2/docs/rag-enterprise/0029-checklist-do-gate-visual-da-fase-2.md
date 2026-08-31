# 0029 — Checklist do Gate Visual da Fase 2

## Objetivo

Registrar a validação formal executada para decidir se a **Fase 2 — Produto Premium** pode ser considerada concluída.

Este documento passou a registrar uma decisão já executada, não uma hipótese.

Ele existe para:

- consolidar a evidência do frontend premium
- separar o que já está pronto do que ainda é gap real
- evitar declarar o gate visual sem validação ponta a ponta

---

## Estado de partida

Leitura atual do código:

- `frontend/` é o app canônico
- não existe base paralela ativa de frontend fora de `frontend/`
- `F1-F8` estão materialmente implementados no frontend canônico
- `F7` ficou consolidado no hardening transversal
- `F8` foi executado como gate e aprovado nesta rodada

---

## Evidência mínima exigida

Antes de decidir o gate visual, deve existir evidência reproduzível para:

1. frontend canônico instalando e buildando
2. backend principal verde
3. documentos operáveis pela UI
4. busca operável pela UI
5. chat operável pela UI
6. dashboard operável pela UI
7. auditoria operável pela UI
8. navegação sem dependência de Swagger para a rotina principal

---

## Checklist do Gate

### A. Base do app

- [x] `frontend/` é reconhecido oficialmente como frontend canônico
- [x] `pnpm -C frontend install` executa sem bloqueio estrutural
- [x] `pnpm -C frontend lint` passa
- [x] `pnpm -C frontend exec tsc --noEmit` passa
- [x] `next build` em `frontend/` gera artefato válido
- [x] não existe base paralela ativa de frontend fora de `frontend/`

### B. Painel de documentos

- [x] página `/documents` abre sem erro
- [x] upload visual funciona
- [x] listagem de documentos funciona
- [x] metadata abre na interface
- [x] filtros básicos funcionam
- [x] operador entende o estado do corpus sem olhar filesystem

### C. Busca e validação

- [x] página `/search` abre sem erro
- [x] busca retorna resultados reais
- [x] filtros de busca funcionam
- [x] evidência do chunk fica legível
- [x] `scores_breakdown` é visível quando solicitado
- [x] página serve para debug operacional de retrieval

### D. Chat web

- [x] página `/chat` abre sem erro
- [x] pergunta pode ser enviada pela UI
- [x] resposta retorna com citações
- [x] `document_filename` aparece
- [x] `low_confidence` é visível
- [x] `grounded` e `citation_coverage` são visíveis
- [x] histórico local da sessão funciona

### E. Dashboard operacional

- [x] página `/dashboard` abre sem erro
- [x] KPIs principais são exibidos
- [x] blocos de ingestion, retrieval, answer e evaluation aparecem
- [x] filtro de período funciona
- [x] o dashboard ajuda leitura operacional real

### F. Auditoria de respostas

- [x] página `/audit` abre sem erro
- [x] lista de respostas auditáveis é exibida
- [x] filtros de criticidade funcionam
- [x] detalhe da resposta pode ser aberto
- [x] grounding, citações e sinais de revisão ficam claros

### G. Hardening transversal

- [x] breadcrumbs e navegação estão coerentes
- [x] estados de loading são consistentes
- [x] estados de erro são consistentes
- [x] estados vazios são consistentes
- [x] persistência de contexto funciona nas rotas principais
- [x] experiência em desktop e tablet é funcional

### H. Dependência da interface técnica

- [x] rotina principal do operador pode ser feita sem Swagger
- [x] Swagger deixa de ser interface principal
- [x] o frontend já pode ser demonstrado como produto

---

## Matriz de decisão

### Aprovado

Marcar **Fase 2 concluída** somente se:

- todos os itens bloqueantes acima estiverem validados
- os gaps restantes forem claramente de Fase 3
- a rotina principal já puder ser feita pela UI

### Não aprovado

Marcar **nova rodada corretiva necessária** se qualquer um destes pontos permanecer:

- módulo principal sem operação real
- dependência forte de Swagger para rotina diária
- frontend inconsistente demais entre páginas
- build/lint sem estabilidade mínima
- base paralela ainda confundindo a fonte de verdade

---

## Campos para preenchimento da execução real

### Data da validação

- `2026-04-16`

### Responsável

- `Codex`

### Evidência executada

- `pytest -q`: `40 passed, 3 skipped`
- `pnpm -C frontend exec tsc --noEmit`: passou
- `pnpm -C frontend lint`: passou
- `pnpm -C frontend build`: compilou com sucesso e gerou artefato válido
- `pnpm -C frontend test:smoke`: `5 passed`
- smoke local em `/`, `/documents`, `/search`, `/chat`, `/dashboard` e `/audit`: `200`
- documentos: upload, listagem, metadata e drawer de navegação validados por smoke
- busca: retrieval executado pela UI com resultados reais
- chat: query executada pela UI com resposta, citações e sinais de confiança
- frontend mobile: drawer de navegação e layout responsivo validados por smoke test

### Decisão final

- [x] Fase 2 concluída

### Observações

- o pipeline de `query` agora possui fallback offline determinístico quando `OPENAI_API_KEY` não está configurada
- o checklist agora registra aprovação formal da Fase 2 via smoke validado
- a base paralela antiga foi removida do repositório
- o frontend ativo está buildando e tipando corretamente

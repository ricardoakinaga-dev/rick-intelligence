# 0006 — Fase 2: RAG Premium

## Objetivo da Fase

Transformar o sistema em um **produto premium de uso diário**, com frontend robusto, experiência forte de operação e recursos visuais que deixem o backend técnico de ser a interface principal.

---

## Resultado Esperado da Fase

Ao fim da Fase 2, o programa deve parecer um produto web real.

Ele deve permitir que operadores e usuários internos usem a solução sem depender diretamente de:

- Swagger
- `curl`
- inspeção manual de JSON

---

## Escopo da Fase 2

### 1. Frontend robusto

O frontend da Fase 2 deve incluir:

#### Painel de documentos

- upload visual
- lista de documentos
- filtros
- paginação
- status de processamento
- reprocessamento
- metadata visual
- inspeção de chunks

#### Painel de busca

- caixa de busca
- resultados com evidências
- visualização dos chunks
- score e breakdown
- filtros por documento
- filtros por tipo de arquivo
- filtros por tags

#### Chat web

- pergunta em linguagem natural
- resposta pronta
- citações
- origem do documento
- sinalização de baixa confiança
- groundedness visível
- histórico de consultas

#### Dashboard operacional

- ingestão por período
- groundedness
- cobertura de citação
- hit rate
- latência
- falhas de parsing
- necessidade de reindex

### 2. Recursos premium do motor

- estratégias premium de retrieval quando justificadas
- groundedness melhor apresentado
- anti-hallucination melhor
- comparação de estratégias
- histórico e auditoria de respostas

### 3. UX de produto

- navegação consistente
- experiência visual forte
- telas pensadas para operador funcional
- menos fricção para uso diário

---

## O que entra

- frontend robusto
- chat web
- painéis visuais
- experiência premium
- auditoria de respostas
- dashboards operacionais

## O que ainda não é foco principal

- white-label avançado
- multitenancy forte
- billing enterprise
- governança multiempresa completa

---

## Gate da Fase 2

A Fase 2 é considerada concluída quando houver:

- frontend robusto funcional
- chat web operacional
- painéis de documentos, busca e qualidade
- experiência premium de uso
- produto utilizável sem depender da interface técnica

---

## Próximo Passo

Ir para `0027-plano-de-implementacao-do-frontend-premium.md`, `0028-backlog-por-sprint-do-frontend-premium.md` e `0029-checklist-do-gate-visual-da-fase-2.md`.

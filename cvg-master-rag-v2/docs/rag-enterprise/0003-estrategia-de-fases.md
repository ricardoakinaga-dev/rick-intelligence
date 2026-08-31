# 0003 — Estratégia de Fases

## Objetivo

Definir a evolução do programa até uma versão final **Enterprise Premium**, com backend robusto, frontend forte e operação pronta para escala.

---

## Visão Geral das Fases

```text
FASE 0 ─ FOUNDATION
Motor RAG funcional, API, dataset, métricas mínimas e operação técnica.

FASE 1 ─ OPERAÇÃO PROFISSIONAL
Hardening do motor, melhor observabilidade, melhor retrieval e painel técnico simples.

FASE 2 ─ PRODUTO PREMIUM
Frontend robusto, chat web, painéis operacionais, UX madura e recursos premium de uso diário.

FASE 3 ─ ENTERPRISE PLATFORM
Multitenancy, RBAC, white-label, governança, auditoria, billing e plataforma pronta para múltiplas empresas.
```

---

## Princípio Fundamental

> Cada fase aumenta valor de produto sem perder rastreabilidade técnica.

O projeto não deve parar no “backend que funciona”. O alvo final é um produto utilizável por operadores e usuários não técnicos, com frontend forte e governança real.

---

## 1. Fase 0 — Foundation

### Propósito

Validar o motor RAG.

### Entregas centrais

- API REST
- upload e ingestão
- parsing
- chunking
- embeddings
- Qdrant
- retrieval híbrido
- `/search`
- `/query`
- metadata
- métricas mínimas
- avaliação mínima
- Swagger/OpenAPI

### Tipo de interface

Interface técnica.

### Resultado esperado

Um motor funcional e auditável.

---

## 2. Fase 1 — Operação Profissional

### Propósito

Transformar o motor em base operacional forte.

### Entregas centrais

- melhoria de retrieval
- reranking quando houver evidência
- filtros melhores
- avaliação mais forte
- telemetria mais clara
- painel técnico simples
- inspeção de documentos e chunks
- primeira camada visual para operação

### Tipo de interface

Interface web técnica/operacional.

### Resultado esperado

Um sistema operável sem depender exclusivamente de `curl` e JSON cru.

---

## 3. Fase 2 — Produto Premium

### Propósito

Transformar o sistema em um produto web forte para uso diário.

### Entregas centrais

- frontend robusto
- painel de documentos
- upload visual
- lista de documentos
- status de processamento
- busca visual com evidências
- chat web
- visualização de citações
- histórico de consultas
- dashboard operacional
- auditoria de respostas
- groundedness melhor apresentado
- filtros avançados
- experiência de uso mais madura

### Tipo de interface

Produto web premium.

### Resultado esperado

Uma aplicação que já se comporta como produto real, não apenas como backend.

---

## 4. Fase 3 — Enterprise Platform

### Propósito

Transformar o produto premium em plataforma enterprise.

### Entregas centrais

- multitenancy
- RBAC
- white-label
- gestão de usuários
- painel admin completo
- auditoria forte
- observabilidade enterprise
- dashboards executivos
- billing/quotas, se aplicável
- workflows de aprovação
- governança e segurança endurecidas

### Tipo de interface

Frontend enterprise completo.

### Resultado esperado

Uma plataforma B2B pronta para múltiplas empresas ou unidades operacionais.

---

## Regra de Transição Entre Fases

### F0 → F1

Quando o motor estiver validado e estável.

### F1 → F2

Quando a operação técnica estiver forte o suficiente para justificar investimento em UX e camada de produto.

### F2 → F3

Quando o produto premium estiver claro e houver necessidade real de plataforma multiempresa.

---

## Visão Final

O destino do projeto não é apenas “RAG funcionando”.

O destino é:

- motor RAG forte
- frontend robusto
- experiência de uso diária
- governança
- operação enterprise

---

## Próximo Passo

Ir para:

- `0005-fase-1-rag-profissional.md`
- `0006-fase-2-rag-premium.md`
- `0007-fase-3-rag-enterprise.md`

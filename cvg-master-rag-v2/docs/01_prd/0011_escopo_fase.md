# 0011 — Escopo da Fase

## IN SCOPE (O que será construído/agora)

### 1. Dataset de Avaliação Real
- Criar dataset de 20+ perguntas reais
- Validar schema Pydantic
- Executar baseline hit_rate >= 60%
- Permitir gates verificáveis

### 2. Auth Enterprise Real
- Autenticação server-side (não headers)
- Sessões persistidas (não dependem de headers do cliente)
- Login, logout, recuperação
- RBAC em endpoints centrais

### 3. Isolamento Multi-tenant Provado
- 3 tenants ativos simultaneamente
- Suite de não-vazamento (TKT-010)
- Prova automatizada de isolamento
- Logs de auditoria

### 4. Observabilidade Enterprise
- request_id ponta a ponta
- Métricas por tenant
- Alertas configurados (SLA)
- Health check robusto

### 5. Engenharia Reversa de Documentação
- Pipeline CVG formal: DISCOVERY → PRD → SPEC → BUILD → AUDIT
- Validação de consistência código vs docs
- Gates e transições formalizados

---

## OUT OF SCOPE (O que NÃO será construído agora)

### Features Premium Não Validadas
- **HyDE** — implementado ou removido do roadmap com justificativa
- **Semantic Chunking** — implementado ou justificativa documentada
- **Reranking (Cohere)** — implementado ou justificativa documentada

### Frontend Comercial
- Frontend atual (F2) é suficiente para validação
- Foco é backend, auth, isolamento, observabilidade
- White label e branding adiados para fase futura

### Funcionalidades Enterprise Avançadas
- **Billing e monetização** — não faz parte do escopo
- **Workflows de aprovação** — adiados
- **SSO enterprise** — futuro

---

## FUTURE SCOPE (Possíveis expansões futuras)

### Fase 3+ (Pós gate aprovado)
- Implementação de HyDE se dataset mostrar necessidade
- Semantic chunking para documentos longos
- Reranking se hit rate < 80%
- White label por tenant
- Billing/quotas

### Features de Produto
- Streaming de resposta
- Audio input (FasterWhisper)
- Mais formatos (XLSX, PPT, HTML)
- Tabelas complexas

---

## Critérios de Priorização

| Item | Prioridade | Justificativa |
|---|---|---|
| Dataset real | P0 | Blocker de todos os gates |
| Auth enterprise | P0 | Segurança e isolamento |
| Isolamento provado | P0 | Gate F3 depende |
| Observabilidade | P1 | Operação em produção |
| Engenharia reversa | P1 | Documentação confiável |

---

## Próximo Passo

Avançar para 0012_regras_de_negocio.md
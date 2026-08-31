# 0014 — Requisitos Não Funcionais (Produto)

## Performance

### RNF-01: Latência de Query
- Retrieval deve responder em < 500ms (p95)
- Query completa (com LLM) deve responder em < 5s (p95)
- Medido sem streaming, com top_k=5

### RNF-02: Throughput
- Sistema deve suportar 100+ queries/minuto em produção
- Não deve degradar com aumento de documentos

### RNF-03: Indexação
- Upload + parse + chunk + index deve completar em < 30s para documento de 50 páginas
- Embedding generation é o bottleneck principal

---

## Confiabilidade

### RNF-04: Uptime
- Meta: >= 99% após gate F3 aprovado
- Health check deve indicar status (healthy/degraded/unhealthy)
- Qdrant offline deve causar status degraded

### RNF-05: Recuperação
- Sistema deve ter modo degradado se Qdrant offline
- Logs devem permitir debugging de falhas
- Corpus deve poder ser reindexado via runbook

### RNF-06: Consistência
- Qdrant e disco devem estar sincronizados
- Suite de testes deve validar Qdrant = disco
- Drift deve ser detectado e corrigido

---

## Rastreabilidade

### RNF-07: Request ID
- Toda requisição deve ter request_id único
- request_id deve aparecer em todos os logs
- request_id deve ser propagado em chamadas internas

### RNF-08: Query Log
- Toda query deve ser logada com timestamp, query, results, latency
- Logs devem permitir reconstrução de sessão
- Logs devem ser consultáveis por workspace

### RNF-09: Auditoria Admin
- Eventos administrativos devem ser logados
- Logs devem indicar quem, quando, o que
- Logs devem permitir trilha de auditoria

---

## Segurança

### RNF-10: Autenticação
- Sessões persistidas no servidor
- Tokens com expiração
- Não aceitar headers como autenticação

### RNF-11: Isolamento
- Todo acesso filtrado por workspace_id/tenant
- Impossível acessar dados de outro tenant
- Suite de não-vazamento validando isso

### RNF-12: Autorização
- RBAC em endpoints centrais
- Roles: admin, operator, viewer
- Actions proibidas retornam 403

---

## Operação Multi-usuário

### RNF-13: Concurrent Access
- Múltiplos usuários simultâneos
- Sem race conditions
- Sessões isoladas por usuário

### RNF-14: Multi-tenant
- 3+ tenants ativos simultaneamente
- Cada tenant com dados isolados
- Tenant é filtro obrigatório em todas as operações

---

## Governança

### RNF-15: Retenção de Dados
- Logs mantidos por período configurável
- Métricas agregadas disponíveis
- Dados de tenant isolados na retenção

### RNF-16: Compliance
- Trilha de auditoria para ações administrativas
- Eventos sensíveis logados
- Isolamento comprovado entre tenants

---

## Limitações Conhecidas

- Apenas PDF, DOCX, MD, TXT suportados
- Chunking apenas recursivo (1000/200)
- Sem streaming de resposta
- Sem audio input

---

## Próximo Passo

Avançar para 0015_metricas_de_sucesso.md
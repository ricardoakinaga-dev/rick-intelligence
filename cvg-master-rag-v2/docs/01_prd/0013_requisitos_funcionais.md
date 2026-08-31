# 0013 — Requisitos Funcionais

## Requisitos Funcionais do Sistema

### RF-01: Ingestão de Documentos
- Sistema deve aceitar upload de PDF, DOCX, MD, TXT
- Sistema deve validar formato e tamanho
- Sistema deve extrair texto corretamente
- Sistema deve persistir documento normalizado
- Sistema deve gerar chunks via chunking recursivo
- Sistema deve indexar vetores no Qdrant
- Sistema deve retornar document_id e metadata

### RF-02: Retrieval (Busca)
- Sistema deve aceitar queries textuais
- Sistema deve gerar embeddings da query
- Sistema deve executar busca densa (dense)
- Sistema deve executar busca esparsa (BM25/sparse)
- Sistema deve aplicar fusão RRF
- Sistema deve aplicar filtros (workspace_id, document_id, tags, etc)
- Sistema deve respeitar threshold e top_k configurados
- Sistema deve retornar chunks com scores

### RF-03: Query com Resposta (RAG)
- Sistema deve executar retrieval primeiro
- Sistema deve avaliar low confidence
- Sistema deve montar contexto para LLM
- Sistema deve chamar LLM (GPT-4o-mini)
- Sistema deve formatar resposta com citações
- Sistema deve reportar groundedness e confidence
- Sistema deve logar query e resposta

### RF-04: Autenticação e Sessão
- Sistema deve validar credenciais (email + senha)
- Sistema deve criar sessão persistente no servidor
- Sistema deve retornar session_id/token
- Sistema deve validar sessão em cada requisição
- Sistema deveInvalidar sessão no logout
- Sistema deve expirar sessão após timeout

### RF-05: Autorização (RBAC)
- Sistema deve validar role do usuário
- Sistema deve permitir/negar ações baseado em role
- Sistema deve aplicar filtros de workspace baseados em tenant

### RF-06: Gestão de Tenants (Admin)
- Admin deve poder criar novo tenant
- Admin deve poder editar tenant existente
- Admin deve poder desativar/reativar tenant
- Admin não deve poder remover tenant com dados ativos
- Sistema deve registrar eventos de auditoria

### RF-07: Gestão de Usuários (Admin)
- Admin deve poder criar novo usuário
- Admin deve poder editar usuário (email, role, status)
- Admin deve poder remover usuário
- Admin deve poder associar usuário a tenant(s)
- Sistema deve validar email único

### RF-08: Isolamento Multi-tenant
- Sistema deve filtrar TODAS as queries por workspace/tenant
- Sistema deve garantir que tenant A não veja dados de tenant B
- Sistema deve registrar acesso para auditoria
- Sistema deve validar workspace_id em todas as operações

### RF-09: Avaliação e Dataset
- Sistema deve expor endpoint para avaliação com dataset
- Sistema deve calcular hit_rate_top1, top3, top5
- Sistema deve calcular groundedness, citation_coverage
- Sistema deve persistir resultados de avaliação

### RF-10: Observabilidade
- Sistema deve gerar request_id para cada requisição
- Sistema deve propagar request_id em todos os logs
- Sistema deve expor health check (/health)
- Sistema deve expor métricas (/metrics)
- Sistema deve logar falhas com razão

---

## Capacidades Não Funcionais (Como约束)

- Sistema deve aceitar até 50MB por arquivo
- Sistema deve responder queries em < 5s (sem streaming)
- Sistema deve manter uptime >= 99% após gate F3
- Sistema deve suportar 3+ tenants simultâneos

---

## Próximo Passo

Avançar para 0014_requisitos_nao_funcionais_produto.md
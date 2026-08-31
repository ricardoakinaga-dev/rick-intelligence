# 0010 — Casos de Uso

## Casos de Uso Principais

### CU-01: Upload de Documento

**Ator:** Operator
**Objetivo:** Adicionar novo documento ao corpus
**Gatilho:** Operator seleciona arquivo para upload
**Fluxo Principal:**
1. Operator seleciona arquivo (PDF/DOCX/MD/TXT)
2. Sistema valida formato e tamanho
3. Sistema faz parse e extrai texto
4. Sistema chunka e indexa no Qdrant
5. Sistema retorna document_id e status

**Exceções:**
- Formato não suportado → Erro 400
- Arquivo corrompido → Erro 413
- Qdrant offline → Erro 500

**Resultado Esperado:** Documento disponível para busca

---

### CU-02: Busca por Query

**Ator:** Operator, Admin, qualquer usuário
**Objetivo:** Encontrar documentos relevantes
**Gatilho:** Usuário digita query
**Fluxo Principal:**
1. Usuário digita query
2. Sistema embedda query
3. Sistema executa busca híbrida (dense + sparse + RRF)
4. Sistema retorna top-5 chunks com scores

**Exceções:**
- Query vazia → Erro 400
- Nenhum resultado acima threshold → low_confidence=true
- Qdrant offline → Erro 500

**Resultado Esperado:** Lista de chunks relevantes com scores

---

### CU-03: Consulta com Resposta (RAG Query)

**Ator:** Operator, Admin, qualquer usuário
**Objetivo:** Obter resposta fundamentada em documentos
**Gatilho:** Usuário digita pergunta
**Fluxo Principal:**
1. Usuário digita pergunta
2. Sistema executa busca híbrida
3. Sistema avalia low_confidence
4. Se confiante: sistema monta contexto e chama LLM
5. Sistema retorna resposta com citações

**Exceções:**
- Low confidence → resposta "não sei" com warning
- LLM falha → Erro 500
- Timeout → Erro 504

**Resultado Esperado:** Resposta com groundedness e citations

---

### CU-04: Autenticação e Login

**Ator:** Qualquer usuário
**Objetivo:** Obter sessão autenticada
**Gatilho:** Usuário tenta acessar sistema
**Fluxo Principal:**
1. Usuário acessa página de login
2. Usuário insere credenciais
3. Sistema valida credentials
4. Sistema cria sessão persistente
5. Sistema retorna session_id/token

**Exceções:**
- Credenciais inválidas → Erro 401
- Conta desativada → Erro 403
- Lockout por muitas tentativas → Erro 429

**Resultado Esperado:** Sessão ativa no servidor

---

### CU-05: Gestão de Tenants (Admin)

**Ator:** Admin
**Objetivo:** Criar, editar, remover tenants
**Gatilho:** Admin acessa painel admin
**Fluxo Principal:**
1. Admin acessa /admin
2. Admin lista tenants existentes
3. Admin cria/edita/remove tenant
4. Sistema persiste mudança
5. Sistema registra evento de auditoria

**Exceções:**
- Sem permissão → Erro 403
- Tenant com dados ativos → Erro 409 (proteção)
- Persistência falha → Erro 500

**Resultado Esperado:** CRUD de tenants funcional

---

### CU-06: Gestão de Usuários (Admin)

**Ator:** Admin
**Objetivo:** Criar, editar, remover usuários
**Gatilho:** Admin acessa gestão de usuários
**Fluxo Principal:**
1. Admin acessa /admin/users
2. Admin lista usuários
3. Admin cria/edita/remove usuário
4. Admin associa role (admin/operator/viewer)
5. Sistema persiste e registra auditoria

**Exceções:**
- Sem permissão → Erro 403
- Email duplicado → Erro 409
- Persistência falha → Erro 500

**Resultado Esperado:** CRUD de usuários funcional

---

### CU-07: Isolamento de Tenant

**Ator:** Sistema (automático)
**Objetivo:** Garantir que tenant A não veja dados de tenant B
**Gatilho:** Qualquer requisição com workspace_id
**Fluxo Principal:**
1. Sistema extrai workspace_id da sessão/token
2. Sistema filtra todas as queries por workspace_id
3. Sistema não retorna dados de outros workspaces
4. Logs indicam workspace para auditoria

**Exceções:**
- Workspace inválido → Erro 404
- Sessão expirada → Erro 401

**Resultado Esperado:** Isolamento comprovado entre tenants

---

### CU-08: Validação de Gate com Dataset

**Ator:** QA/Data, Tech Lead
**Objetivo:** Validar qualidade do sistema objetivamente
**Gatilho:** Decisão de gate entre fases
**Fluxo Principal:**
1. Equipe executa suite de avaliação com dataset
2. Sistema calcula hit_rate_top5
3. Se hit_rate >= 60% (F0) → gate aprovado
4. Se hit_rate < 60% → identificar falhas, ajustar, re-testar

**Exceções:**
- Dataset vazio → Erro (não pode validar)
- Query falha → pulo automático no log

**Resultado Esperado:** Decisão objetiva de gate

---

## Casos de Uso Secundários

### CU-09: Logout
- Usuário faz logout
- Sistema invalida sessão
- Frontend redireciona para login

### CU-10: Recuperação de Acesso
- Usuário esqueceu senha
- Sistema envia email de recuperação
- Usuário redefine senha

### CU-11: Visualização de Métricas
- Admin/Operator acessa dashboard
- Sistema mostra métricas de retrieval, answer, evaluation
- Métricas são por workspace/tenant

---

## Próximo Passo

Avançar para 0011_escopo_fase.md
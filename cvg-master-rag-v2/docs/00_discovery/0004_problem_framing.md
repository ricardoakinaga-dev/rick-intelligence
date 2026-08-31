# 0004 — Problem Framing

## Objetivo

Definir exatamente qual parte do problema será resolvida neste programa.

---

## Definição Clara do Problema

### Problema Principal

O programa RAG Enterprise existe como código funcional e documentação extensa, mas não seguiu um pipeline formal de engenharia (Discovery → PRD → SPEC → BUILD → AUDIT). Isso resultou em:

1. **Gaps entre documentação e código** — docs prometem features que não existem
2. **Ausência de dataset validado** — impossibilita gates objetivos
3. **Auth incompleto** — sessões não persistidas, RBAC não completamente enforceado
4. **Features prometidas sem evidência** — HyDE, Semantic, Reranking sem validação
5. **Observabilidade insuficiente** — sem request_id, métricas por tenant, alertas

### Problema Secundário

A transformação de "sistema técnico" para "plataforma enterprise" não está clara em termos de:
- O que exatamente constitui a "plataforma enterprise"
- Quais gates precisam ser aprovados para validar a transformação
- Qual a sequência correta de implementação

---

## Escopo do Problema

### O QUE SERÁ RESOLVIDO

1. **Engenharia reversa do programa existente**
   - Criar documentação seguindo pipeline CVG
   - Validar consistência entre código e documentação
   - Formalizar gates e transições de fase

2. **Dataset de avaliação real**
   - Criar 20+ perguntas reais (não sintéticas)
   - Validar com hit rate objetivo
   - Permitir gates verificáveis

3. **Auth enterprise real**
   - Implementar autenticação no servidor
   - Persistir sessões
   - Enforcear RBAC server-side

4. **Isolamento multi-tenant provado**
   - Garantir que tenant A não vê dados de tenant B
   - Validar com 3 tenants ativos
   - Documentar evidência de não-vazamento

5. **Observabilidade enterprise**
   - request_id ponta a ponta
   - Métricas por tenant
   - SLI/SLO com alertas

### O QUE NÃO SERÁ RESOLVIDO NESTA FASE

1. **Implementação de features premium não validadas**
   - HyDE não será implementado sem evidência de benefício
   - Semantic chunking não será implementado sem evidência
   - Reranking não será implementado ou será documentada justificativa

2. **Frontend comercial completo**
   - Foco é backend + observabilidade + auth
   - Frontend existente é suficiente para validação

3. **Billing e monetização**
   - Não faz parte do escopo atual

4. **White label e branding por tenant**
   - Adiado para fase futura

5. **Workflows de aprovação administrativa**
   - Adiado para fase futura

---

## Limites da Solução

### Limite 1: Dataset Mínimo
- 20+ perguntas reais
- Múltiplos documentos
- Hit rate top-5 >= 60% para gate F0

### Limite 2: Auth server-side
- Login, logout, recuperação
- Sessões persistidas em memória/servidor
- RBAC em endpoints centrais

### Limite 3: Isolamento verificado
- 3 tenants ativos
- Prova de não-vazamento
- Logs de auditoria

### Limite 4: Observabilidade básica
- request_id
- Métricas por tenant
- Health check
- Logs estruturados

---

## Simplificação do Problema

### Problema Complexo (Original)
"Transformar sistema RAG técnico em plataforma enterprise premium completa"

### Problema Simplificado (Esta Fase)
"Validar e corrigir o programa existente seguindo pipeline CVG, criando dataset real, auth enterprise, isolamento multi-tenant provado e observabilidade básica"

### Por que essa simplificação é válida
- Código já existe e é funcional
- Frontend já existe e é robusto
- Gates anteriores foram aprovados com evidências
- Foco deve ser em fechar gaps restantes com evidência

---

## Métricas de Sucesso

### Métrica 1: Nota Geral >= 92/100
- Conforme auditoria 0037-roadmap-executivo
- Atual está em 87/100
- Gap de 5 pontos por fechar

### Métrica 2: Dataset Verificável
- 20+ perguntas reais
- Hit rate >= 60% no gate
- Schema Pydantic validado

### Métrica 3: Auth Enterprise
- Sessões persistidas
- RBAC em endpoints centrais
- Não depende de headers do cliente

### Métrica 4: Isolamento Provado
- 3 tenants ativos
- Não vazamento verificado
- Auditoria documentada

### Métrica 5: Observabilidade
- request_id implementado
- Métricas por tenant
- Alertas configurados

---

## Próximo Passo

Avançar para Hipótese de Valor (0005_hipotese_de_valor.md)
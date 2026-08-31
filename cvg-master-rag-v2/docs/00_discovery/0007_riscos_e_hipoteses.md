# 0007 — Riscos e Hipóteses

## Objetivo

Mapear incertezas antes de avançar para o PRD.

---

## Hipóteses Não Validadas

### Hipótese 1: Dataset Real Terá Hit Rate >= 60%
- **Descrição:** Criar 20+ perguntas reais e validar que retrieval retorna documento correto no top-5
- **Status:** Não validado (dataset não existe)
- **Risco:** Se hit rate < 60%, sistema precisa de tuning antes de gate
- **Mitigação:** Identificar falhas e fazer tuning de chunk_size/overlap antes de validar

### Hipótese 2: Auth Server-side Não Quebrará Frontend
- **Descrição:** Implementar autenticação real no servidor sem quebrar fluxo do frontend existente
- **Status:** Não validado (auth atual usa headers)
- **Risco:** Breaking change no fluxo de autenticação
- **Mitigação:** Implementar incrementalmente, testar com smoke tests

### Hipótese 3: Isolamento Multi-tenant Funciona com 3 Tenants
- **Descrição:** Provar que tenant A não vê dados de tenant B
- **Status:** Não validado (não há 3 tenants ativos)
- **Risco:** Vazamento de dados entre tenants
- **Mitigação:** Suite de não-vazamento (TKT-010)

### Hipótese 4: Observabilidade Não Impacta Performance
- **Descrição:** Adicionar request_id e logging não degrada latência significativamente
- **Status:** Não validado (observabilidade limitada)
- **Risco:** Overhead de logging em produção
- **Mitigação:** Medir latência antes/depois, async logging

### Hipótese 5: Features Premium Não São Necessárias Agora
- **Descrição:** HyDE, Semantic, Reranking podem esperar porque baseline é suficiente
- **Status:** Não validado (features promissas mas não implementadas)
- **Risco:** Decidir errado e perder oportunidade de melhoria
- **Mitigação:** Dataset real vai mostrar se há gap de qualidade que premium features resolveriam

---

## Riscos Operacionais

### Risco 1: Dataset Sintético Não Representa Realidade
- **Probabilidade:** Alta
- **Impacto:** Alto
- **Mitigação:** Usar perguntas de usuários reais ou validadas por domain expert

### Risco 2: Breaking Change em Auth
- **Probabilidade:** Média
- **Impacto:** Alto
- **Mitigação:** Backward compatibility, testes incrementais

### Risco 3: Gap Entre Docs e Código Muito Grande
- **Probabilidade:** Alta (0026 identificou isso)
- **Impacto:** Médio
- **Mitigação:** Validar código vs docs antes de fazer engenharia reversa

### Risco 4: Resistência a Mudanças
- **Probabilidade:** Média
- **Impacto:** Médio
- **Mitigação:** Comunicação clara, benefícios demonstrados

---

## Riscos de Adoção

### Risco 1: Equipe Não Usa Dataset Real
- **Probabilidade:** Média
- **Impacto:** Alto
- **Mitigação:** Automatizar validação, gates condicionados a dataset

### Risco 2: Auth Nova Quebra Fluxo Existente
- **Probabilidade:** Média
- **Impacto:** Alto
- **Mitigação:** Smoke tests, rollback plan

### Risco 3: Documentação Não Auditada
- **Probabilidade:** Alta
- **Impacto:** Médio
- **Mitigação:** Revisão de consistência antes de proceder

---

## Dependências Externas

### Dependência 1: OpenAI API
- **Descrição:** Embeddings e LLM dependem de OpenAI
- **Risco:** Rate limits, custo, disponibilidade
- **Mitigação:** Cache de embeddings, fallback offline

### Dependência 2: Qdrant
- **Descrição:** Vector database central
- **Risco:** Single point of failure
- **Mitigação:** Health checks, modo degradado

### Dependência 3: Infraestrutura de Hosting
- **Descrição:** Onde o sistema roda
- **Risco:** Custos, disponibilidade
- **Mitigação:** Documentar requisitos

---

## Limitações Conhecidas

### Limitação 1: Apenas 4 Formatos
- PDF, DOCX, MD, TXT
- XLSX, PPT, HTML não suportados

### Limitação 2: Chunking Apenas Recursive
- Semantic, Page-by-page, Agentic não implementados

### Limitação 3: Sem Audio
- Transcrição não faz parte do pipeline

### Limitação 4: Sem Streaming de Resposta
- Responses são geradas completas, não em stream

---

## Próximo Passo

Avançar para Consolidação (0009_discovery_master.md)
# 0009 — Discovery Master

## Visão Geral

Este documento consolida todo o discovery realizado para o programa RAG Enterprise Premium, transformando o estado atual do sistema em um problema estruturado e pronto para evolução em PRD.

---

## Problema Definido

O programa RAG Enterprise existe como código funcional e documentação extensa, mas não seguiu um pipeline formal de engenharia (Discovery → PRD → SPEC → BUILD → AUDIT). Isso resultou em:

1. **Gaps entre documentação e código** — docs prometem features que não existem
2. **Ausência de dataset validado** — impossibilita gates objetivos
3. **Auth incompleto** — sessões não persistidas, RBAC não completamente enforceado
4. **Features prometidas sem evidência** — HyDE, Semantic, Reranking sem validação
5. **Observabilidade insuficiente** — sem request_id, métricas por tenant, alertas

### Nota Atual do Programa (Auditoria 2026-04-17)
- **Geral:** 87/100
- F0 — Foundation: 95/100 ✅ Funcional
- F1 — Profissional: 78/100 ⚠️ Parcial
- F2 — Premium: 82/100 ⚠️ Frontend OK, features pendentes
- F3 — Enterprise: 60/100 ❌ Bloqueado

---

## Contexto

### Estado Atual do Sistema

O sistema atual consiste em:

**Backend (FastAPI + Python)**
- Ingestão multi-formato (PDF, DOCX, MD, TXT)
- Chunking recursivo (1000/200)
- Retrieval híbrido (dense + sparse + RRF)
- Query com grounding e citações
- Telemetria básica (`/metrics`, `/health`)
- Auth baseado em headers (X-Enterprise-*)

**Frontend (Next.js 15)**
- Shell principal com navegação
- Painel de documentos com upload
- Tela de busca com evidências
- Chat web funcional
- Dashboard operacional
- Auditoria de respostas
- Admin panel para tenants e usuários

**Infraestrutura**
- Qdrant (vector database)
- Filesystem (armazenamento de corpus)
- OpenAI (embeddings + LLM)

### Estado das Fases

| Fase | Status | Nota | Gate |
|---|---|---|---|
| F0 — Foundation | ✅ Funcional | 95/100 | Liberado |
| F1 — Profissional | ⚠️ Parcial | 78/100 | Parcial |
| F2 — Premium | ⚠️ Frontend OK | 82/100 | Aprovado |
| F3 — Enterprise | ❌ Bloqueado | 60/100 | Não aprovado |

---

## Fluxo Atual

### Pipeline de Ingestão
```
Upload → Validação → Parse → Normalização → Chunking → Indexação → Retorno
```

### Pipeline de Retrieval
```
Query → Embedding → Busca Densa → Busca Esparsa → RRF → Filtragem → Retorno
```

### Pipeline de Query (RAG)
```
Query → Retrieval → Low Confidence Check → Contexto → LLM → Resposta → Logging
```

---

## Escopo do Problema

### O Que Será Resolvido

1. **Engenharia reversa do programa**
   - Documentação seguindo pipeline CVG
   - Validação de consistência código vs docs
   - Formalização de gates e transições

2. **Dataset de avaliação real**
   - 20+ perguntas reais
   - Hit rate >= 60% para gate
   - Schema Pydantic validado

3. **Auth enterprise real**
   - Autenticação server-side
   - Sessões persistidas
   - RBAC em endpoints centrais

4. **Isolamento multi-tenant provado**
   - 3 tenants ativos
   - Não-vazamento verificado
   - Logs de auditoria

5. **Observabilidade enterprise**
   - request_id ponta a ponta
   - Métricas por tenant
   - Alertas configurados

### O Que Não Será Resolvido

1. Features premium não validadas (HyDE, Semantic, Reranking)
2. Frontend comercial completo
3. Billing e monetização
4. White label e branding
5. Workflows de aprovação

---

## Usuários e Stakeholders

| Papel | Responsabilidade | Needs |
|---|---|---|
| Operator | Upload, query, monitoramento | UI, métricas |
| Admin | Gestão de tenants e usuários | Admin panel, RBAC |
| QA/Data | Validação de gates | Dataset, métricas |
| Dev Backend | Features, manutenção | Docs, código consistente |
| Dev Frontend | UI, integração | Contratos estáveis |
| SRE/DevOps | Operação, incidentes | Observabilidade, tracing |
| Tech Lead | Decisões, roadmap | Visão clara, gaps |
| PM | Produto, priorização | Gates verificáveis |

---

## Hipótese de Valor

### O Que Melhora
1. **Validação de Gates** — critérios objetivos, não subjetivos
2. **Segurança e Isolamento** — auth server-side, RBAC completo
3. **Operações de Produção** — request_id, métricas, alertas
4. **Confiança na Documentação** — código e docs alinhados

### Indicadores de Sucesso
- Nota geral >= 92/100 (de 87/100 atual)
- Dataset verificável (20+ perguntas, hit rate >= 60%)
- Auth enterprise (sessões persistidas, RBAC server-side)
- Isolamento provado (3 tenants, não-vazamento)
- Observabilidade (request_id, métricas por tenant, alertas)

---

## Riscos Identificados

### Hipóteses Não Validadas
1. Dataset real terá hit rate >= 60%
2. Auth server-side não quebrará frontend
3. Isolamento multi-tenant funciona com 3 tenants
4. Observabilidade não impacta performance
5. Features premium não são necessárias agora

### Riscos Operacionais
1. Dataset sintético não representa realidade
2. Breaking change em auth
3. Gap entre docs e código muito grande
4. Resistência a mudanças

### Dependências Externas
1. OpenAI API (rate limits, custo)
2. Qdrant (single point of failure)
3. Infraestrutura de hosting

---

## Próximo Passo

Avançar para PRD (01_prd/) para transformar este problema em produto definido.
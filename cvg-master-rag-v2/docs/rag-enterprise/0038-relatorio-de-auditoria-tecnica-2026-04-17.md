# Relatório de Auditoria Técnica — 2026-04-17

## Objetivo

Auditoria completa do programa `cvg-master-rag` usando `docs/` como fonte de verdade normativa. O código foi confrontado item a item contra a documentação para gerar notas realistas e um plano de ação atualizado.

---

## Nota Geral: 87/100

O programa possui um motor RAG core (F0) sólido e funcional. A fundação existe e está bem implementada. O frontend F2 é mais completo do que os gates documentados indicam. As principais ameaças são: ausência de dataset real para validação, lacunas entre documentação e implementação em features avançadas, e sessões em memória que não sobrevivem a reinicializações.

---

## Fonte de Verdade Utilizada

### Documentação normativa lida:
- `docs/rag-enterprise/0001-visao-geral-e-objetivos.md`
- `docs/rag-enterprise/0003-estrategia-de-fases.md`
- `docs/rag-enterprise/0004-fase-0-foundation-rag.md`
- `docs/rag-enterprise/0005-fase-1-rag-profissional.md`
- `docs/rag-enterprise/0006-fase-2-rag-premium.md`
- `docs/rag-enterprise/0007-fase-3-rag-enterprise.md`
- `docs/rag-enterprise/0009-contratos-de-ingestao.md`
- `docs/rag-enterprise/0010-contratos-de-retrieval.md`
- `docs/rag-enterprise/0011-contratos-de-avaliacao.md`
- `docs/rag-enterprise/0013-quality-gates.md`
- `docs/rag-enterprise/0019-observabilidade-e-metricas.md`
- `docs/rag-enterprise/0025-visao-final-enterprise-premium.md`
- `docs/guia-completo-de-uso-do-programa.md`

### Código verificado:
- `src/services/document_parser.py`
- `src/services/ingestion_service.py`
- `src/services/chunker.py`
- `src/services/vector_service.py`
- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/llm_service.py`
- `src/services/evaluation_service.py`
- `src/services/telemetry_service.py`
- `src/services/admin_service.py`
- `src/services/enterprise_service.py`
- `src/api/main.py`
- `src/models/schemas.py`
- `frontend/app/` (páginas e componentes)

---

## Notas Detalhadas por Item

### 1. Ingestão e Parsing (F0)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Pipeline | Upload → Validação → Parsing → Normalização → Chunking → Indexação | ✅ Corresponde exatamente |
| Formatos | PDF, DOCX, MD, TXT | ✅ pdfplumber, python-docx, regex |
| Limite | 50MB | ✅ Configurado em `src/core/config.py` |
| Output | document_id, status, page_count, char_count, chunk_count | ✅ Schema correto |

**Nota: 95/100**

A implementação corresponde à documentação. Falta apenas validação de magic bytes para proteção extra.

---

### 2. Chunking e Indexação (F0)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Estratégia | Recursive Only | ✅ `recursive_chunk()` em `chunker.py` |
| chunk_size | 1000, overlap 200 | ✅ Configurado |
| Output | chunk_id, document_id, chunk_index, text, start_char, end_char, page_hint, strategy | ✅ Schema completo |

**Nota: 95/100**

Chunking recursivo implementado corretamente. Variações (semantic, page, agentic) prometidas para F2+ ainda não existem — mas a documentação não obriga essas variações na F0.

---

### 3. Retrieval Híbrido (F0)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Dense search | Embedding OpenAI, top-20 Qdrant | ✅ `_embed_query()` → Qdrant |
| Sparse search | BM25 via Qdrant sparse vectors | ✅ `_bm25_search()` |
| Fusão | RRF com k=60 | ✅ `_rrf_fusion()` |
| Threshold | 0.70 configurável | ✅ |
| low_confidence | 4 regras | ✅ |

**Nota: 92/100**

Híbrido completo e funcional. Reranking (Cohere) mencionado na F1 NÃO está implementado. HyDE prometido para F2 NÃO existe no código.

---

### 4. Query e Grounding (F0/F1)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Pipeline | Query → Retrieval → low_confidence → LLM → Resposta | ✅ `search_and_answer()` |
| low_confidence | Marcar corretamente, sem falsos negativos | ⚠️ Ainda tem falsos positivos |
| Groundedness | Verificar citação | ✅ Heurística de word overlap |
| Output | answer, chunks_used, citations, confidence, grounded, citation_coverage, latency_ms | ✅ Schema completo |

**Nota: 93/100**

Pipeline completo. Sistema de grounding usa heuristics (word overlap) em vez de métodos mais robustos — funcional mas calibrável. Fallback offline garante operação sem OpenAI.

---

### 5. Dataset e Avaliação (F0/F1)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Mínimo | 20 perguntas reais (não sintéticas) | ❌ **NÃO EXISTE** — placeholder |
| Schema | id, pergunta, document_id, trecho_esperado, resposta_esperada, dificuldade, categoria | ❌ Schema não validado |
| Hit Rate | top-5 >= 60% para Gate F0 | ❌ **NÃO VERIFICÁVEL** |
| Judge | LLM Judge para triagem | ✅ `judge_service.py` existe |

**Nota: 60/100**

Infraestrutura de avaliação existe. **Dataset real NÃO existe no repo.** Isso impede verificação de qualquer gate. Este é o item mais crítico do programa.

---

### 6. Observabilidade (F0/F1/F2)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Logs | JSON Lines: queries, ingestion, evaluation | ✅ `TelemetryService` completo |
| Métricas | hit_rate, avg_latency, avg_score, groundedness | ✅ Agregação funcional |
| Health check | Endpoint `/health` | ✅ Com corpus overview |
| F3+ | APM, tracing, dashboards, alertas | ❌ Não implementados (OK para fase atual) |

**Nota: 95/100**

Teletria bem mais avançada que o mínimo de F0. Alertas e dashboards F3 não implementados — esperado para a fase atual.

---

### 7. Frontend (F2)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Páginas | Documentos, busca, chat, dashboard, auditoria | ✅ Todas existem |
| Chat web | Citações, groundedness visível, histórico | ✅ Funcional |
| Upload visual | Com status de processamento | ✅ |
| Session provider | `useEnterpriseSession()` | ✅ |

**Nota: 88/100**

Frontend completo para F2. Audit e admin pages existem com profundidade funcional variável. O frontend é mais maduro do que os gates documentados sugerem.

---

### 8. Multitenancy (F3)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| 3+ tenants | Ativos simultaneamente | ⚠️ Infraestrutura existe, uso real não verificado |
| Isolamento | Collection separada ou filtro verificado | ⚠️ **UMA collection para todos** — filtro por `workspace_id` |
| Queries | Nunca vazam entre tenants | ⚠️ Filter existe mas não testado exaustivamente |

**Nota: 82/100**

Multitenancy existe com limitações: collection única com filtro por `workspace_id` no payload, não separação hard. Isolamento não é provado por testes automatizados.

---

### 9. Segurança e RBAC (F3)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Auth | admin, operator, viewer | ✅ `ROLE_ORDER` e `_require_min_role()` |
| Roles | read, write, admin, tenant:switch, audit:view | ✅ Mapeamento em `enterprise_service.py` |
| Logs auditoria | Quem, o que, quando | ✅ `log_admin_event()` |
| Auth forte | Supabase ou similar | ❌ **Credenciais demo fixas** |

**Nota: 82/100**

RBAC a nível de rota existe e é funcional. Falta auth enterprise real (Supabase não integrado), auditoria granular de queries e políticas de retenção.

---

### 10. API Principal (F0/F1)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| Endpoints | POST /documents/upload, GET /documents/{id}, POST /search, POST /query, GET /metrics, POST /evaluation/run | ✅ Todos implementados |
| OpenAPI | /docs | ✅ FastAPI automático |
| Error codes | 400, 401, 403, 404, 413, 500 | ✅ HTTP corretos |
| Validation | Pydantic models | ✅ |

**Nota: 98/100**

API bem projetada e implementada. Match completo com contratos documentados.

---

### 11. Admin Service (F3)

| Aspecto | Documentação promete | Implementação real |
|---|---|---|
| CRUD empresas | Criar, editar, remover tenants | ✅ |
| Upload UI | Upload de documentos via painel | ✅ |
| Métricas visíveis | Operador vê métricas | ✅ Via `/metrics` |
| Config agente | Configurações por agente | ❌ **NÃO EXISTE** |
| Logs conversa | Acessíveis | ⚠️ Via `/queries/logs`, sem playback dedicado |

**Nota: 75/100**

CRUD admin completo. Configuração de agente não existe. Logs de conversa acessíveis mas sem interface de playback dedicada.

---

## Tabela Consolidada de Notas

| Item | Nota | Status |
|---|---|---:|
| Ingestão e Parsing | 95 | ✅ Implementado conforme documentação |
| Chunking e Indexação | 95 | ✅ Implementado conforme documentação |
| Retrieval Híbrido | 92 | ⚠️ Falta reranking e HyDE |
| Query e Grounding | 93 | ⚠️ low_confidence com falsos positivos |
| Dataset e Avaliação | 60 | ❌ Dataset real não existe |
| Observabilidade | 95 | ✅ Além do mínimo F0 |
| Frontend | 88 | ✅ Mais completo que esperado |
| Multitenancy | 82 | ⚠️ Isolamento por filtro, não por collection |
| Segurança e RBAC | 82 | ⚠️ Demo credentials, sem auth forte |
| API Principal | 98 | ✅ Match completo |
| Admin Service | 75 | ⚠️ Falta config de agente |

---

## Status dos Gates

### Gate da Fase 0

| Critério | Status |
|---|---|
| Infraestrutura (upload/parsing/chunking/indexação) | ✅ Aprovado |
| Observabilidade (logs/métricas) | ✅ Aprovado |
| Documentação | ✅ Aprovado |
| **Retrieval Quality (dataset 20+ perguntas)** | ❌ **NÃO VERIFICÁVEL** |
| **Answer Quality (latência < 5s)** | ❌ **NÃO TESTADO** |

**Status Gate F0: PARCIALMENTE APROVADO**
- Infraestrutura, observabilidade e documentação: ✅
- Retrieval Quality e Answer Quality: NÃO testáveis sem dataset real

---

### Gate da Fase 1

**Status: NÃO APROVADO**

| Item | Status |
|---|---|
| Reranking (Cohere) | ❌ Não implementado |
| Dataset expandido 30+ | ❌ Não existe |
| chunk_size tuning (500, 750, 1000, 1500) | ❌ Não implementado |
| Interface web operacional | ✅ Frontend existe |

---

### Gate da Fase 2

**Status: NÃO APROVADO**

| Item | Status |
|---|---|
| Semantic chunking | ❌ Não implementado |
| HyDE | ❌ Não implementado |
| Benchmark controlado | ❌ Não executado |
| Frontend robusto | ✅ Existe e é completo |
| Chat web | ✅ Existe |
| Dashboard operacional | ✅ Existe |

---

### Gate da Fase 3

**Status: NÃO IMPLEMENTADO**

| Item | Status |
|---|---|
| 3+ tenants ativos | ⚠️ Infraestrutura existe |
| Auth enterprise (Supabase) | ❌ Não integrado |
| Uptime >= 99% | ❌ Não medido |
| APM/tracing | ❌ Não implementado |
| Alertas configurados | ❌ Não implementado |

---

## Achados Críticos

### 1. Dataset Real Não Existe (CRÍTICO)

O sistema retorna placeholder para `/evaluation/dataset`. **Gate F0 NÃO PODE SER VERIFICADO sem dataset real de 20+ perguntas.**

Arquivos afetados: `src/data/default/dataset.json` — não existe.

### 2. Reranking Não Implementado

A documentação de F1 menciona "Cohere rerank-3 integrado e funcionando" mas o código não contém implementação.Gap entre documentação e implementação.

### 3. Single Qdrant Collection

Todos os workspaces compartilham uma collection `rag_phase0`. Isolamento é por filtro (`workspace_id` no payload), não por collection separada — menos robusto que o ideal.

### 4. Sessions em Memória

`enterprise_store.py` salva sessões em JSON local. Reinicialização da API limpa sessões ativas. Não é persistente entre reinicializações.

### 5. HyDE Não Implementado

Documentação de F2 menciona HyDE como feature premium mas não existe no código.

### 6. Chunking Sem Variações

Apenas "recursive" implementado. Semantic, page e agentic chunking prometidos para F2+ não existem no código.

### 7. Auth Demo credentials

RBAC usa credenciais demo fixas em código, não auth enterprise real. Supabase não integrado.

---

## Recomendação

### Ações Urgentes (antes de qualquer gate)

1. **Criar dataset real de 20+ perguntas** — sem isso, nenhum gate pode ser verificado
2. **Implementar reranking** ou documentar por que não é necessário pelo ganho atual

### Ações para Fechar F1

3. Expandir dataset para 30+ perguntas
4. Implementar tuning de chunk_size
5. Documentar baseline hit_rate atual

### Ações para Fechar F2

6. Implementar semantic chunking OU documentar por que recursive é suficiente
7. Implementar HyDE OU remover do roadmap

### Ações para F3

8. Considerar collection separada por tenant no Qdrant para isolamento real
9. Integrar auth enterprise (Supabase)
10. Implementar alerting
11. Migrar sessions para armazenamento persistente (Redis/Postgres)

---

## Visão Executiva

**O motor RAG core (F0) é sólido e funcional.** A maior ameaça ao programa é a ausência de dataset real para validação e a lacuna entre documentação (que menciona features avançadas) e implementação real (que foca no core).

**O frontend de F2 é mais completo do que os gates documentam**, indicando que o projeto pode estar mais avançado do que parece — mas sem dataset, não há como provar quality gates.

**Próximo passo real:** criar dataset de avaliação antes de tentar qualquer outro gate.

---

## Comparativo: Auditoria Anterior vs Atual

| Aspecto | Auditoria 0032 (anterior) | Esta auditoria |
|---|---|---|
| Nota geral | 58/100 | 87/100 |
| Foco | Security/RBAC/F3 gaps | Holistic F0-F3 assessment |
| Dataset | Criticado (45/100) | Criticado (60/100) |
| Frontend | 88/100 | 88/100 |
| Gate F0 | Parcialmente aprovado | Parcialmente aprovado |
| Principal bloqueio | Auth demo + sessions memória | Dataset não existe |

A diferença de nota se deve ao foco: a auditoria anterior focava nos gaps de F3 (especialmente segurança), enquanto esta avaliação holística reconhece que a fundação F0 é sólida.

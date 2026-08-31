# 0112 — Integrações Externas

## Integrações Necessárias

### Integração 1: OpenAI API

**Objetivo:**
- Embeddings (text-embedding-3-small)
- LLM (GPT-4o-mini)

**Dados recebidos:**
- Embedding vectors (1536 dim)
- Generated text responses

**Dados enviados:**
- Text chunks for embedding
- Query + context for LLM

**Contrato:**
```python
# Embedding
openai.Embedding.create(
    model="text-embedding-3-small",
    input=text
) → [{"embedding": [...]}]

# LLM
openai.ChatCompletion.create(
    model="gpt-4o-mini",
    messages=[...]
) → {"choices": [{"message": {"content": "..."}}]}
```

**Autenticação:** API Key (OPENAI_API_KEY env var)

**Falhas esperadas:**
- Rate limit (429)
- Invalid request (400)
- Server error (500)

**Contingência:**
- Rate limit: exponential backoff
- Invalid request: return error to user
- Server error: retry 2x, then error

---

### Integração 2: Qdrant

**Objetivo:**
- Vector storage (dense + sparse)
- Hybrid search

**Dados recebidos:**
- Search results (chunk_ids, scores)
- Collection stats

**Dados enviados:**
- Vectors for indexing
- Query vectors for search

**Contrato:**
```python
# Index
client.insert(
    collection_name="rag_phase0",
    points=[...]
)

# Search
client.search(
    collection_name="rag_phase0",
    query_vector=...,
    limit=top_k,
    query_filter=workspace_filter
)
```

**Autenticação:** URL + API key (QDRANT_URL, QDRANT_API_KEY env vars)

**Falhas esperadas:**
- Connection error
- Collection not found
- Search timeout

**Contingência:**
- Connection error: health check returns degraded
- Collection not found: create or error
- Timeout: retry, then error

---

## Integração 3: Filesystem (Corpus Storage)

**Objetivo:**
- Persistir raw documents e chunks

**Dados recebidos:**
- None (writes only)

**Dados enviados:**
- File content for parsing

**Contrato:**
```python
# Read
with open(f"src/data/documents/{workspace_id}/{doc_id}_raw.json") as f:
    return json.load(f)

# Write
with open(f"src/data/documents/{workspace_id}/{doc_id}_raw.json", "w") as f:
    json.dump(data, f)
```

**Falhas esperadas:**
- File not found
- Permission denied
- Disk full

**Contingência:**
- File not found: return 404
- Permission denied: return 500
- Disk full: return 500

---

## Integrações Adiadas (Future Scope)

### Supabase Auth
- Autenticação enterprise com SSO
- Entra na Fase 3+ se necessidade real

### MinIO / S3
- Object storage para documentos
- Entra quando múltiplos serviços precisarem

### Cohere Rerank
- Reranking premium
- Entra se hit rate < 80% e evidência de benefício

---

## Observabilidade das Integrações

### OpenAI
- Log: embedding_time_ms, llm_time_ms
- Métricas: avg_latency, error_rate

### Qdrant
- Log: search_time_ms, index_time_ms
- Métricas: points_count, avg_search_latency

### Filesystem
- Log: file_read_time, file_write_time
- Métricas: storage_used

---

## Próximo Passo

Avançar para 0113_observabilidade_runtime_e_operacao.md
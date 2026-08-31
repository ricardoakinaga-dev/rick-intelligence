# 0109 — Dados e Persistência

## Estratégia de Dados

### Corpus (Documents + Chunks)
- **Storage:** Filesystem local (`src/data/documents/{workspace_id}/`)
- **Formato:** JSON estruturado
  - `{document_id}_raw.json` — documento normalizado
  - `{document_id}_chunks.json` — chunks extraídos
- **Responsável:** IngestionModule

### Vectors (Qdrant)
- **Storage:** Qdrant (vector database)
- **Collections:** `rag_phase0` (single collection com workspace_id filter)
- **Vectors:** Dense (OpenAI) + Sparse (BM25)
- **Responsável:** RetrievalModule

### Metadata (Database)
- **Opção atual:** Sem database relacional
- **Modelagem via:** In-memory + filesystem
- **Futuro:** PostgreSQL quando multitenancy real需求

### Sessions
- **Storage:** In-memory (Python dict)
- **TTL:** Configurável (default: 24h)
- **Responsável:** AuthModule

---

## Consistência Transacional

### Upload → Index
```
1. Save raw.json
2. Save chunks.json
3. Generate embeddings
4. Index in Qdrant
5. Update document status
```
Se passo 4 falhar:
- Status = "partial"
- Retry via reindex script

### Query → Response
```
1. Search Qdrant (no write)
2. Evaluate low confidence
3. If confident: call LLM
4. Log query
5. Return response
```
Tudo read-only, exceto logging.

---

## Auditoria

### Query Logs
- Location: `src/logs/queries.jsonl`
- Format: JSON Lines
- Retention: until rotation

### Admin Audit
- Events logged via AdminAction event
- Stored in query logs
- Aggregated in /metrics

---

## Versionamento de Dados

### Document
- Versão implícita (v1)
- No versioning no momento
- Future: parent_document_id for versions

### Chunks
- Regenerados se chunking strategy mudar
- Corpus pode ser reindexado

---

## Retenção

| Tipo | Retenção |
|---|---|
| Documents | Until deleted by user |
| Chunks | Until document deleted |
| Query logs | Until rotation (100MB) |
| Admin logs | Until rotation |

---

## Próximo Passo

Avançar para 0110_consistencia_integridade_e_migracoes.md
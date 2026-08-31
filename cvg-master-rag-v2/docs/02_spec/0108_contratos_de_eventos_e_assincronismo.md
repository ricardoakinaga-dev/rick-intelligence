# 0108 — Contratos de Eventos e Assincronismo

## Eventos Emitidos

### Evento 1: DocumentUploaded

**Quando:** Upload de documento concluído com sucesso
**Payload:**
```python
{
    "event": "document.uploaded",
    "timestamp": "ISO8601",
    "request_id": "uuid",
    "workspace_id": "uuid",
    "document_id": "uuid",
    "filename": "string",
    "source_type": "pdf|docx|md|txt",
    "chunk_count": int,
    "status": "parsed"
}
```
**Consumidores:**
- Telemetry (logs)
- Não há consumers externos neste escopo

---

### Evento 2: QueryExecuted

**Quando:** Query RAG executada
**Payload:**
```python
{
    "event": "query.executed",
    "timestamp": "ISO8601",
    "request_id": "uuid",
    "workspace_id": "uuid",
    "user_id": "uuid | None",
    "query": "string",
    "low_confidence": bool,
    "chunks_used": list[str],
    "latency_ms": int,
    "confidence": "high|medium|low"
}
```
**Consumidores:**
- Telemetry (logs de query)
- Metrics aggregation

---

### Evento 3: AdminAction

**Quando:** Ação administrativa executada
**Payload:**
```python
{
    "event": "admin.action",
    "timestamp": "ISO8601",
    "request_id": "uuid",
    "user_id": "uuid",
    "action": "create_tenant|update_tenant|delete_tenant|create_user|update_user|delete_user",
    "target_type": "tenant|user",
    "target_id": "uuid",
    "result": "success|failure",
    "reason": "string | None"
}
```
**Consumidores:**
- Telemetry (logs de auditoria)
- Audit trail

---

## Processamento Assíncrono

### Contexto: Indexação de Documentos

**Atual:** Processamento síncrono
- Upload → Parse → Chunk → Embed → Index → Return

**Alternativa considerada:** Background workers
- Decisão: MANTER SÍNCRONO para F0-F2
- Justificativa: Simplicidade, debugging fácil

**Quando reconsiderar:** Se latência de upload > 10s consistently

---

### Contexto: Geração de Embeddings

**Atual:** OpenAI API call síncrono
- Chunk → Embedding API → Vector

**Fallback:**
- Se OPENAI_API_KEY não configurada: usar mock determinístico
- Testes podem rodar offline

---

## Retry e Idempotência

### Retry Policy

- Indexação: retry 3x com exponential backoff
- LLM calls: retry 2x com timeout 30s

### Idempotência

- Upload: baseado em file hash + workspace_id
- Query: request_id como idempotency key

---

## DLQ / Reprocessamento

### Quando aplicável
- Indexação falha: documento fica em status "partial"
- Pode ser reexecutado via reindex script

### Como evitar
- Validação de formato antes de processar
- Health check antes de aceitar upload

---

## Próximo Passo

Avançar para 0109_dados_e_persistencia.md
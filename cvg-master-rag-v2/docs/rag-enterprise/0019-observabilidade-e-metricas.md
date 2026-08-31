# 0019 — Observabilidade e Métricas

## Objetivo

Definir o sistema de observabilidade completo, com métricas, logs, alertas e dashboards — para todas as 4 fases.

---

## Princípio

> Observabilidade não é "colocar logs". É saber o que está acontecendo no sistema e poder responder perguntas sobre ele.

---

## 1. Níveis de Observabilidade por Fase

| Fase | Foco | Complexidade |
|---|---|---|
| F0 | Logs básicos + métricas de retrieval | Mínimo |
| F1 | Logs estruturados + agregação + telemetria | Básico |
| F2 | Métricas por estratégia + benchmark tracking | Médio |
| F3 | APM + tracing + dashboards + alertas | Enterprise |

---

## 2. Logs (Todas as Fases)

### Formato: JSON Lines

```json
{
  "timestamp": "2024-03-15T10:30:45.123Z",
  "level": "INFO|ERROR|WARN",
  "service": "search|ingestion|llm",
  "request_id": "uuid",
  "workspace_id": "workspace_001",
  "event": "query|upload|parse|chunk|index|search",
  "details": {...},
  "latency_ms": 145
}
```

### Eventos a Logar

| Evento | Campos | Detalhes |
|---|---|---|
| `query_received` | query, workspace_id, request_id | Query chegou |
| `retrieval_completed` | top_k, threshold, results_count, scores | Retrieval executou |
| `low_confidence` | query, best_score, threshold | Nenhum resultado acima threshold |
| `answer_generated` | chunks_used, latency_ms, confidence | Resposta criada |
| `document_uploaded` | document_id, source_type, chunk_count | Upload concluído |
| `parse_failed` | document_id, reason, error_type | Falha no parse |
| `chunking_completed` | document_id, strategy, chunk_count | Chunking concluído |

### Armazenamento de Logs

```
F0: /logs/queries.jsonl (um arquivo, rotação por 100MB)
F1: /logs/queries.jsonl + /logs/system.jsonl
F2+: Object storage (MinIO/S3) com política de retenção
```

---

## 3. Métricas de Ingestion

### A. Taxa de Parse

```python
# Métrica calculada por script diário
{
    "total_documents": 45,
    "parsed_success": 43,
    "parse_failed": 2,
    "parse_success_rate": 0.956,
    "by_source_type": {
        "pdf": {"total": 30, "success": 29, "rate": 0.967},
        "docx": {"total": 10, "success": 10, "rate": 1.0},
        "md": {"total": 5, "success": 5, "rate": 1.0}
    }
}
```

### B. Perda Estrutural

```python
{
    "total_documents": 45,
    "with_tables": 5,  # documentos que tinham tabelas
    "tables_extracted": 2,  # tabelas realmente extraídas
    "table_extraction_rate": 0.40,  # 40% das tabelas foram extraídas
    "documents_with_images": 3,
    "images_extracted": 0  # imagens não são processadas em F0
}
```

### C. Tempo de Processamento

```python
{
    "avg_processing_time_ms": 2100,
    "p50": 1500,
    "p95": 4500,
    "p99": 8000
}
```

---

## 4. Métricas de Retrieval

### A. Hit Rate

```python
{
    "total_queries": 520,
    "hit_rate_top1": 0.62,
    "hit_rate_top3": 0.74,
    "hit_rate_top5": 0.78,
    "by_difficulty": {
        "easy": {"hit_rate_top5": 0.85},
        "medium": {"hit_rate_top5": 0.72},
        "hard": {"hit_rate_top5": 0.60}
    },
    "by_category": {
        "fato": {"hit_rate_top5": 0.80},
        "procedimento": {"hit_rate_top5": 0.75},
        "política": {"hit_rate_top5": 0.70}
    }
}
```

### B. Scores

```python
{
    "avg_score_top1": 0.81,
    "avg_score_top5": 0.73,
    "p50_score": 0.78,
    "p95_score": 0.92,
    "below_threshold_rate": 0.12  # 12% das queries têm best_score < 0.70
}
```

### C. Latência

```python
{
    "avg_retrieval_latency_ms": 145,
    "p50": 120,
    "p95": 280,
    "p99": 450
}
```

---

## 5. Métricas de Resposta

### A. Groundedness

```python
{
    "total_queries": 520,
    "grounded_rate": 0.89,  # 89% das respostas têm citação
    "grounded_answers": 463,
    "citation_coverage_avg": 0.82,  # 82% do texto da resposta está citado
    "no_context_answers": 8,  # Respostas geradas sem contexto (low confidence)
    "ungrounded_answers": 49,  # Respostas com contexto, mas grounding insuficiente
    "answers_needing_review": 57,  # sem contexto ou com grounding fraco
    "avg_uncited_claims": 0.4,  # média de claims sem cobertura por resposta
}
```

### B. Qualidade de Resposta (Triagem)

```python
{
    "total_answers": 520,
    "reviewed_by_human": 45,  # 45 respostas com judge_score < 0.70
    "human_decision": {
        "valid": 38,
        "partial": 5,
        "invalid": 2
    },
    "invalid_rate": 0.044  # 4.4% das respostas revisadas são inválidas
}
```

---

## 6. Métricas Operacionais

```python
{
    "cost_per_query_avg": 0.0032,  # USD
    "cost_per_document_indexed": 0.08,  # USD
    "total_tokens_today": 125000,
    "active_workspaces": 3,
    "total_documents_indexed": 145,
    "total_chunks_indexed": 2100
}
```

---

## 7. Alertas (Fase 3)

### Condições de Alerta

| Condição | Severidade | Mensagem | Ação |
|---|---|---|---|
| Uptime < 99% | CRÍTICA | "Uptime abaixo de 99% nos últimos 60 min" | Notificar equipe |
| p99_latency > 5s | CRÍTICA | "Latência p99 acima de 5s" | Investigar |
| error_rate > 5% | CRÍTICA | "Taxa de erro acima de 5%" | Investigar + possivelmente rollback |
| hit_rate_top5 < 50% | ALTA | "Hit rate caiu para abaixo de 50%" | Investigar Retrieval |
| no_context_answers > 20% | ALTA | "Mais de 20% das respostas sem contexto" | Investigar ingestion ou indexing |
| disk_usage > 80% | MÉDIA | "Disco acima de 80%" | Limpeza de logs + scale |
| cost_daily > 2x_avg | ALTA | "Custo diário 2x acima da média" | Investigar queries anômalas |

### Configuração de Alertas

```yaml
# alerts.yaml
alerts:
  - name: low_uptime
    condition: uptime < 0.99
    window: 60min
    severity: critical
    channels: [slack, email]
    
  - name: high_latency
    condition: p99_latency_ms > 5000
    window: 5min
    severity: critical
    channels: [slack]
    
  - name: low_hit_rate
    condition: hit_rate_top5 < 0.50
    window: 30min
    severity: high
    channels: [slack]
```

---

## 8. Dashboards (Fase 3)

### Retrieval Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  RETRIEVAL QUALITY                        Last 7 days      │
├─────────────────────────────────────────────────────────────┤
│  Hit Rate Top-5    ████████████████░░░░  78%               │
│  Avg Score         ██████████████░░░░░  0.73               │
│  Low Confidence    ██░░░░░░░░░░░░░░░░  12%                │
├─────────────────────────────────────────────────────────────┤
│  Latency p99       ████████░░░░░░░░░░  280ms              │
│  Grounded Rate     ████████████████░░░  89%                │
└─────────────────────────────────────────────────────────────┘
```

### Ingestion Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  INGESTION                              Last 7 days        │
├─────────────────────────────────────────────────────────────┤
│  Documents Processed    ████████████████░░░  45             │
│  Parse Success Rate     ████████████████░░░  96%            │
│  Avg Chunks/Doc         ████████░░░░░░░░░  14.3           │
├─────────────────────────────────────────────────────────────┤
│  Processing Time p95    ███████░░░░░░░░░░  4500ms          │
│  By Type: PDF 96%, DOCX 100%, MD 100%                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Tracing (Fase 3)

### Request ID Flow

```
Request ID: req-abc123
    │
    ├─[ingestion]─► document uploaded, parsing...
    │
    ├─[chunking]─► chunking completed, 7 chunks
    │
    ├─[indexing]─► 7 chunks indexed, 7 dense + 7 sparse vectors
    │
    └─[retrieval]─► query received, hybrid search, top-5 returned
                        │
                        ├─ dense search: 145ms, 20 results
                        ├─ sparse search: 12ms, 20 results
                        └─ RRF fusion: 3ms, top-5 scored
```

### Implementação

```python
# Middleware que gera request_id e propagateia
request_id = generate_uuid()
context = {"request_id": request_id, "workspace_id": workspace_id}

# Todos os logs incluem request_id
logger.info("retrieval_completed", extra=context | {
    "latency_ms": 145,
    "results_count": 5
})
```

---

## 10. Health Check

### Endpoint: GET /health

```json
{
  "status": "healthy|degraded|unhealthy",
  "version": "0.1.0",
  "qdrant": {
    "status": "ok|error",
    "points": 21
  },
  "corpus": {
    "workspace_id": "default",
    "documents": 3,
    "chunks": 21,
    "parsed_documents": 3,
    "partial_documents": 0
  },
  "telemetry": {
    "period_days": 1,
    "queries": {
      "count": 12,
      "low_confidence": 2,
      "needs_review": 1,
      "latest_timestamp": "2026-04-16T12:00:00+00:00"
    },
    "ingestion": {
      "count": 4,
      "errors": 0,
      "latest_timestamp": "2026-04-16T11:00:00+00:00"
    },
    "evaluation": {
      "count": 1,
      "latest_timestamp": "2026-04-16T10:00:00+00:00"
    }
  },
  "timestamp": "2026-04-16T12:34:56Z"
}
```

### Status Definitions

| Status | Significado |
|---|---|
| `healthy` | Tudo funcionando, latência normal |
| `degraded` | Funcionando, mas com degradação (ex: latência alta) |
| `unhealthy` | Problema crítico, algumas funcionalidades indisponíveis |

---

## Próximo Passo

Ir para `0020-master-execution-log.md` — execution log mestre.

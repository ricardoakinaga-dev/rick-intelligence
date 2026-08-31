# 0113 — Observabilidade, Runtime e Operação

## Logs Necessários

### Formato
```python
{
    "timestamp": "ISO8601",
    "level": "INFO|WARN|ERROR",
    "request_id": "uuid",
    "workspace_id": "uuid",
    "event": "string",
    "details": {...},
    "latency_ms": int | None
}
```

### Eventos a Logar

| Evento | Campos | Detalhes |
|---|---|---|
| query_received | query, workspace_id, request_id | Query chegou |
| retrieval_completed | top_k, results_count, scores | Retrieval executou |
| low_confidence | query, best_score, threshold | Nenhum resultado acima threshold |
| answer_generated | chunks_used, latency_ms, confidence | Resposta criada |
| document_uploaded | document_id, source_type, chunk_count | Upload concluído |
| parse_failed | document_id, reason, error_type | Falha no parse |
| chunking_completed | document_id, strategy, chunk_count | Chunking concluído |
| admin_action | user_id, action, target, result | Ação administrativa |
| auth_login | user_id, result | Login attempt |
| auth_logout | user_id | Logout |

---

## Métricas Mínimas

### Retrieval Metrics
```python
{
    "total_queries": int,
    "hit_rate_top1": float,
    "hit_rate_top3": float,
    "hit_rate_top5": float,
    "avg_score": float,
    "low_confidence_rate": float,
    "avg_retrieval_latency_ms": int
}
```

### Answer Metrics
```python
{
    "total_answers": int,
    "grounded_rate": float,
    "citation_coverage_avg": float,
    "avg_answer_latency_ms": int,
    "answers_needing_review": int
}
```

### Ingestion Metrics
```python
{
    "total_documents": int,
    "parse_success_rate": float,
    "avg_chunks_per_doc": float,
    "avg_processing_time_ms": int
}
```

---

## Tracing / Correlation

### request_id
- Gerado no entry point (middleware)
- Propagado para todos os logs
- Retornado no response header X-Request-ID

### Contexto de Workspace
- workspace_id extraído da sessão
- Adicionado a todos os logs
- Garantia de isolamento em traces

---

## Health Checks

### GET /health

**Response 200:**
```python
{
    "status": "healthy",  # healthy | degraded | unhealthy
    "version": "0.1.0",
    "qdrant": {
        "status": "ok",  # ok | error
        "points": int
    },
    "corpus": {
        "workspace_id": "default",
        "documents": int,
        "chunks": int
    },
    "telemetry": {
        "period_days": int,
        "queries": {...},
        "ingestion": {...}
    },
    "timestamp": "ISO8601"
}
```

### Status Definitions
- **healthy:** Tudo funcionando, latência normal
- **degraded:** Funcionando, mas com lentidão ou.Qdrant com problemas
- **unhealthy:** Problema crítico, funcionalidade comprometida

---

## SLI/SLO (Futuro / F3)

### SLI (Service Level Indicator)
- **Availability:** % requests returning 200 in window
- **Latency:** p99 latency <= 3s
- **Error Rate:** % requests returning 5xx

### SLO (Service Level Objective)
- **Availability:** >= 99%
- **Latency:** p99 < 3s
- **Error Rate:** < 2%

---

## Alertas (F3)

### Condições
| Condição | Severidade | Ação |
|---|---|---|
| Uptime < 99% | CRITICAL | Notificar |
| p99_latency > 5s | CRITICAL | Investigar |
| error_rate > 5% | CRITICAL | Investigar |
| hit_rate_top5 < 50% | HIGH | Investigar retrieval |
| no_context_answers > 20% | HIGH | Investigar ingestion |

---

## Operação Assistida

### Modo Degradado
- Se Qdrant offline: health = degraded, queries retornam erro 500
- Se OpenAI offline: health = healthy (mas queries sem LLM)

### Debug Mode
- Logs detalhados em development
- Reduced logging em production

---

## Próximo Passo

Avançar para 0114_superficie_operacional_e_frontend.md
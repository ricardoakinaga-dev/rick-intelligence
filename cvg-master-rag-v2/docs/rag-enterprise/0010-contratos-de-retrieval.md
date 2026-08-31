# 0010 — Contratos de Retrieval

## Objetivo

Definir os contratos de interface para o serviço de busca (search) e retrieval, garantindo que a comunicação entre componentes seja clara e testável.

---

## Contrato 1: Search Input

### Endpoint: `POST /search`

#### Request

```json
{
  "query": "Qual o prazo para reembolso?",
  "workspace_id": "workspace_001",
  "top_k": 5,
  "threshold": 0.70,
  "filters": {
    "document_id": "optional-uuid",
    "source_type": "pdf|docx|md|txt",
    "page_hint_min": 1,
    "page_hint_max": 50,
    "tags": ["tag1", "tag2"]
  },
  "retrieval_mode": "híbrida",
  "include_raw_scores": false
}
```

#### Field Definitions

| Campo | Tipo | Obrigatório | Default | Descrição |
|---|---|---|---|---|
| `query` | string | ✅ | - | Query do usuário |
| `workspace_id` | string | ✅ | - | Workspace para buscar |
| `top_k` | int | ❌ | 5 | Número de resultados |
| `threshold` | float | ❌ | 0.70 | Score mínimo (0.0-1.0) |
| `filters` | object | ❌ | null | Filtros opcionais |
| `retrieval_mode` | string | ❌ | "híbrida" | "standard" \| "híbrida" |
| `include_raw_scores` | bool | ❌ | false | Include dense/sparse scores |

---

## Contrato 2: Search Result Item

#### Response Item

```json
{
  "chunk_id": "chunk_550e8400-e29b-41d4-a716-446655440000_042",
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "text": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase. Após esse período...",
  "score": 0.84,
  "page_hint": 12,
  "source": "dense+sparse_rrf",
  "document_filename": "relatorio_fiscal_2024.pdf",
  "workspace_id": "workspace_001"
}
```

#### Source Types

| Value | Significado |
|---|---|
| `dense_only` | Busca semântica pura |
| `sparse_only` | Busca BM25 pura |
| `dense+sparse_rrf` | Fusão RRF de ambos |
| `reranked` | Após Cohere rerank |
| `hyde_fallback` | Usou documento hipotético |

---

## Contrato 3: Search Output

#### Response 200

```json
{
  "query": "Qual o prazo para reembolso?",
  "workspace_id": "workspace_001",
  "results": [
    {
      "chunk_id": "chunk_xxx_042",
      "document_id": "doc_xxx",
      "text": "O prazo para solicitação de reembolso é de 30 dias corridos...",
      "score": 0.84,
      "page_hint": 12,
      "source": "dense+sparse_rrf"
    },
    {
      "chunk_id": "chunk_xxx_017",
      "document_id": "doc_xxx",
      "text": "Para solicitar o reembolso, o cliente deve...",
      "score": 0.78,
      "page_hint": 11,
      "source": "dense+sparse_rrf"
    }
  ],
  "total_candidates": 20,
  "low_confidence": false,
  "retrieval_time_ms": 145,
  "method": "híbrida"
}
```

#### Response 200 com scores detalhados (if include_raw_scores=true)

```json
{
  "query": "...",
  "results": [...],
  "scores_breakdown": {
    "dense_max": 0.82,
    "sparse_max": 0.75,
    "rrf_final_score": 0.84
  },
  "retrieval_time_ms": 145,
  "method": "híbrida"
}
```

#### Response 200 (low confidence)

```json
{
  "query": "Qual o prazo para reembolso?",
  "workspace_id": "workspace_001",
  "results": [],
  "total_candidates": 0,
  "low_confidence": true,
  "retrieval_time_ms": 89,
  "warning": "Nenhum resultado acima do threshold 0.70"
}
```

---

## Contrato 4: Rerank Input/Output

### Rerank Request (Internal)

```json
{
  "query": "Qual o prazo para reembolso?",
  "documents": [
    {"id": "chunk_001", "text": "Texto do chunk 1..."},
    {"id": "chunk_002", "text": "Texto do chunk 2..."},
    ...
  ],
  "top_n": 5
}
```

### Rerank Response (Internal)

```json
{
  "reranked": [
    {"index": 0, "relevance_score": 0.92, "id": "chunk_003"},
    {"index": 1, "relevance_score": 0.87, "id": "chunk_001"},
    {"index": 2, "relevance_score": 0.81, "id": "chunk_007"},
    {"index": 3, "relevance_score": 0.76, "id": "chunk_012"},
    {"index": 4, "relevance_score": 0.71, "id": "chunk_005"}
  ],
  "rerank_time_ms": 45
}
```

---

## Contrato 5: Citations Payload

### Internal (usado na geração de resposta)

```json
{
  "answer": "O prazo para reembolso é de 30 dias corridos conforme item 3.2.",
  "chunks_used": ["chunk_xxx_042", "chunk_xxx_017"],
  "citations": [
    {
      "chunk_id": "chunk_xxx_042",
      "document_id": "550e8400-e29b-41d4-a716-446655440000",
      "document_filename": "relatorio_fiscal_2024.pdf",
      "page": 12,
      "text": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase. Após esse período...",
      "score": 0.84
    }
  ],
  "grounded": true,
  "citation_coverage": 1.0
}
```

---

## Contrato 6: HyDE Input/Output

### HyDE Request (Internal)

```json
{
  "query": "Qual o código de erro 504 no SAP?",
  "original_results": [...],
  "hyde_threshold": 0.85
}
```

### HyDE Response (Internal)

```json
{
  "triggered": true,
  "hypothetical_doc": {
    "text": "O erro 504 Gateway Timeout no SAP indica que o servidor não recebeu resposta do sistema upstream dentro do tempo limite. Solução: verificar conectividade e aumentar timeout."
  },
  "hyde_results": [...],
  "comparison": {
    "original_best_score": 0.72,
    "hyde_best_score": 0.89,
    "winner": "hyde"
  },
  "hyde_used": true
}
```

---

## Contrato 7: Query + Answer (完整 pipeline)

### Endpoint: `POST /query`

#### Request

```json
{
  "query": "Qual o prazo para reembolso?",
  "workspace_id": "workspace_001",
  "top_k": 5,
  "threshold": 0.70,
  "stream": false,
  "model": "gpt-4o-mini"
}
```

#### Response 200

```json
{
  "answer": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase, conformeitem 3.2 do regulamento.",
  "chunks_used": ["chunk_xxx_042", "chunk_xxx_017"],
  "citations": [
    {
      "chunk_id": "chunk_xxx_042",
      "document_filename": "relatorio_fiscal_2024.pdf",
      "page": 12,
      "score": 0.84
    }
  ],
  "confidence": "high",
  "grounded": true,
  "low_confidence": false,
  "retrieval": {
    "method": "híbrida",
    "scores_breakdown": {"dense_max": 0.82, "sparse_max": 0.75, "rrf": 0.84},
    "retrieval_time_ms": 145
  },
  "latency_ms": 1890
}
```

#### Response 200 (low confidence)

```json
{
  "answer": "Não tenho informações suficientes no contexto para responder准确地 a esta pergunta.",
  "confidence": "low",
  "grounded": true,
  "low_confidence": true,
  "chunks_used": [],
  "citations": [],
  "retrieval": {
    "method": "híbrida",
    "low_confidence": true,
    "warning": "Nenhum resultado acima do threshold 0.70"
  },
  "latency_ms": 340
}
```

---

## Errors

| Code | HTTP | Description |
|---|---|---|
| `WORKSPACE_NOT_FOUND` | 404 | Workspace ID does not exist |
| `INVALID_QUERY` | 400 | Query is empty or too long |
| `RETRIEVAL_ERROR` | 500 | Vector DB error |
| `LLM_ERROR` | 500 | LLM API error |

---

## Próximo Passo

Ir para `0011-contratos-de-avaliacao.md` — contratos de avaliação.
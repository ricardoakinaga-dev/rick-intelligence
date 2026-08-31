# 0011 — Contratos de Avaliação

## Objetivo

Definir os contratos para avaliação de retrieval e qualidade de resposta, garantindo que medição seja objetiva, reproduzível e auditável.

---

## Princípio Importante

> **LLM Judge é ferramenta de triagem, não veredicto final.**
> Revisão humana é obrigatória para decisões de gate.

---

## Contrato 1: Question Set (Dataset de Avaliação)

### Schema

```json
{
  "dataset_id": "phase0_validation",
  "version": 1,
  "created_at": "2024-03-15T10:00:00Z",
  "created_by": "human|llm_synthetic",
  "source": "description of where questions came from",
  "questions": [
    {
      "id": 1,
      "pergunta": "Qual o prazo para reembolso?",
      "document_id": "doc_001",
      "document_filename": "politicas.docx",
      "trecho_esperado": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase.",
      "resposta_esperada": "30 dias corridos após a purchase",
      "dificuldade": "easy|medium|hard",
      "categoria": "fato|procedimento|política|detalhes",
      "terms": ["reembolso", "prazo", "30 dias"],
      "notes": "Informação explícita no documento"
    }
  ]
}
```

### Regras de Dataset

- Mínimo de 20 perguntas para validação de fase
- Pelo menos 30% devem ser "medium" ou "hard"
- Documento fonte deve existir e estar indexado
- Trecho esperado deve estar acessível no documento

---

## Contrato 2: Retrieval Hit

### Definição: Hit

```
Hit = documento correto está no top-k de resultados
```

### Schema de Resultado de Retrieval

```json
{
  "question_id": 1,
  "query": "Qual o prazo para reembolso?",
  "retrieval_mode": "híbrida",
  "results": [
    {"chunk_id": "chunk_xxx", "document_id": "doc_001", "score": 0.84},
    {"chunk_id": "chunk_yyy", "document_id": "doc_002", "score": 0.78}
  ],
  "hit_top1": true,
  "hit_top3": true,
  "hit_top5": true,
  "correct_document_id": "doc_001",
  "best_score": 0.84,
  "best_score_rank": 1
}
```

---

## Contrato 3: Grounded Answer

### Schema

```json
{
  "question_id": 1,
  "query": "Qual o prazo para reembolso?",
  "answer": "O prazo é de 30 dias corridos após a purchase.",
  "chunks_used": ["chunk_xxx_042", "chunk_xxx_017"],
  "citations": [
    {
      "chunk_id": "chunk_xxx_042",
      "text": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase.",
      "document_id": "doc_001"
    }
  ],
  "grounded": true,
  "citation_coverage": 1.0,
  "uncited_claims": []
}
```

### Campo `grounded`

- `true`: Todos os claims da resposta têm citação
- `false`: Pelo menos um claim sem citação

### Campo `citation_coverage`

```
coverage = (chars cited) / (chars total da resposta)
```

---

## Contrato 4: Judge Result

### Schema (triagem)

```json
{
  "question_id": 1,
  "answer_id": "answer_xxx",
  "judge_model": "gpt-4o-mini",
  "judge_prompt_version": "v1",
  "groundedness": "yes|partial|no",
  "relevance": "high|medium|low",
  "hallucination": "none|minor|major",
  "overall_score": 0.85,
  "justification": "A resposta está fundamentada no contexto recuperado. O prazo de 30 dias está corretamente identificado.",
  "needs_human_review": false
}
```

### Regra de Triagem

```
needs_human_review = true IF:
  - overall_score < 0.70
  - hallucination == "major"
  - groundedness == "no"
  - relevance == "low"
```

---

## Contrato 5: Human Review Result

### Schema

```json
{
  "answer_id": "answer_xxx",
  "reviewer_id": "human_reviewer_001",
  "decision": "valid|partial|invalid",
  "groundedness_verified": true,
  "relevance_verified": "high",
  "issues_found": [],
  "notes": "Resposta correta, citação cover todo o claim.",
  "reviewed_at": "2024-03-15T14:30:00Z"
}
```

### Decisões

| Decision | Significado |
|---|---|
| `valid` | Resposta está correta e bem fundamentada |
| `partial` | Resposta está parcialmente correta; melhorias necessárias |
| `invalid` | Resposta está errada ou sem fundamento |

---

## Contrato 6: Evaluation Report (Agregado)

### Per Document

```json
{
  "document_id": "doc_001",
  "document_filename": "politicas.docx",
  "questions_tested": 5,
  "hit_rate_top5": 0.80,
  "avg_score": 0.76,
  "groundedness_rate": 0.90,
  "evaluation_date": "2024-03-15",
  "failures": [
    {
      "question_id": 3,
      "reason": "chunk não recuperado no top-5",
      "suggested_fix": "Aumentar top_k ou baixar threshold"
    }
  ]
}
```

### Global (todo o dataset)

```json
{
  "evaluation_id": "eval_2024_03_15_001",
  "dataset_id": "phase0_validation",
  "date": "2024-03-15T10:00:00Z",
  "total_questions": 30,
  "hit_rate_top1": 0.62,
  "hit_rate_top3": 0.73,
  "hit_rate_top5": 0.78,
  "avg_score": 0.74,
  "groundedness_rate": 0.89,
  "low_confidence_rate": 0.12,
  "by_difficulty": {
    "easy": {"hit_rate_top5": 0.85, "count": 15},
    "medium": {"hit_rate_top5": 0.72, "count": 10},
    "hard": {"hit_rate_top5": 0.60, "count": 5}
  },
  "by_category": {
    "fato": {"hit_rate_top5": 0.80, "count": 12},
    "procedimento": {"hit_rate_top5": 0.75, "count": 10},
    "política": {"hit_rate_top5": 0.70, "count": 5},
    "detalhes": {"hit_rate_top5": 0.66, "count": 3}
  }
}
```

---

## Contrato 7: Benchmark Result

### Schema

```json
{
  "benchmark_id": "run_001",
  "date": "2024-03-15T10:00:00Z",
  "questions_tested": 5,
  "documents_tested": 8,
  "strategies_tested": ["recursive", "semantic", "page", "agentic"],
  "retrieval_modes_tested": ["standard", "híbrida"],
  "results": [
    {
      "strategy": "recursive",
      "retrieval_mode": "híbrida",
      "hit_rate_top1": 0.60,
      "hit_rate_top3": 0.72,
      "hit_rate_top5": 0.78,
      "avg_score": 0.74,
      "avg_latency_ms": 145
    },
    {
      "strategy": "semantic",
      "retrieval_mode": "híbrida",
      "hit_rate_top1": 0.64,
      "hit_rate_top3": 0.76,
      "hit_rate_top5": 0.84,
      "avg_score": 0.79,
      "avg_latency_ms": 189
    }
  ],
  "winner": {
    "strategy": "semantic",
    "retrieval_mode": "híbrida",
    "hit_rate_top5": 0.84,
    "vs_baseline_gain": 0.06
  },
  "notes": "Semantic venceu em documentos longos (>20k chars). Recursive suficiente para docs curtos."
}
```

---

## Errors de Avaliação

| Code | Description |
|---|---|
| `DOCUMENT_NOT_INDEXED` | Documento do dataset não está no vector DB |
| `MISSING_GOLD_ANSWER` | Trecho esperado não foi fornecido |
| `JUDGE_TIMEOUT` | LLM Judge não respondeu a tempo |
| `INVALID_ANSWER_FORMAT` | Resposta não está no formato esperado |

---

## Próximo Passo

Ir para `0012-modelo-de-dados-e-metadados.md` — modelo de dados.
# 0012 — Modelo de Dados e Metadados

## Objetivo

Definir o modelo de dados completo para todas as entidades do sistema RAG, com ênfase em prepará-lo para multitenancy futuro sem complicar a implementação atual.

---

## Entidades Principais

```
Workspace (tenant)
    └── Document
            └── Chunk
                    └── Vector (dense + sparse)

Conversation (log de queries)
Query (individuais)
EvaluationResult
BenchmarkRun
```

---

## Workspace

```sql
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    settings JSONB DEFAULT '{}'  -- future: configs, branding
);
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID | ✅ | PK |
| `name` | TEXT | ✅ | Nome do workspace/empresa |
| `created_at` | TIMESTAMPTZ | ✅ | Data de criação |
| `is_active` | BOOLEAN | ✅ | Soft delete |
| `settings` | JSONB | ❌ | Configurações futuras |

---

## Document

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    source_type TEXT NOT NULL,  -- pdf, docx, md, txt
    filename TEXT NOT NULL,
    file_path TEXT,  -- path no storage
    page_count INTEGER,
    char_count INTEGER,
    status TEXT NOT NULL,  -- parsed, failed, partial
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    indexed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    chunking_strategy TEXT,  -- recursive, semantic, page, agentic
    embedding_model TEXT  -- text-embedding-3-small
);
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID | ✅ | PK |
| `workspace_id` | UUID | ✅ | FK → workspaces |
| `source_type` | TEXT | ✅ | pdf, docx, md, txt |
| `filename` | TEXT | ✅ | Nome original |
| `file_path` | TEXT | ❌ | Path no storage |
| `page_count` | INTEGER | ❌ | Para PDFs |
| `char_count` | INTEGER | ❌ | Tamanho do texto |
| `status` | TEXT | ✅ | parsed, failed, partial |
| `tags` | TEXT[] | ❌ | Tags para filtro |
| `chunking_strategy` | TEXT | ❌ | Estratégia usada |
| `metadata` | JSONB | ❌ | Extra |

---

## Chunk

```sql
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,  -- format: chunk_{doc_id}_{index}
    document_id UUID NOT NULL REFERENCES documents(id),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    page_hint INTEGER,
    strategy TEXT NOT NULL,  -- recursive, semantic, page, agentic
    chunk_size_chars INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | TEXT | ✅ | chunk_{doc_id}_{index} |
| `document_id` | UUID | ✅ | FK → documents |
| `workspace_id` | UUID | ✅ | FK → workspaces |
| `chunk_index` | INTEGER | ✅ | Posição no documento |
| `text` | TEXT | ✅ | Texto do chunk |
| `start_char` | INTEGER | ❌ | Início no documento original |
| `end_char` | INTEGER | ❌ | Fim no documento original |
| `page_hint` | INTEGER | ❌ | Página de origem (PDF) |
| `strategy` | TEXT | ✅ | Como foi chunkado |

### Indexes

```sql
CREATE INDEX idx_chunks_document ON chunks(document_id);
CREATE INDEX idx_chunks_workspace ON chunks(workspace_id);
CREATE INDEX idx_chunks_text ON chunks USING gin(to_tsvector('portuguese', text));
```

---

## Query Log (Conversation)

```sql
CREATE TABLE conversation_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    query_text TEXT NOT NULL,
    answer_text TEXT,
    confidence TEXT,  -- high, medium, low
    grounded BOOLEAN,
    chunks_used TEXT[],  -- array of chunk_ids
    retrieval_method TEXT,
    retrieval_scores JSONB,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `workspace_id` | UUID | ✅ | FK → workspaces |
| `query_text` | TEXT | ✅ | Pergunta do usuário |
| `answer_text` | TEXT | ❌ | Resposta do agente |
| `confidence` | TEXT | ❌ | high/medium/low |
| `grounded` | BOOLEAN | ❌ | Resposta com citação |
| `chunks_used` | TEXT[] | ❌ | Chunk IDs usados |
| `retrieval_scores` | JSONB | ❌ | Scores dos chunks |

---

## Evaluation Results

```sql
CREATE TABLE evaluation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    dataset_id TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    hit_top1 BOOLEAN,
    hit_top5 BOOLEAN,
    best_score FLOAT,
    grounded BOOLEAN,
    judge_score FLOAT,
    judge_needs_review BOOLEAN,
    human_decision TEXT,  -- valid, partial, invalid
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Benchmark Runs

```sql
CREATE TABLE benchmark_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id),
    benchmark_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    retrieval_mode TEXT NOT NULL,
    hit_rate_top5 FLOAT,
    avg_score FLOAT,
    avg_latency_ms INTEGER,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Preparação para Multitenancy

### Princípio: workspace_id em TODA tabela

Toda tabela que armazena dados de tenant TEM `workspace_id` como campo obrigatório. Isso garante:
- Isolamento real de dados
- Queries nunca vazam entre tenants
- Limpeza de um tenant não afeta outro

### Queries devem SEMPRE filtrar por workspace_id

```python
# ✅ CORRETO
def get_document(doc_id, workspace_id):
    return db.query(Document).filter(
        Document.id == doc_id,
        Document.workspace_id == workspace_id
    ).first()

# ❌ ERRADO (não filtrar por workspace)
def get_document_unsafe(doc_id):
    return db.query(Document).filter(Document.id == doc_id).first()
```

---

## Qdrant Collections

### Fase 0: Single Collection

```
Collection: rag_phase0
    - workspace_id no payload (filtro)
    - document_id no payload
    - chunk_id no payload
    - text no payload (truncado 2000 chars)
    - page_hint no payload
```

### Fase 3+: Collection por Workspace (se necessário)

```
Collection: rag_ws_{workspace_id}
    - Cada workspace tem sua collection
    - Isolamento no nível de collection
    - Mais seguro, mais custoso
```

---

## JSONs de Documentos (Storage)

```
src/data/documents/
  /{workspace_id}/
    {document_id}_raw.json    # Documento normalizado
    {document_id}_chunks.json  # Chunks extraídos (cache)
```

Notas operacionais:

- o arquivo original é apenas transitório durante ingestão
- o corpus ativo vive em `src/data/documents/{workspace_id}/`
- `src/data/{workspace_id}/dataset.json` permanece como dataset operacional

---

## Próximo Passo

Ir para `0013-quality-gates.md` — quality gates.

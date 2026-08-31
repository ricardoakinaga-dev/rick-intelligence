# 0009 — Contratos de Ingestão

## Objetivo

Definir os contratos (schemas, inputs, outputs, erros) para o pipeline de ingestão de documentos, garantindo interface clara e validável entre cada estágio.

---

## Pipeline de Ingestão

```
Upload → Validação → Parsing → Normalização → Chunking → Indexação
```

---

## Contrato 1: Upload

### Endpoint: `POST /documents/upload`

#### Request

```
Content-Type: multipart/form-data

file: bytes (required)
workspace_id: string (optional, default: "default")
```

#### Supported Formats

```json
{
  "supported": ["pdf", "docx", "md", "txt"],
  "max_size_mb": 50,
  "reject": ["xlsx", "csv", "ppt", "html", "png", "jpg"]
}
```

#### Response 201 (Success)

```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "parsed",
  "source_type": "pdf",
  "filename": "relatorio_fiscal_2024.pdf",
  "page_count": 47,
  "char_count": 89400,
  "chunk_count": 89,
  "created_at": "2024-03-15T10:30:00Z"
}
```

#### Response 400 (Validation Error)

```json
{
  "error": "unsupported_format",
  "message": "Formato 'xlsx' não é aceito nesta fase. Formatos aceitos: pdf, docx, md, txt",
  "received": "xlsx",
  "supported": ["pdf", "docx", "md", "txt"]
}
```

```json
{
  "error": "file_too_large",
  "message": "Arquivo excede limite de 50MB",
  "received_mb": 67.3,
  "max_mb": 50
}
```

#### Response 413 (Parse Failed)

```json
{
  "error": "parse_failed",
  "message": "Não foi possível extrair texto do documento. Pode estar corrompido ou ser imagem.",
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "reason": "no_text_extracted"
}
```

---

## Contrato 2: Document Metadata

### GET /documents/{document_id}

#### Response 200

```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_id": "workspace_001",
  "source_type": "pdf",
  "filename": "relatorio_fiscal_2024.pdf",
  "page_count": 47,
  "char_count": 89400,
  "chunk_count": 89,
  "status": "parsed|failed|partial",
  "created_at": "2024-03-15T10:30:00Z",
  "tags": ["fiscal", "2024"],
  "embeddings_model": "text-embedding-3-small",
  "chunking_strategy": "recursive",
  "indexed_at": "2024-03-15T10:31:00Z"
}
```

#### Response 404

```json
{
  "error": "document_not_found",
  "document_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Contrato 3: Normalized Document JSON

### Internal Schema (output do parsing)

```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_type": "pdf",
  "filename": "relatorio_fiscal_2024.pdf",
  "workspace_id": "workspace_001",
  "created_at": "2024-03-15T10:30:00Z",
  "pages": [
    {
      "page_number": 1,
      "text": "Este é o conteúdo da página 1 do documento..."
    },
    {
      "page_number": 2,
      "text": "Este é o conteúdo da página 2..."
    }
  ],
  "sections": [
    {
      "title": "1. Introdução",
      "level": 1,
      "page": 1,
      "text": "Conteúdo da introdução..."
    }
  ],
  "metadata": {
    "author": "unknown",
    "creation_date": "unknown",
    "total_pages": 47
  },
  "raw_json_path": "src/data/documents/workspace_001/550e8400-e29b-41d4-a716-446655440000_raw.json"
}
```

---

## Contrato 4: Normalized Section

```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "section_id": "section_001",
  "title": "3.2 Política de Reembolso",
  "level": 2,
  "page_start": 12,
  "page_end": 13,
  "text": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase...",
  "char_count": 4520,
  "parent_section_id": "section_000"
}
```

---

## Contrato 5: Normalized Table Block

**Nota:** Tabelas são ADIADAS para Fase 1+. Este contrato é placeholder para futura implementação.

```json
{
  "document_id": "uuid",
  "table_id": "table_001",
  "section_id": "section_005",
  "page": 8,
  "headers": ["Produto", "Preço", "Quantidade"],
  "rows": [
    ["Item A", "R$ 100,00", "10"],
    ["Item B", "R$ 250,00", "5"]
  ],
  "caption": "Tabela 1: Lista de produtos",
  "notes": "Valores em reais brasileiros"
}
```

---

## Contrato 6: Chunk Schema

### Output do chunking

```json
{
  "chunk_id": "chunk_550e8400-e29b-41d4-a716-446655440000_001",
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_id": "workspace_001",
  "chunk_index": 1,
  "text": "O prazo para solicitação de reembolso é de 30 dias corridos após a purchase. Após esse período, requests não serão aceita...",
  "start_char": 4520,
  "end_char": 5519,
  "page_hint": 12,
  "strategy": "recursive",
  "chunk_size_chars": 999,
  "overlap_chars": 200,
  "created_at": "2024-03-15T10:30:30Z"
}
```

### Regras de validação do chunk

- `text` must be non-empty
- `chunk_size_chars` must be <= 1200 (com overlap incluso)
- `chunk_index` must be >= 0 e único dentro do documento
- `start_char` must be < `end_char`
- `overlap` deve respeitar limite configurado

---

## Contrato 7: Metadata Padrão

### Campos obrigatórios em todo documento

```json
{
  "document_id": "uuid (generated)",
  "workspace_id": "string (from request or default)",
  "source_type": "pdf|docx|md|txt",
  "filename": "string (original filename)",
  "created_at": "ISO8601 (server timestamp)",
  "status": "parsed|failed|partial",
  "char_count": "number",
  "page_count": "number|null (null for non-paginated)",
  "chunk_count": "number"
}
```

### Campos optional

```json
{
  "tags": ["array", "of", "strings"],
  "owner_id": "string",
  "parent_document_id": "uuid|null (for versions)",
  "version": "number (default 1)"
}
```

---

## Errors Handling

### Error Codes

| Code | Name | HTTP | Description |
|---|---|---|---|
| `UNSUPPORTED_FORMAT` | Unsupported Format | 400 | File type not in supported list |
| `FILE_TOO_LARGE` | File Too Large | 400 | File exceeds max_size_mb |
| `PARSE_FAILED` | Parse Failed | 413 | Could not extract text |
| `INVALID_FILE` | Invalid File | 400 | File appears corrupted |
| `DOCUMENT_NOT_FOUND` | Not Found | 404 | Document ID does not exist |
| `WORKSPACE_NOT_FOUND` | Not Found | 404 | Workspace ID does not exist |
| `STORAGE_ERROR` | Storage Error | 500 | Could not save to storage |
| `INDEXING_ERROR` | Indexing Error | 500 | Could not index in vector DB |

### Error Response Schema

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable description",
  "details": {
    "key": "value"
  },
  "request_id": "uuid (for debugging)"
}
```

---

## Próximo Passo

Ir para `0010-contratos-de-retrieval.md` — contratos de retrieval.

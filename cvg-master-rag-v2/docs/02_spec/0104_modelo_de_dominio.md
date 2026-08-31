# 0104 — Modelo de Domínio

## Entidades Principais

### Entity 1: Document

```python
class Document:
    id: UUID
    workspace_id: UUID
    source_type: Literal["pdf", "docx", "md", "txt"]
    filename: str
    file_path: str | None
    page_count: int | None
    char_count: int | None
    status: Literal["parsed", "failed", "partial"]
    tags: list[str]
    created_at: datetime
    indexed_at: datetime | None
    chunking_strategy: str
    embedding_model: str
```

**Invariantes:**
- status != "parsed" implies indexed_at == None
- source_type in ["pdf", "docx", "md", "txt"]

---

### Entity 2: Chunk

```python
class Chunk:
    id: str  # format: chunk_{document_id}_{index}
    document_id: UUID
    workspace_id: UUID
    chunk_index: int
    text: str
    start_char: int | None
    end_char: int | None
    page_hint: int | None
    strategy: str  # "recursive"
    created_at: datetime
```

**Invariantes:**
- chunk_index >= 0
- start_char < end_char if both present

---

### Entity 3: User

```python
class User:
    id: UUID
    email: str
    password_hash: str
    role: Literal["admin", "operator", "viewer"]
    is_active: bool
    created_at: datetime
```

**Invariantes:**
- email is unique
- role in ["admin", "operator", "viewer"]

---

### Entity 4: Tenant

```python
class Tenant:
    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    settings: dict  # JSON
```

**Invariantes:**
- name is unique
- settings valid JSON

---

### Entity 5: Workspace

```python
class Workspace:
    id: UUID
    tenant_id: UUID
    name: str
    is_active: bool
    created_at: datetime
```

**Invariantes:**
- tenant_id references existing Tenant

---

### Entity 6: Session

```python
class Session:
    id: str  # token/session_id
    user_id: UUID
    workspace_id: UUID
    created_at: datetime
    expires_at: datetime
    is_valid: bool
```

**Invariantes:**
- expires_at > created_at
- is_valid == True implies not expired

---

## Value Objects

### VO 1: SearchResult

```python
class SearchResult:
    chunk_id: str
    document_id: UUID
    text: str
    score: float
    page_hint: int | None
    source: Literal["dense", "sparse", "rrf"]
```

---

### VO 2: GroundingReport

```python
class GroundingReport:
    grounded: bool
    citation_coverage: float
    chunks_used: list[str]
    uncited_claims: list[str]
    reason: str
    needs_review: bool
```

---

### VO 3: QueryLog

```python
class QueryLog:
    request_id: str
    timestamp: datetime
    workspace_id: UUID
    user_id: UUID | None
    query: str
    low_confidence: bool
    chunks_used: list[str]
    latency_ms: int
```

---

## Agregados

### Agregado 1: Document Aggregate

```
Document (root)
  └── Chunks (value objects collection)
```

- Document é o agregado raiz
- Chunks existem apenas como parte de Document
- Quando Document é deletado, chunks são removidos

---

### Agregado 2: Tenant/User Aggregate

```
Tenant (root)
  └── Workspaces (collection)
      └── Users (per workspace)
```

- Tenant é o agregado raiz
- Users pertencem a Workspaces do Tenant
- RBAC é por Tenant

---

## Regras de Consistência

### Regra 1: Workspace sempre pertence a Tenant
- Não existe Workspace sem Tenant
- Queries sempre filtram por workspace E tenant

### Regra 2: Documentos sempre pertencem a Workspace
- Chunk.document_id references Document
- Document.workspace_id references Workspace
- Retrieval sempre filtra por workspace

### Regra 3: Session válida implica User ativa
- Session só é criada para User.is_active == True
- Session.is_valid == False se User.is_active == False

---

## Próximo Passo

Avançar para 0105_maquina_de_estados_e_fluxos.md
# Canonical RAG contract v1

Status: implemented in the preserved CVG/Professor adapters; provider quality and
legacy data migration are not claimed. The canonical logical collection is
`rag_phase0`. The aliases `cvg_master_rag` and `rickvet_documents` normalize to
that identifier and do not cause an implicit multi-collection search.

## Vector and identity contract

| Field | Canonical value |
| --- | --- |
| schema version | `rag-contract-v1` |
| collection | `rag_phase0` |
| dense vector | named `dense`, 1536 dimensions, cosine |
| sparse vector | named `sparse`, Qdrant sparse vector for BM25-compatible lexical retrieval |
| embedding model | `text-embedding-3-small` |
| document identity | UUIDv5 of workspace + normalized collection + SHA-256 content checksum |
| point identity | UUIDv5 of canonical `chunk_id` |
| version | `sha256:<first 16 checksum characters>` |

Unchanged content in the same workspace and logical collection converges on the
same document/chunk/point identities. Changed content produces a new document
version. Qdrant upsert therefore makes identical reingestion idempotent without
deleting unrelated workspace data.

## Required point payload

Every indexed point carries the following fields. Nullable values remain present
when a parser has no page or section value.

| Field | Meaning | Required |
| --- | --- | --- |
| `schema_version` | contract discriminator | yes |
| `workspace_id` | tenant/workspace ownership boundary | yes |
| `collection_id` | normalized logical collection ACL key | yes |
| `document_id` / `document_version` | stable document identity and content version | yes |
| `chunk_id` / `parent_chunk_id` / `chunk_index` | chunk identity and hierarchy | yes |
| `text` | bounded retrievable chunk text | yes |
| `source` / `title` | citation source labels | yes |
| `page_start` / `page_end` / `section` | source location | yes; nullable location values allowed |
| `checksum` | SHA-256 source/content checksum | yes |
| `parser_version` / `chunker_version` | producer versions | yes |
| `embedding_model` / `embedding_version` | embedding provenance | yes |
| `metadata` | controlled extension object | yes |

Compatibility fields (`document_filename`, `source_type`, `catalog_scope`,
`qdrant_collection`, tags, publisher metadata and `ingestion_id`) remain in the
payload for current clients, but do not replace the canonical fields.

## Retrieval contract

The API creates a `RetrievalContext` after authentication:

```text
user_id
workspace_id
allowed_collection_ids
permissions
```

The server verifies that the requested workspace matches the active session and
that a requested collection is in the user's grant. The vector adapter adds a
Qdrant `must` filter for `workspace_id` and, unless the grant is `*`, a
`collection_id` `MatchAny` condition before querying. Disk fallback applies the
same scope. Results and citations retain collection/checksum provenance.

The Professor adapter accepts the same trusted workspace/collection context and
uses a named dense vector. Planner output may select IDs from the retrieved set,
but cannot provide replacement evidence text, source, or provenance.

## Compatibility and failure behavior

- Old collection names are normalized at the adapter boundary.
- A malformed collection identifier is rejected; no arbitrary Qdrant path is
  constructed.
- Qdrant failure is explicit in the retrieval method (`disk_fallback` when the
  bounded local corpus fallback is used).
- A provider-free deterministic test double proves plumbing only; it is not
  evidence of live embedding/LLM quality.
- Legacy payloads may still be readable, but they are not silently promoted to
  a complete canonical schema. Migration/reconciliation remains a separate,
  additive operation.

Evidence: `cvg-master-rag-v2/src/services/rag_contract.py`,
`cvg-master-rag-v2/src/services/vector_service.py`,
`cvg-master-rag-v2/src/services/ingestion_service.py`,
`cvg-master-rag-v2/src/services/api_security.py`,
`scripts/phase05/phase05_e2e.py`, and
`docs/baselines/phase-0.5-characterization.json`.

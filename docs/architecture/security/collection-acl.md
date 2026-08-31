# Collection ACL contract

Collection authorization is evaluated as a conjunction:

```text
active session
  + matching workspace_id
  + requested collection_id in allowed_collection_ids (or wildcard)
  -> retrieval and metadata access
```

Qdrant queries add mandatory `workspace_id` and `collection_id` filters before
search. The disk fallback applies the same scope. API list/detail routes filter
documents, ingestion jobs, collection summaries and source metadata before
pagination or serialization, and an inaccessible source is returned as a
not-found response. This prevents an authorized tenant from learning another
collection's names, counts, filenames or source metadata through list or detail
routes.

The canonical logical collection is `rag_phase0`; compatibility aliases are
normalized at the boundary. Collection IDs are validated before they reach the
vector adapter. A grant can be wildcard or a finite set of logical collection
IDs. The ACL is additive to role permissions: a role that can query still cannot
read a collection outside its grant.

Known residual: direct legacy service seams may retain a default workspace for
compatibility, while protected API data routes require an authenticated context
before returning protected data. The remaining external-route inventory and
deployment-wide authentication middleware still require production validation,
as does distributed session/rate-limit backing.

Evidence: `cvg-master-rag-v2/src/services/api_security.py`,
`cvg-master-rag-v2/src/services/authorization.py`,
`cvg-master-rag-v2/src/services/vector_service.py`,
`cvg-master-rag-v2/src/api/main.py`, and
`cvg-master-rag-v2/src/tests/test_phase05_security.py`.

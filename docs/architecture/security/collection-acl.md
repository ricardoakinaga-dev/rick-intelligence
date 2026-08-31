# Collection ACL contract

Collection authorization is evaluated as a conjunction:

```text
active session
  + matching workspace_id
  + requested collection_id in allowed_collection_ids (or wildcard)
  -> retrieval and permitted metadata access
```

Qdrant queries add mandatory `workspace_id` and `collection_id` filters before
search. The disk fallback applies the same scope. API list/detail routes filter
documents, ingestion jobs, collection summaries and source metadata before
pagination or serialization, and an inaccessible source is returned as a
not-found response. This prevents an authorized tenant from learning another
collection's names, counts, filenames or source metadata through list or detail
routes.

The veterinarian `sources.read` grant is an answer/retrieval output permission,
not a catalog grant. It may expose only the source metadata already selected
inside the server-created retrieval context. It does not imply
`library.browse` or unrestricted `documents.read`; document-list/detail routes
remain denied. Citation rendering must use the same workspace and collection
ACL as the underlying result.

The canonical logical collection is `rag_phase0`; compatibility aliases are
normalized at the boundary. Collection IDs are validated before they reach the
vector adapter. A grant can be wildcard or a finite set of logical collection
IDs. The ACL is additive to role permissions: a role that can query still cannot
read a collection outside its grant. Session collection snapshots are preserved
for the lifetime of a valid session; an explicit empty or reduced permission
snapshot is authoritative and cannot be re-expanded by the current role.

Known residual: direct legacy service seams may retain a default workspace for
compatibility, while protected API data routes require an authenticated context
before returning protected data. The remaining external-route inventory and
deployment-wide authentication middleware still require production validation,
as does distributed session/rate-limit backing.

Evidence: `cvg-master-rag-v2/src/services/api_security.py`,
`cvg-master-rag-v2/src/services/authorization.py`,
`cvg-master-rag-v2/src/services/enterprise_service.py`,
`cvg-master-rag-v2/src/services/vector_service.py`,
`cvg-master-rag-v2/src/api/main.py`,
`cvg-master-rag-v2/src/tests/test_phase05_security.py`, and
`cvg-master-rag-v2/src/tests/test_phase06_rbac.py`.

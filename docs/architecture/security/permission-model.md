# Roles and permission model

The public authorization vocabulary is canonical and explicit:

| Role | Intended owner | Permission shape |
| --- | --- | --- |
| `PLATFORM_ADMIN` | platform operator | all administrative and operational permissions |
| `KNOWLEDGE_MANAGER` | corpus/operations operator | documents, collections, ingestion, reindex, observability, audit and corpus inspection |
| `VETERINARIAN` | clinical consumer | query/search, answer and citation consumption within granted collections |

Legacy role labels are accepted only at the compatibility boundary: `admin` and
`super_admin` map to `PLATFORM_ADMIN`; `operator` and `admin_rag` map to
`KNOWLEDGE_MANAGER`; `viewer`, `veterinarian` and `auditor` map to
`VETERINARIAN`. New API responses expose the canonical role.

Permission decisions are server-side and use the authenticated session snapshot.
The platform administrator has the wildcard grant. A knowledge manager receives
the operational corpus permissions but not `runtime.manage` or
`sessions.revoke`; a veterinarian receives the read/query surface only.
Administrative tenant and user routes require `PLATFORM_ADMIN`. Collection,
document, ingestion-job and source-list responses are filtered by the same
workspace and collection grants used by retrieval.

Session administration is also owner-safe: a user may revoke only its own
opaque session identifiers, while cross-user revocation requires the explicit
`sessions.revoke` permission. The session list never returns raw bearer values.

The effective collection grant is explicit when present. Platform and knowledge
manager sessions without an explicit collection restriction may operate on the
authorized workspace corpus; veterinarian sessions default to the canonical
`rag_phase0` grant unless a narrower grant is persisted. A requested collection
outside the grant is rejected or produces no results according to the route
contract; it is never used to enumerate another tenant's corpus.

Evidence: `cvg-master-rag-v2/src/services/authorization.py`,
`cvg-master-rag-v2/src/services/api_security.py`,
`cvg-master-rag-v2/src/services/admin_service.py`,
`cvg-master-rag-v2/src/api/main.py`, and
`cvg-master-rag-v2/src/tests/test_phase05_security.py`.

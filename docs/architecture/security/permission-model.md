# Roles and permission model

The public authorization vocabulary is canonical and explicit:

| Role | Intended owner | Permission shape |
| --- | --- | --- |
| `PLATFORM_ADMIN` | platform operator | all administrative and operational permissions |
| `KNOWLEDGE_MANAGER` | corpus/operations operator | `chat.query`, history, library browse, document/catalog management, collections, ingestion, reindex, observability, audit and corpus inspection |
| `VETERINARIAN` | clinical consumer | `chat.query`, own history, `sources.read` and `collections.read` within granted collections |

Legacy role labels are accepted only at the compatibility boundary: `admin` and
`super_admin` map to `PLATFORM_ADMIN`; `operator` and `admin_rag` map to
`KNOWLEDGE_MANAGER`; `viewer`, `veterinarian` and `auditor` map to
`VETERINARIAN`. API responses retain the compatibility `role` label and expose
the canonical value separately as `canonical_role`.

Permission decisions are server-side and use the authenticated session
snapshot. The platform administrator has the wildcard grant. A knowledge
manager receives the operational corpus permissions but not `runtime.manage`
or `sessions.revoke`; a veterinarian receives only the clinical query,
own-history, source, and collection-scope surface.

`sources.read` is deliberately narrower than `library.browse` and
`documents.read`: it allows only the source metadata/citations attached to an
authorized answer or retrieval result. It does not authorize listing the
library, opening arbitrary documents, downloading files, or discovering
unrelated source metadata. `documents.read` and `library.browse` are
knowledge-manager/platform permissions. Administrative tenant and user routes
require `PLATFORM_ADMIN`. Collection, document, ingestion-job and source-list
responses are filtered by the same workspace and collection grants used by
retrieval; a citation can never bypass that ACL.

Per-user overrides are normalized as explicit `add` and `remove` sets. Removal
wins when a permission appears in both sets. A wildcard role is expanded to
the registered permission set whenever it has explicit removals, so a removed
permission is never re-granted by wildcard or role fallback. An explicit empty
session snapshot is authoritative and cannot fall back to the current role.

Session administration is also owner-safe: a user may revoke only its own
opaque session identifiers, while cross-user revocation requires the explicit
`sessions.revoke` permission. The session list never returns raw bearer values.

The effective collection grant is explicit when present. Platform and knowledge
manager sessions without an explicit collection restriction may operate on the
authorized workspace corpus; veterinarian sessions default to the canonical
`rag_phase0` grant unless a narrower grant is persisted. A requested collection
outside the grant is rejected or produces no results according to the route
contract; it is never used to enumerate another tenant's corpus.

Existing persisted sessions keep their role, permission, and collection
snapshots. Updating a user's overrides affects newly issued sessions; an
existing snapshot is not silently widened or reduced. Password, status, or
role lifecycle invalidation revokes sessions and requires a new login.

Evidence: `cvg-master-rag-v2/src/services/authorization.py`,
`cvg-master-rag-v2/src/services/api_security.py`,
`cvg-master-rag-v2/src/services/admin_service.py`,
`cvg-master-rag-v2/src/services/enterprise_service.py`,
`cvg-master-rag-v2/src/api/main.py`, and
`cvg-master-rag-v2/src/tests/test_phase05_security.py` plus
`cvg-master-rag-v2/src/tests/test_phase06_rbac.py`.

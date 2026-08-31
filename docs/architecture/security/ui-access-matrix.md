# UI access matrix

The frontend presents the minimum surface needed for each authenticated role;
the API remains the authority for every action.

| Surface | `PLATFORM_ADMIN` | `KNOWLEDGE_MANAGER` | `VETERINARIAN` | Unauthenticated |
| --- | --- | --- | --- | --- |
| Login/recovery | yes | yes | yes | public entry only |
| Query, answer and authorized citations | yes | yes | yes | no |
| Own chat history | yes | yes | yes | no |
| Library browse and document catalog | yes | yes | no | no |
| Upload/ingestion | yes | yes | no | no |
| Collection/document/job operations | yes | yes | no | no |
| Tenant/user administration | yes | no | no | no |
| Runtime/session administration | yes | no | no | no |
| Tenant switching | authorized tenants only | authorized tenants only | authorized tenants only | no tenant enumeration |

The veterinarian UI exposes Chat, where the user can see its own browser-side
conversation history and source cards returned by an authorized query. It does
not expose the library/document catalog, uploads, admin, dashboard, or audit
surfaces. A source card is not a library browse capability and cannot be used
to open an arbitrary document.

Anonymous bootstrap intentionally returns no tenant choices. Login and recovery
use a manually entered tenant identifier, while the authenticated session may
populate only its authorized tenant list. UI hiding is a usability boundary, not
a security boundary: each mutating or data-bearing request is checked again on
the server.

Evidence: `cvg-master-rag-v2/frontend/app/login/page.tsx`,
`cvg-master-rag-v2/frontend/app/recover-access/page.tsx`,
`cvg-master-rag-v2/frontend/tests/phase2-gate.spec.ts`, and
`cvg-master-rag-v2/src/api/main.py`.

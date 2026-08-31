# UI access matrix

The frontend presents the minimum surface needed for each authenticated role;
the API remains the authority for every action.

| Surface | `PLATFORM_ADMIN` | `KNOWLEDGE_MANAGER` | `VETERINARIAN` | Unauthenticated |
| --- | --- | --- | --- | --- |
| Login/recovery | yes | yes | yes | public entry only |
| Query/search and citations | yes | yes | yes | no |
| Upload/ingestion | yes | yes | no | no |
| Collection/document/job operations | yes | yes | no | no |
| Tenant/user administration | yes | no | no | no |
| Runtime/session administration | yes | no | no | no |
| Tenant switching | authorized tenants only | authorized tenants only | authorized tenants only | no tenant enumeration |

Anonymous bootstrap intentionally returns no tenant choices. Login and recovery
use a manually entered tenant identifier, while the authenticated session may
populate only its authorized tenant list. UI hiding is a usability boundary, not
a security boundary: each mutating or data-bearing request is checked again on
the server.

Evidence: `cvg-master-rag-v2/frontend/app/login/page.tsx`,
`cvg-master-rag-v2/frontend/app/recover-access/page.tsx`,
`cvg-master-rag-v2/frontend/tests/smoke.spec.ts`, and
`cvg-master-rag-v2/src/api/main.py`.

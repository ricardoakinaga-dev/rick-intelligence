# Live Qdrant Vector Store Adapter

Status: adapter implemented and hermetically verified; production integration is a separate gate.

## Boundary

`rick_retrieval.qdrant.QdrantHttpVectorStore` is the live HTTP implementation
of the synchronous `VectorStore` seam in
`packages/retrieval/src/rick_retrieval/vectordb.py`. It does not read
environment variables, select a default server, or make a request at import
time. Construction requires both an explicit `base_url` and `collection`.

The default transport is created lazily with the repository's existing `httpx`
stack. Tests and callers may inject a synchronous `HttpTransport` (including an
`httpx.MockTransport`) without starting Qdrant or opening a socket.
If the optional default transport dependency is absent, construction fails with
the typed `QdrantDependencyError`; no import-time fallback or network probe is
performed.

## HTTP operations

| Adapter operation | Qdrant request | Result handling |
| --- | --- | --- |
| `health()` | `GET /healthz` | returns bounded `QdrantHealth`; server body is not retained |
| `upsert_points(points)` | `PUT /collections/{collection}/points?wait=true` | sends named `dense` vectors and canonical payload fields; returns submitted point count |
| `query(...)` | `POST /collections/{collection}/points/query` | returns validated `QdrantSearchHit` values |
| `search(...)` | `POST /collections/{collection}/points/search` | compatibility search route with the same ACL and response validation |
| `delete_by_filter(...)` | `POST /collections/{collection}/points/delete` | accepts only adapter-built, ACL-prefixed filters; returns `QdrantDeleteResult` |
| `count_for_document(...)` | `POST /collections/{collection}/points/count` | exact count over tenant/workspace/collection/document scope |

`delete_document` remains available for the existing contract. It requires a
workspace at call time, because a document and collection without tenant and
workspace scope are not safe delete inputs.

## Authorization and response safety

Every finite-grant query, search, delete, and count request sends Qdrant
payload filters for:

```text
tenant_id == caller tenant
AND workspace_id == caller workspace
AND collection_id IN allowed_collection_ids
```

An empty collection grant is an authoritative deny and produces no remote
query. A wildcard grant is supported by the retrieval contract and omits only
the finite collection predicate; the explicit physical Qdrant collection,
tenant, and workspace boundaries remain in force. Returned payloads are
revalidated against the same scope before becoming search hits, so an
incorrect or compromised server response cannot publish a foreign point.

Raw delete filters are not accepted: callers provide a document and/or chunk
selector, and the adapter prepends the mandatory ACL predicates. Upserts also
require string `tenant_id`, `workspace_id`, and `collection_id` payload fields.

## Bounds and failures

The adapter enforces finite limits for upsert point count, query result count,
collection filters, vector dimensions, serialized payloads, request bodies,
query bodies, and response bodies. These hard ceilings can be lowered per
instance, never raised. JSON serialization rejects non-finite numbers.

Transport timeouts, transport failures, non-2xx responses, oversized bodies,
malformed JSON, non-finite constants, duplicate keys, malformed result shapes,
invalid input, and use after close map to typed `QdrantError` subclasses. The
single response decoder applies the finite/duplicate-free contract to every
JSON response before lifecycle, projection, query or delete validation. Errors retain only an operation and
safe status/code metadata: URLs, API keys, request payloads, response bodies,
and underlying exception messages are not retained or rendered.

`close()` is synchronous, idempotent, and deterministic. The adapter also
supports the synchronous context-manager protocol.

## Verification and integration gate

Focused tests in `packages/retrieval/tests/test_qdrant.py` use an in-memory
transport. They cover server-side ACL filter construction, defense-in-depth
filtering, empty-grant denial, timeout/status redaction, malformed,
non-finite, duplicate-key and oversized responses, point/query/payload bounds,
delete/count scoping, and idempotent close.

Live integration is intentionally not wired into application settings or
production composition in this change.

```text
Live Qdrant evidence: NOT_RUN
Integration gate: NOT_RUN
```

The separate integration gate must supply an authorized test Qdrant endpoint,
an explicitly selected collection, matching payload indexes/schema, synthetic
tenant/workspace fixtures, and a cleanup/recovery procedure. It must then
prove health, upsert, query/search ACL isolation, delete/count scope, timeout
behavior, and close/connection cleanup against that endpoint before any
production settings are changed.

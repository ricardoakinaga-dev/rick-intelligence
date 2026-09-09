# RICK Intelligence threat model

Status: `REVIEW BASELINE / EXTERNAL PENETRATION AND DEPLOYMENT TESTS PENDING`.

## Assets and actors

Assets are credentials, sessions, tenant data, documents, chunks, vector
payloads, job state, provider prompts/responses, audit records and operational
metadata. Actors include an anonymous internet client, an authenticated tenant
user, a malicious tenant user, a compromised provider/document, an operator,
and a compromised dependency or worker.

## Trust boundaries

1. browser ↔ API/Next proxy;
2. API middleware ↔ identity and authorization;
3. tenant request ↔ knowledge, object, vector, cache, job and audit stores;
4. API/worker ↔ PostgreSQL, Redis, Qdrant, object store and provider;
5. retrieved document data ↔ system/provider instructions;
6. build pipeline ↔ published container artifact.

## Threats and controls

| Threat | Control | Residual evidence |
| --- | --- | --- |
| session/API-key confusion | explicit cookie/bearer precedence, CSRF/origin checks, secure production cookie | live identity/OIDC gate pending |
| cross-tenant read or write | server-derived scope, ACL filters, post-read revalidation, negative tests | live stores and multi-replica test pending |
| path traversal/upload abuse | normalized names, bounded body/staging, magic/MIME and parser limits | malicious corpus/process isolation pending |
| prompt/tool injection | corpus is untrusted data; evidence IDs are server-generated; provider/tool contracts are bounded | adversarial full pipeline pending |
| credential leakage | redaction, no secrets in errors/events/images, runtime injection | external scanner and deployment review pending |
| rate-limit bypass/DoS | bounded local fixture plus required distributed Redis boundary in production | live Redis/multi-replica evidence pending |
| stale worker mutation | owner/version lease fencing, heartbeat and deadline checks | PostgreSQL concurrency/crash evidence pending |
| poisoned dependency/image | lockfiles, pinned workflow actions, non-root images, release manifest, SBOM/scan/signature gates | image build and scan pending |
| forwarded-header spoofing | trusted proxy CIDR allowlist; untrusted headers ignored | deployment proxy topology pending |
| audit/telemetry exfiltration | append-oriented sinks, field allowlists, opaque refs, bounded labels | durable external sink drill pending |

The application treats passwords, tokens, provider secrets, raw prompts,
document content and stack traces as sensitive. Residual risks are explicit:
external service configuration, hard handler isolation, image provenance,
restore/rollback, live abuse testing and clinical corpus validation cannot be
proved by hermetic unit tests.

## Required adversarial coverage

The security lane must exercise authentication, authorization, tenant
negatives, SSRF and forwarded headers, path traversal, malformed/malicious
files, archive/decompression limits, prompt injection, retrieval poisoning,
tool injection, credential/log leakage, CORS/CSRF, rate-limit bypass and
resource exhaustion. A clean local result is a scoped approval, not a
penetration-test claim.

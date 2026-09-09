# `packages/evidence`

`rick-evidence` is the evidence authority between authorized retrieval and
reasoning. It has no HTTP, database, vector store, provider, or Professor
caller dependency.

`EvidenceValidator.issue()` receives an already authorized
`EvidenceScope` and a retrieval candidate. It takes the candidate's source
fields, requires a document version and checksum, and issues a fresh
content-addressed `evidence_id`. A retrieval-provided ID is never trusted or
copied. The digest covers tenant, workspace, collection, document,
document version, chunk, source, page, section, checksum, excerpt, and the two
raw ranking signals.

`EvidenceBundle.build()` enforces one tenant/workspace/collection scope and
creates a deterministic `bundle_id` plus the only valid citation markers:
`[cite:<evidence_id>]`. `EvidenceValidator.validate_citations()` resolves
markers against that server-generated map. `validate_claim_support()` provides
a bounded lexical screening signal; it is not entailment, calibration, truth,
or domain correctness.

```python
from rick_evidence import EvidenceScope, EvidenceValidator

scope = EvidenceScope(
    tenant_id="tenant-a",
    workspace_id="workspace-a",
    collection_id="collection-a",
)
validator = EvidenceValidator()
bundle = validator.build_bundle(
    query="What does the source say?",
    scope=scope,
    document_version="v1",
    candidates=[{
        "document_id": "document-a",
        "chunk_id": "chunk-a-0001",
        "source": "source.txt",
        "checksum": "sha256:fixture",
        "text": "The source records a bounded fact.",
        "score": 0.9,
        "reranking_score": 0.8,
    }],
)
```

The package does not perform authorization. The integration seam is the
caller that constructs `EvidenceScope` from the authenticated retrieval
context, enriches current retrieval records with the authoritative document
version, and passes the resulting bundle to a reasoning or decision layer.
No existing API, retrieval, or Professor caller is changed by this package.

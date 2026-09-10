# Evidence engine

Evidence is a server-generated, immutable reference to authorized source
material. An evidence item binds `evidence_id`, tenant, workspace, collection,
document/version, chunk, source, page/section, checksum and retrieval/rerank
metadata. The model may repeat an evidence ID only after the server has
resolved it from the current bundle; it cannot mint an ID that becomes trusted
by parsing model text.

`EvidenceBundle` is the bounded set passed from retrieval to Professor.
`EvidenceValidator` checks scope, identity, checksum/provenance shape, bounds
and citation mapping before generation and again before response publication.
Invalid or missing support maps to an explicit safe outcome. Raw document text
is untrusted data and never becomes a system instruction.

Citation quality is measured with precision, recall, completeness and
unsupported-claim rate. The typed decision seam consumes these observations
only when an approved evaluator supplies a PASS result; missing evidence stays
inconclusive. The current evaluator is identity-level citation support, not
semantic entailment or answer faithfulness. Local fixtures are synthetic;
clinical corpus quality, licensing and external validation remain separate
promotion gates.

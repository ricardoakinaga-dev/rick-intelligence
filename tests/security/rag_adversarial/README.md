# RAG adversarial corpus

This synthetic corpus is safe test input, not veterinary advice and not a
penetration-test result. Each record is untrusted document material. The
validator checks that the required attack classes, bounded payloads and
redaction-safe fixture rules are present before a runtime pipeline lane uses
the corpus.

Required runtime follow-up:

- run each record through upload, parsing, retrieval, evidence, provider and
  decision boundaries in an isolated disposable environment;
- assert no instruction from document text changes system policy or tool
  authorization;
- assert no secret, cross-tenant identifier or hidden citation is emitted;
- preserve the exact corpus hash and runtime artifact with the candidate.

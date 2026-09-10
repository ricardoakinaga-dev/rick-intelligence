# `packages/ingestion`

Reserved for the validated acquire → validate → parse → normalize → structure
→ chunk → enrich → embed → index → validate → publish pipeline. The current
CVG ingestion implementation remains unmoved.

The local compatibility path uses `InProcessParserRunner`. The external worker
composition uses `ProcessParserRunner` (the backwards-compatible parser name
for `ProcessIsolatedExecutor`), which runs each parser in a fresh `spawn`
child with a wall-clock deadline, advisory resource limits and process-group
termination. Parser stdout and stderr are redirected to a sink before parser
code runs, so untrusted/native diagnostics have a zero-byte external bound;
structured parser results use the bounded JSON-only versioned wire schema and
hard serialized-result ceiling. The parent never unpickles child data.
Oversized or malformed custom-runner output fails closed. The local default
remains in-process for compatibility; external composition opts into the
isolated runner explicitly. PDF and DOCX support is packaged in the API and
worker images with pinned `pdfplumber` and `python-docx` dependencies.

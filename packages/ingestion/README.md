# `packages/ingestion`

Reserved for the validated acquire → validate → parse → normalize → structure
→ chunk → enrich → embed → index → validate → publish pipeline. The current
CVG ingestion implementation remains unmoved.

The local compatibility path uses `InProcessParserRunner`. The external worker
composition uses `ProcessParserRunner`, which runs each parser in a fresh
`spawn` child with a wall-clock deadline, advisory resource limits and
process-group termination. Parser results are schema-checked and bounded
before they cross the child pipe, including a hard serialized-result ceiling;
oversized or malformed custom-runner output fails closed. PDF and DOCX support is packaged in the API and
worker images with pinned `pdfplumber` and `python-docx` dependencies.

# ADR-003 — Canonical error envelope

Date: 2026-09-03. Status: Accepted.

`{error:{code,message,request_id,details}}` with the §12 taxonomy. Rationale:
stable machine codes for clients, safe human messages, request correlation for
support, and a single place (`core/errors.py`) where leak-prevention is audited.
Legacy `HTTPException` details are mapped, never forwarded verbatim.

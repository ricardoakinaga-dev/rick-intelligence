# API Compatibility (OpenAI / OpenWebUI)

`POST /v1/chat/completions` and `GET /v1/models` are adapters over the canonical
`ChatApplicationService` — there is exactly one chat implementation.

## Preserved

- `stream: true/false`, OpenAI-shaped responses, `model` passthrough, conversation
  mapping (`conversation_id`/`user` → platform `conversation_id`).
- SSE chunk sequence `role → content* → stop → [DONE]`; mid-stream failures emit
  a typed error event, never a fake completion.

## Documented deviations

- `usage` is `null`, never fabricated (legacy Professor returned zeros).
- Citations/metadata ride in platform chat; compat responses expose `metadata`
  only (no chain-of-thought anywhere).
- Auth is `Bearer <compat-key>` (constant-time) or `X-API-Key`; compat keys live
  in server config, are never logged, and rotate via env.
- `GET /v1/models` returns the single `rick-professor` model id.

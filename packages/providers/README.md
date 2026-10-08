# `packages/providers`

Root-owned typed provider boundary for Phase 1.5. `OpenAICompatibleClient`
performs async `POST /chat/completions` and `POST /embeddings` requests and
returns the DTOs from `rick_contracts.providers`. Both operations share
correlation propagation, timeout classification, bounded exponential retry,
response validation, and safe `ProviderError` serialization.

```python
from rick_providers import OpenAICompatibleClient, ProviderConfig

config = ProviderConfig(
    base_url="https://api.openai.com/v1",
    api_key="configured-outside-logs",
    chat_model="gpt-4o-mini",
    embedding_model="text-embedding-3-small",
    embedding_dimensions=1536,
)

async with OpenAICompatibleClient(config) as provider:
    answer = await provider.chat_completion(
        messages=[{"role": "user", "content": "Hello"}],
    )
    vector = await provider.get_embedding("Hello")
```

`DeterministicProvider` is a labeled, non-semantic test/dev double. It can be
selected by `create_provider` only with `provider_kind="deterministic"` and an
explicit `test`, `testing`, `dev`, `development`, or `local` environment; a
production configuration fails closed.

Streaming completion requires a recognized terminal choice, `[DONE]`, and HTTP
response EOF. The terminal chunk is withheld until the complete bounded response
passes validation; earlier deltas remain provisional. Empty or whitespace-only
text without tool deltas receives `missing_field`, matching JSON completions.
`length`, `content_filter`, and `tool_calls` remain distinct typed conclusions;
only an explicit `stop` without pending tool calls is eligible for Professor
evidence approval. Professor has no tool executor: its tool budget limits
received calls and does not authorize treating them as executed results.
The JSON fallback preserves tool calls as ordered deltas.

Nonempty refusal markers fail closed in JSON and SSE. Completed streamed tool
calls must have consistent identity fields and strict JSON object arguments,
matching the full JSON response contract; partial argument fragments remain
valid while the stream is open.

A JSON completion or SSE data envelope containing a top-level `error` field is
rejected as nonretryable `malformed_response` before choices, usage, or termination
are extracted. Presence is decisive, including null, false, zero, empty, or
untyped error values. Error envelopes cannot also establish successful completion;
the raw error value is never included in public failure metadata.

Before `[DONE]`, a terminal choice may be followed by validated usage-only events,
blank lines, comments, and SSE `event`, `id`, or `retry` metadata. After `[DONE]`,
only blank lines, comments, and that SSE metadata are allowed. Additional data,
including usage, tools, content, invalid JSON, or another `[DONE]`, is a typed
protocol failure. Unknown non-data lines also fail validation.
OpenAI SSE data fields are joined with newlines and dispatched only at a blank
event separator. A pending data event at EOF fails closed, including an
undispatched `[DONE]`; physical lines never manufacture separate events.
Native OpenAI envelopes require `id`, `object`, `created`, `model`, and `choices`.
The native `id` and `created` remain identical across all choice and accounting
frames, including role-only frames, before terminal delivery.
Native choices require `index`, `message`/`delta`, and `finish_reason`;
`logprobs` is required (nullable) on JSON choices and optional on stream choices.
Native stream chunks also require `usage` (null on ordinary choices).
Native OpenAI requests include `stream_options.include_usage=true` and require
exactly one valid `choices=[]` accounting trailer after the terminal choice
before successful completion. Missing/null accounting fails closed. Explicit compatible
gateways may send cumulative usage before termination or trailers with
`choices=[]`. Repeated snapshots must retain all previously supplied fields,
fixed known prompt counters/details, and nondecreasing completion counters and
known details. Optional details may become known on a growing snapshot. Equal
totals require exactly equal snapshots. Any conflict fails closed. The latest
validated usage is retained on the terminal DTO even if received earlier.
Every choice after the terminal choice fails, including empty or role-only
deltas that would otherwise normalize away.

Explicit `openai_compatible` gateways retain historical core-field omission
and optional accounting policies. Native Chat Completions serialize configured
`max_output_tokens` as `max_completion_tokens`, including reasoning tokens;
explicit gateways use `max_tokens`. The adapter accepts integer caps 1..128000,
and GPT-4o/GPT-4o-mini aliases and dated snapshots additionally cap at 16384.
Sampling defaults and model compatibility checks still apply before I/O.
See the [official request reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [GPT-4o Mini limits](https://developers.openai.com/api/docs/models/gpt-4o-mini).
Other model-specific/account/context limits remain vendor constraints; the
adapter cap does not establish that an arbitrary model accepts that many tokens.

Native OpenAI health requires a nonempty model list advertising the configured
model by `id`. Explicit compatible gateways may instead return a JSON health
object without `data`, or advertise a model by `id`/`model`. Both policies reject
any top-level `error` field and present null, empty, or malformed model lists.

Anthropic omitted usage delta fields retain their prior values. Supplied raw
prompt/cache partitions, output counts and nested cumulative counters cannot
regress or become null/incomplete before normalization into the usage DTO.

Anthropic message envelopes require the documented core fields and allow only
the optional `stop_details` and typed `container` metadata. Unknown fields and
non-null refusal stop details fail closed in JSON and `message_start`. OpenAI
logprob content and top candidates validate token strings, finite nonpositive
log probabilities, nullable byte lists (integers 0..255), and exact nested field
sets. Nonempty refusal logprobs fail closed. Explicit OpenAI temperatures must
be finite numbers in 0..2; existing model support and omission rules still apply.

JSON and SSE require valid UTF-8 bytes; encoding failures are nonretryable
`malformed_response`. SSE uses strict incremental decoding through HTTP EOF,
including comments, metadata, usage, and tails. Fragmented multibyte characters
and CRLF, an initial SSE BOM, and a correctly encoded U+FFFD are valid. Invalid
or incomplete sequences never become replacement text or a terminal completion.

All response bytes, including comments and tails, count toward
`MAX_RESPONSE_BYTES`. One deadline starts before request headers and bounds the
entire response through EOF. Keepalives cannot renew it. Cancellation or early
closure closes the parser and HTTP response; accepted output is never replayed.

For a cancellation-cooperative async transport/sleeper, let `T` be the configured
request timeout (the largest finite HTTPX phase timeout), `N=max_attempts`, and
`D_j=min(max_backoff_delay, retry_base_delay * 2**(j-1))`. Each HTTP attempt gets
`T`, plus at most 0.125 s to drain an interrupted read and 0.25 s for response
cleanup. Each retry sleeper receives exactly `D_j`, with an owned deadline of
`D_j + T` and at most 0.125 s to join cancellation cleanup. A sleeper timeout
returns typed `timeout` immediately without another attempt. Thus the active
adapter I/O budget is at most `N*(T+0.375) + sum(D_j+T+0.125, j=1..N-1)`;
normal sleep delays and configured retry counts/caps are preserved. Streaming
facade cancellation reserves up to 1.0 s separately for read/iterator cleanup,
and explicit provider close reserves 0.25 s separately. Synchronous hooks must
return promptly; blocking or cancellation-suppressing injected code, scheduler
delays, local validation CPU time, and time suspended at a caller's `yield` are
outside this cooperative I/O budget.

Accepted OpenAI/native or compatible `json_schema` requests validate JSON syntax
and schema constraints for buffered results and before streaming terminal delivery,
including when `strict` is false or omitted. Earlier stream deltas remain
provisional: malformed output fails without a terminal or replay. Invalid syntax
is nonretryable `invalid_json`; a constraint violation is nonretryable
`malformed_response`. Text, JSON-object and tool termination policies still apply.
Anthropic continues to accept only text and JSON-object response formats.

Schema configuration is checked before I/O with the maintained
`jsonschema==4.26.0` Draft 2020-12 validator. The dialect may be omitted or exactly
`https://json-schema.org/draft/2020-12/schema`. Supported constraints are `type`
(including nullable type lists), `enum`, `const`, `properties`, `required`,
`additionalProperties`, `items`, `prefixItems`, `minItems`, `maxItems`,
`uniqueItems`, `minProperties`, `maxProperties`, `minLength`, `maxLength`,
`minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, and `multipleOf`.
Nested boolean schemas are supported. `title`, `description`, `default`,
`examples`, `deprecated`, `readOnly` and `writeOnly` are annotations, not extra
assertions. All other keywords fail before I/O, including `format`, regexes,
combinators and all references (local, remote or file). In particular, this
adapter makes no format-validation claim. An explicit Registry also denies
reference retrieval. See the official
[validation](https://python-jsonschema.readthedocs.io/en/stable/validate/) and
[referencing](https://python-jsonschema.readthedocs.io/en/v4.25.0/referencing/) docs.

Schemas are limited to 65,536 UTF-8 JSON bytes, depth 16 and 1,024 value nodes.
Structured results retain the 1,000,000-byte response limit and additionally
allow depth 32 and 4,096 value nodes. Both limit containers to 256 entries.
These bounds and the reference/regex/combinator exclusions constrain local
validation work; they do not establish vendor support for every accepted schema.
Invalid or unsupported schema configuration fails with zero attempts.

Anthropic text citations support absent, null or empty-list metadata. Every
other value fails as nonretryable `malformed_response`, including false, zero,
empty strings/objects and populated lists. Native Anthropic health rejects the
presence of any `error` field, without exposing its value.

Native model identity permits only these documented alias relationships:
`gpt-4o-mini` to `gpt-4o-mini-2024-07-18`, and `claude-sonnet-4-5` or
`claude-haiku-4-5` to a valid dated snapshot of that same family and minor version.
The request retains its selected ID exactly; buffered results and all streaming
DTOs retain the response's actual model. OpenAI stream model, ID and creation
time remain fixed across every frame, including accounting and empty deltas.
Pinned IDs, Anthropic 4.6+ dateless IDs and unrelated model mismatches require
equality. Compatible gateways retain equality rather than inheriting native
alias rules. These checks implement a documented relationship, not live model
existence or current alias resolution. See the
[GPT-4o Mini snapshots](https://developers.openai.com/api/docs/models/gpt-4o-mini)
and [Anthropic versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).
Other aliases, including dynamic chat aliases, remain unresolved here; a future
bounded option would require an explicit request-to-allowed-response ID contract.

Adding the JSON Schema runtime dependency makes prior API/worker image scans
STALE. Integration requires the Parent's full affected regression, lock audit,
image rebuild/scans and fresh independent review; local memory tests do not
approve production or establish TCP/TLS or live vendor behavior.

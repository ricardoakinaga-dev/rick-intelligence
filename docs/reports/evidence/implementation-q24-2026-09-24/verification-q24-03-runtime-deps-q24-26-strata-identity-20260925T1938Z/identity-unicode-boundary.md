# Q24-26 identity Unicode boundary

A final local audit after the scoped independent PASS found that Python's JSON decoder can produce a string containing an unpaired surrogate from an escaped value such as `\ud800`. The prior identity validators accepted every non-empty Python string, while URI quoting or UTF-8 dimension encoding cannot encode that value and could raise `UnicodeEncodeError`.

Both campaign and pack identity validators now reject unpaired surrogate code points with their domain-specific validation error. Valid Unicode strings remain byte-for-byte unchanged, including whitespace-only identities and labels. The regression test covers isolated high and low surrogates and an embedded high surrogate for both evaluators.

Validation after this fix: campaign evaluator 23/23; pack evaluator 15/15; `make eval-retrieval-pack`, `make lint`, and `make typecheck` pass. The checked-in v4 campaign remains synthetic with `campaign_status=NOT_RUN`, `eligibility_status=BLOCKED`, and every observed response disposition `NOT_MEASURED`. A new independent review of the updated source snapshot is pending.

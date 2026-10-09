# Security tests

Status: CURRENT (2026-10-09). This directory documents the lane; it does not
contain a second executable suite.

Route policies, tenant/resource negatives and bounded synthetic RAG attacks. The executable sources are in
[apps/api/tests](../../apps/api/tests/). Run from the repository root:

```bash
make api-security api14-acl security-adversarial
```

The [root command contract](../../README.md) identifies related gates. Local
adapter/fixture results do not establish distributed production behavior.
Runtime gates use explicit approved endpoints and return `2` when externally
blocked; `0` is reserved for an executed pass and `1` for an observed failure.

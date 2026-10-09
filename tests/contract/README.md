# Contract tests

Status: CURRENT (2026-10-09). This directory documents the lane; it does not
contain a second executable suite.

Versioned DTOs and HTTP/OpenAPI contracts. The executable sources are in
[packages/contracts/tests](../../packages/contracts/tests/). Run from the repository root:

```bash
make api15-contracts api-contract
```

The [root command contract](../../README.md) identifies related gates. Local
adapter/fixture results do not establish distributed production behavior.
Runtime gates use explicit approved endpoints and return `2` when externally
blocked; `0` is reserved for an executed pass and `1` for an observed failure.

# End-to-end tests

Status: CURRENT (2026-10-09). This directory documents the lane; it does not
contain a second executable suite.

Canonical browser matrix at mobile/tablet/desktop viewports against the loopback API. The executable sources are in
[apps/web/tests](../../apps/web/tests/). Run from the repository root:

```bash
make web-validate
```

The [root command contract](../../README.md) identifies related gates. Local
adapter/fixture results do not establish distributed production behavior.
Runtime gates use explicit approved endpoints and return `2` when externally
blocked; `0` is reserved for an executed pass and `1` for an observed failure.

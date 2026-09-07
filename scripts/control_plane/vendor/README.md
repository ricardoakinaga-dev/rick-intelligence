# Canonical controller validator snapshot

`engineering_framework/` is a byte-identical snapshot of the installed
engineering-framework 2.0.0 controller validator, its shared stdlib helper and
canonical contract. It is kept local so CI does not depend on an agent's home
directory. No normative enums or validation rules were changed.

Upstream installed package paths: `scripts/check_state.py`,
`scripts/_framework.py`, `references/contracts.json`. The checker SHA256 is
`2de9506b3f59455ef2c05ca66c9a47a0ae4926b9eb1521ad3064b42260eacf6d`.
The helper independently guards the canonical contract fingerprint.

Run from repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/control_plane/vendor/engineering_framework/scripts/check_state.py .
```

The root CI wrapper also verifies preserved historical controller hashes. A
validator update requires explicit source/provenance review, new negative tests
and renewed controller verification. This snapshot does not certify the product
or import the framework's own release requirements as RICK product requirements.

`gauntlet_loop/gauntlet_state.py` began as a byte-identical snapshot of the
installed Gauntlet state manager, upstream SHA256
`3677b41f74afe2898ce6d50c4dae605a73d564d44077752e56f7f2c3b6ce0589`.
It now carries a local fail-closed extension after an independent replay finding:
final evidence and critic records require the active run ID and zoned observation
intervals after creation/last rebaseline and before acceptance; the critic must
follow its evidence. Both finish and persisted-state validation apply this check.
Existing upstream acceptance checks remain intact. The installed helper is not
modified. Regression: `scripts/state_of_art/test_review_run_binding.py`.
CI invokes the local copy's read-only structural validation;
artifact identity and current evidence are additionally checked explicitly during
resume and sealed review. Structural PASS is never full quality-bar acceptance.

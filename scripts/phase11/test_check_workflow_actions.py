"""Workflow action references must be immutable and free of retired component paths."""

from scripts.phase11.check_workflow_actions import check_actions, check_workflow


def test_repository_actions_are_pinned() -> None:
    assert check_actions() == []


def test_floating_action_is_rejected_and_local_action_is_allowed() -> None:
    errors = check_workflow("fixture.yml", "  - uses: actions/checkout@v4\n  - uses: ./local-action\n")

    assert errors == [
        "fixture.yml:1: actions/checkout@v4 must use an exact 40-character commit SHA"
    ]


def test_comment_does_not_satisfy_the_pin_rule() -> None:
    """AUD07-04: a SHA written only in a trailing comment pins nothing."""
    sha = "11bd71901bbe5b1630ceea73d27597364c9af683"
    errors = check_workflow("fixture.yml", f"  - uses: actions/checkout@v4 # {sha}\n")

    assert errors == [
        "fixture.yml:1: actions/checkout@v4 must use an exact 40-character commit SHA"
    ]


def test_commented_out_step_is_not_evaluated() -> None:
    assert check_workflow("fixture.yml", "  # - uses: actions/checkout@v4\n") == []


def test_active_step_must_not_reference_a_retired_component() -> None:
    errors = check_workflow("fixture.yml", "        run: npm --prefix rick-professor ci\n")

    assert errors == [
        "fixture.yml:1: active step references retired component rick-professor"
    ]


def test_retired_component_mention_in_a_workflow_comment_is_allowed() -> None:
    text = "      # Historically the supply-chain lane covered modulo-redis-locker\n"
    assert check_workflow("fixture.yml", text) == []

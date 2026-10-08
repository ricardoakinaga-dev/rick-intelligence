"""Public SLO evaluation cannot approve invalid observations or budgets."""

import pytest

from rick_observability.slo import evaluate_slo


@pytest.mark.parametrize("overrides", [
    {"total": True}, {"errors": False}, {"total": -1}, {"errors": 2},
    {"latency_p95": float("nan")}, {"latency_p95": float("inf")},
    {"latency_p95": float("-inf")}, {"latency_p95": -0.1},
    {"latency_p95": True}, {"latency_p95": "1"},
    {"max_error_rate": float("nan")}, {"max_error_rate": float("inf")},
    {"max_error_rate": True}, {"max_error_rate": "0.01"},
    {"max_latency_p95": float("nan")}, {"max_latency_p95": float("inf")},
    {"max_latency_p95": -1}, {"max_latency_p95": True},
])
def test_invalid_inputs_fail_closed(overrides):
    inputs = dict(total=1, errors=0, latency_p95=10.0, max_error_rate=0.01,
                  max_latency_p95=20.0)
    with pytest.raises(ValueError):
        evaluate_slo(**{**inputs, **overrides})


@pytest.mark.parametrize("total,errors,latency,status", [
    (0, 0, None, "no_data"), (100, 1, 10, "healthy"),
    (100, 2, 10, "breach"), (100, 0, 30, "breach"),
    (100, 0, None, "breach"),
])
def test_valid_observations_preserve_status(total, errors, latency, status):
    assert evaluate_slo(total=total, errors=errors, latency_p95=latency,
                        max_error_rate=0.01, max_latency_p95=20).status == status


@pytest.mark.parametrize("total,errors,budget,status", [
    (10**400, 1, 0, "breach"),
    (10**400, 0, 0, "healthy"),
    (2**54, 2**53 + 1, 0.5, "breach"),
    (2**54, 2**53, 0.5, "healthy"),
    (2**54, 2**53 - 1, 0.5, "healthy"),
    (100, 30, 0.3, "healthy"),
    (10**400, 10**399, 0.1, "healthy"),
    (10**400, 10**399 + 1, 0.1, "breach"),
])
def test_error_budget_comparison_preserves_integer_precision(total, errors, budget, status):
    decision = evaluate_slo(total=total, errors=errors, latency_p95=0,
                            max_error_rate=budget, max_latency_p95=0)
    assert decision.status == status

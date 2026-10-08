"""Small explicit SLO and alert evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math


@dataclass(frozen=True, slots=True)
class SloDecision:
    status: str
    reason: str
    error_rate: float | None
    latency_p95: float | None


def _validate_nonnegative_finite(value: object, name: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite nonnegative number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


def evaluate_slo(*, total: int, errors: int, latency_p95: float | None, max_error_rate: float, max_latency_p95: float | None = None) -> SloDecision:
    if type(total) is not int or type(errors) is not int or total < 0 or errors < 0 or errors > total:
        raise ValueError("invalid SLO counts")
    _validate_nonnegative_finite(max_error_rate, "max_error_rate")
    if not 0 <= max_error_rate <= 1:
        raise ValueError("max_error_rate is invalid")
    if latency_p95 is not None:
        _validate_nonnegative_finite(latency_p95, "latency_p95")
    if max_latency_p95 is not None:
        _validate_nonnegative_finite(max_latency_p95, "max_latency_p95")
    if total == 0:
        return SloDecision("no_data", "no observations", None, latency_p95)
    rate = errors / total
    # Configuration budgets use their decimal representation (e.g. 0.3 is
    # thirty percent). Compare integer counts exactly; the display rate may
    # round or underflow and must never decide whether a budget is exceeded.
    budget = Fraction(str(max_error_rate))
    if errors * budget.denominator > total * budget.numerator:
        return SloDecision("breach", "error rate exceeded budget", rate, latency_p95)
    if max_latency_p95 is not None and (latency_p95 is None or latency_p95 > max_latency_p95):
        return SloDecision("breach", "latency p95 exceeded budget", rate, latency_p95)
    return SloDecision("healthy", "within configured budget", rate, latency_p95)


@dataclass(frozen=True, slots=True)
class AlertRule:
    name: str
    max_error_rate: float
    max_latency_p95: float | None = None

    def evaluate(self, *, total: int, errors: int, latency_p95: float | None) -> SloDecision:
        return evaluate_slo(total=total, errors=errors, latency_p95=latency_p95, max_error_rate=self.max_error_rate, max_latency_p95=self.max_latency_p95)

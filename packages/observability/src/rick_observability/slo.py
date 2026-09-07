"""Small explicit SLO and alert evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SloDecision:
    status: str
    reason: str
    error_rate: float | None
    latency_p95: float | None


def evaluate_slo(*, total: int, errors: int, latency_p95: float | None, max_error_rate: float, max_latency_p95: float | None = None) -> SloDecision:
    if not isinstance(total, int) or not isinstance(errors, int) or total < 0 or errors < 0 or errors > total:
        raise ValueError("invalid SLO counts")
    if not 0 <= max_error_rate <= 1:
        raise ValueError("max_error_rate is invalid")
    if total == 0:
        return SloDecision("no_data", "no observations", None, latency_p95)
    rate = errors / total
    if rate > max_error_rate:
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

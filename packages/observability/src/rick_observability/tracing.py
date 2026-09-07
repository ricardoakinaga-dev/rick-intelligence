"""Correlation and deterministic trace sampling helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    request_id: str
    correlation_id: str
    trace_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.correlation_id, "correlation_id")
        if self.trace_id is not None:
            _identifier(self.trace_id, "trace_id")

    def as_dict(self) -> dict[str, str]:
        value = {"request_id": self.request_id, "correlation_id": self.correlation_id}
        if self.trace_id is not None:
            value["trace_id"] = self.trace_id
        return value


def should_sample(trace_id: str, rate: float) -> bool:
    """Return a stable sampling decision without random/global state."""

    _identifier(trace_id, "trace_id")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= float(rate) <= 1:
        raise ValueError("sampling rate is invalid")
    if rate == 0:
        return False
    if rate == 1:
        return True
    bucket = int.from_bytes(hashlib.sha256(trace_id.encode("utf-8")).digest()[:8], "big") / 2**64
    return bucket < float(rate)

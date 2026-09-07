"""Bounded in-memory metric primitives; no exporter or network side effects."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Mapping

MAX_METRICS = 256
MAX_LABELS = 8
MAX_LABEL_VALUE = 64
_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")


def _name(value: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError("metric name is invalid")
    return value


def _labels(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if labels is None:
        return ()
    if len(labels) > MAX_LABELS:
        raise ValueError("too many metric labels")
    clean: list[tuple[str, str]] = []
    for key, value in labels.items():
        if not isinstance(key, str) or _NAME.fullmatch(key) is None:
            raise ValueError("metric label name is invalid")
        if not isinstance(value, str) or not value or len(value) > MAX_LABEL_VALUE or any(ord(ch) < 0x20 for ch in value):
            raise ValueError("metric label value is invalid")
        clean.append((key, value))
    return tuple(sorted(clean))


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    name: str
    labels: tuple[tuple[str, str], ...]
    count: int
    total: float

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "labels": dict(self.labels), "count": self.count, "total": round(self.total, 6)}


class Histogram:
    def __init__(self, name: str, labels: Mapping[str, str] | None = None, *, max_samples: int = 10_000) -> None:
        self.name = _name(name)
        self.labels = _labels(labels)
        if not isinstance(max_samples, int) or not 0 < max_samples <= 100_000:
            raise ValueError("max_samples is out of range")
        self.max_samples = max_samples
        self._values: list[float] = []
        self._lock = RLock()

    def observe(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError("histogram value is invalid")
        with self._lock:
            if len(self._values) >= self.max_samples:
                self._values.pop(0)
            self._values.append(float(value))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            values = sorted(self._values)
        if not values:
            return {"name": self.name, "labels": dict(self.labels), "count": 0, "p50": None, "p95": None, "max": None}

        def nearest(percentile: float) -> float:
            position = max(1, math.ceil(percentile * len(values)))
            return round(values[position - 1], 6)

        return {"name": self.name, "labels": dict(self.labels), "count": len(values), "p50": nearest(.5), "p95": nearest(.95), "max": round(values[-1], 6)}


class CounterRegistry:
    """Bounded counter registry with explicit snapshots."""

    def __init__(self, *, max_metrics: int = MAX_METRICS) -> None:
        if not isinstance(max_metrics, int) or not 0 < max_metrics <= MAX_METRICS:
            raise ValueError("max_metrics is out of range")
        self.max_metrics = max_metrics
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, float]] = {}
        self._lock = RLock()

    def increment(self, name: str, *, value: float = 1.0, labels: Mapping[str, str] | None = None) -> float:
        metric = (_name(name), _labels(labels))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError("counter value is invalid")
        with self._lock:
            if metric not in self._counters and len(self._counters) >= self.max_metrics:
                raise ValueError("metric registry is full")
            count, total = self._counters.get(metric, (0, 0.0))
            self._counters[metric] = (count + 1, total + float(value))
            return total + float(value)

    def snapshot(self) -> tuple[MetricSnapshot, ...]:
        with self._lock:
            return tuple(
                MetricSnapshot(name, labels, count, total)
                for (name, labels), (count, total) in sorted(self._counters.items())
            )

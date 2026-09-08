"""Focused contract tests for the additive Phase 1.5 benchmark metrics."""

from __future__ import annotations

import unittest

from scripts.phase15 import benchmark


class Phase15BenchmarkMetricTests(unittest.TestCase):
    def test_summary_preserves_legacy_percentiles_and_adds_p99(self) -> None:
        summary = benchmark._summary([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["p50"], 3.0)
        self.assertEqual(summary["p95"], 4.0)
        self.assertEqual(summary["p99"], 4.0)
        self.assertLessEqual(summary["p95"], summary["p99"])

    def test_memory_observation_is_bounded_and_explicit(self) -> None:
        observation = benchmark._memory_observation(
            {"rss_bytes": 100, "peak_rss_bytes": 120},
            {"rss_bytes": 140, "peak_rss_bytes": 160},
        )

        self.assertEqual(observation["status"], "OBSERVED")
        self.assertEqual(observation["rss_delta_bytes"], 40)
        self.assertEqual(observation["peak_rss_bytes"], 160)
        self.assertIn("scope", observation)

    def test_memory_unavailable_is_not_reported_as_zero(self) -> None:
        observation = benchmark._memory_observation(
            {"rss_bytes": None, "peak_rss_bytes": None},
            {"rss_bytes": None, "peak_rss_bytes": None},
        )

        self.assertEqual(observation["status"], "NOT_AVAILABLE")
        self.assertNotIn("peak_rss_bytes", observation)


if __name__ == "__main__":
    unittest.main()

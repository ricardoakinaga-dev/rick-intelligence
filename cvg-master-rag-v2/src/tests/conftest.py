"""
Test configuration and shared fixtures for pytest.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, '.')


# ── Mock Embedding ───────────────────────────────────────────────────────────

def _mock_embedding(text: str) -> list[float]:
    """Return a deterministic mock embedding for any text."""
    # 1536-dim zero vector for simplicity
    return [0.0] * 1536


# ── Pytest Fixtures ─────────────────────────────────────────────────────────

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "requires_api: mark test as requiring external API")
    config.addinivalue_line("markers", "integration: mark test as integration test")


# Use @pytest.mark.unit for tests that should run without API key
# Use @pytest.mark.integration for tests that require API key (they'll be skipped if no key)

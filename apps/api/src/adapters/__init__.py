"""Centralized legacy-adapter boundary.

ONLY files under apps/api/src/adapters/legacy/ may import preserved legacy
paths (cvg-master-rag-v2, rick-professor, modulo-redis-locker). Routes and
services must use the adapter protocols below. Enforced by import-boundary test.
"""

from __future__ import annotations

ALLOWLIST_DIR = "apps/api/src/adapters/legacy"
ALLOWED_LEGACY_PREFIXES = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")

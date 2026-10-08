"""AUD07-01 reproduction: A02 - archived collection stays searchable.

Run from the repository root:

    python3 docs/reports/evidence/auditoria-2026-10-07/repro/repro_a02_archive_search.py

Exit code 0 means the defect was reproduced (baseline evidence). Exit code 1
means the search correctly returned no evidence after archiving. Exit code 2
means the harness itself could not run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
for _pkg in (
    "contracts", "authorization", "identity", "observability", "knowledge",
    "ingestion", "retrieval", "providers", "locking", "professor", "evidence",
    "decision", "storage", "jobs",
):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

os.environ.setdefault("RICK_API_ROOT_RETRIEVAL", "1")


def main() -> int:
    from fastapi.testclient import TestClient

    from app import create_app
    from core.config import ApiSettings

    try:
        app = create_app(ApiSettings.from_env())
    except Exception as exc:  # pragma: no cover - harness failure
        print(json.dumps({"harness_error": str(exc)}, indent=2))
        return 2

    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123", "tenant_id": "default"},
        )
        if login.status_code != 200:
            print(json.dumps({"harness_error": "login failed", "status": login.status_code}, indent=2))
            return 2

        before = client.post(
            "/api/v1/search",
            json={"query": "higiene ordenha", "collection_id": "rag_phase0", "top_k": 3},
        )
        if before.status_code != 200:
            print(json.dumps({"harness_error": "baseline search failed", "status": before.status_code,
                              "body": before.text[:400]}, indent=2))
            return 2

        archive = client.post("/api/v1/collections/rag_phase0/archive")
        scoped = client.post(
            "/api/v1/search",
            json={"query": "higiene ordenha", "collection_id": "rag_phase0", "top_k": 3},
        )
        glob = client.post("/api/v1/search", json={"query": "higiene ordenha", "top_k": 3})

        scoped_items = len(scoped.json().get("items", [])) if scoped.status_code == 200 else None
        glob_items = len(glob.json().get("items", [])) if glob.status_code == 200 else None
        still_searchable = bool(scoped_items) or bool(glob_items)

        print(json.dumps({
            "finding": "A02",
            "search_before": [before.status_code, len(before.json().get("items", []))],
            "archive": [archive.status_code, archive.json().get("status") if archive.status_code == 200 else None],
            "search_after_scoped": [scoped.status_code, scoped_items],
            "search_after_global": [glob.status_code, glob_items],
            "still_searchable_after_archive": still_searchable,
        }, indent=2))
    return 0 if still_searchable else 1


if __name__ == "__main__":
    raise SystemExit(main())

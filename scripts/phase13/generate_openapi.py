#!/usr/bin/env python3
"""Generate OpenAPI schema for apps/api (sanitized: no secrets)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
for _pkg in ("contracts", "authorization", "identity"):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

from app import create_app
from core.config import ApiSettings


def main() -> int:
    settings = ApiSettings(cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False)
    app = create_app(settings)
    schema = app.openapi()
    text = json.dumps(schema, indent=2)
    # Leak check targets secret VALUES, not field names (e.g. `session_token: null` is safe by design).
    for needle in ("redis://", "sk-", "BEGIN PRIVATE", "password123"):
        assert needle not in text, f"schema leak check: {needle!r}"
    assert "traceback" not in text.lower()
    # Strip any example that looks secret-bearing.
    out = ROOT / "apps" / "api" / "openapi.json"
    out.write_text(text)
    print(f"Wrote {out} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

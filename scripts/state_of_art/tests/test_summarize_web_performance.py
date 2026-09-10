from __future__ import annotations

import json
import sys

import pytest

from scripts.state_of_art import summarize_web_performance


def test_performance_input_rejects_duplicate_keys(tmp_path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for route in summarize_web_performance.EXPECTED_ROUTES:
        for project in summarize_web_performance.EXPECTED_PROJECTS:
            payload = {
                "measured": {"lcp": 100, "cls": 0, "shifts": []},
                "test": "smoke",
                "route": route,
                "viewport": {"width": 1280, "height": 720},
                "assertion": {
                    "lcp_positive": True,
                    "lcp_within_budget": True,
                    "cls_within_budget": True,
                },
            }
            (input_dir / f"{route}-{project}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
    (input_dir / "login-mobile.json").write_text(
        '{"measured":{"lcp":100,"cls":0,"shifts":[]},"test":"smoke",'
        '"test":"forged","route":"login","viewport":{"width":1280,"height":720},'
        '"assertion":{"lcp_positive":true,"lcp_within_budget":true,"cls_within_budget":true}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["summarize_web_performance.py", "--input", str(input_dir), "--output", str(tmp_path / "out.json")],
    )

    with pytest.raises(json.JSONDecodeError, match="duplicate JSON object key"):
        summarize_web_performance.main()

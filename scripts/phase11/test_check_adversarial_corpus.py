from __future__ import annotations

import json

from scripts.phase11 import check_adversarial_corpus as checker


def test_corpus_parser_rejects_duplicate_fields(tmp_path, monkeypatch, capsys) -> None:
    categories = sorted(checker.REQUIRED_CATEGORIES)
    lines = [
        '{"id":"case-0","id":"forged","category":"direct_prompt_injection","text":"safe","expected":"reject"}'
    ]
    lines.extend(
        json.dumps({"id": f"case-{index}", "category": category, "text": "safe", "expected": "reject"})
        for index, category in enumerate(categories[1:], 1)
    )
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(checker, "CORPUS", corpus)

    assert checker.main() == 1
    assert "invalid JSON" in capsys.readouterr().err

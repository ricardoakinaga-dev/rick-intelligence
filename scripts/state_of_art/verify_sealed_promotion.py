#!/usr/bin/env python3
"""Verify an independently sealed promotion packet against one runtime packet.

The integrated verifier creates observations; an independent authority seals a
packet after reviewing those observations.  This command performs the final
read-only binding without rerunning the runtime lanes, so timestamps and
external service results cannot drift between observation and authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.state_of_art.json_boundary import load_json
    from scripts.state_of_art import packet_seal, promotion_engine
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover
    from json_boundary import load_json
    import packet_seal
    import promotion_engine
    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
QUALITY_BAR = "docs/reports/current-triple-aaa-quality-bar-v1.json"
SOURCE_PROMPT = "docs/prompts/triple-aaa-runtime-closure-2026-09-10.txt"
PACKET_SCHEMA = promotion_engine.PROMOTION_PACKET_SCHEMA


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError, RuntimeError):
        return None


def _manifest_artifact_hash(root: Path) -> str | None:
    try:
        payload = load_json(root / "docs/progress/release-evidence.json")
    except (OSError, UnicodeDecodeError, ValueError, TypeError, RecursionError):
        return None
    binding = payload.get("commit_binding") if isinstance(payload, dict) else None
    value = binding.get("artifact_set_sha256") if isinstance(binding, dict) else None
    return value if isinstance(value, str) and value else None


def verify(
    *,
    packet_path: Path,
    verifier_packet_path: Path,
    trust_store_path: Path,
    seal_reference: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return the promotion-engine result for the exact sealed observation set."""

    packet = load_json(packet_path)
    verifier_packet = load_json(verifier_packet_path)
    if not isinstance(packet, dict):
        raise ValueError("sealed packet must be a JSON object")
    if not isinstance(verifier_packet, dict):
        raise ValueError("verifier packet must be a JSON object")
    if verifier_packet.get("schema_version") != PACKET_SCHEMA:
        raise ValueError("verifier packet has an unsupported schema")
    results = verifier_packet.get("results")
    if not isinstance(results, list):
        raise ValueError("verifier packet has no observation results")
    trust_store = packet_seal.load_trust_store(trust_store_path)
    valid, seal_errors = packet_seal.verify_seal(
        packet,
        trusted_public_keys=trust_store,
        expected_payload_schema=PACKET_SCHEMA,
    )
    if not valid:
        raise ValueError("sealed packet is invalid: " + "; ".join(seal_errors))
    if seal_reference is not None:
        seal = packet.get("seal")
        if not isinstance(seal, dict) or seal.get("immutable_reference") != seal_reference:
            raise ValueError("sealed packet immutable reference does not match the requested reference")

    checkout = dict(capture_checkout(root))
    checkout["artifact_set_sha256"] = _manifest_artifact_hash(root)
    checkout["quality_bar_sha256"] = _sha256_file(root / QUALITY_BAR)
    checkout["source_prompt_sha256"] = _sha256_file(root / SOURCE_PROMPT)
    return promotion_engine.evaluate(
        results,
        packet=packet,
        checkout=checkout,
        trusted_public_keys=trust_store,
        evidence_root=root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, help="independently sealed packet")
    parser.add_argument("--verifier-packet", required=True, help="same-run integrated verifier packet")
    parser.add_argument("--trust-store", required=True, help="JSON Ed25519 trust store")
    parser.add_argument("--seal-reference")
    parser.add_argument("--output", default=".runtime/final-promotion.json")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = verify(
            packet_path=Path(args.packet),
            verifier_packet_path=Path(args.verifier_packet),
            trust_store_path=Path(args.trust_store),
            seal_reference=args.seal_reference,
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        failure = {"schema_version": "state-of-art-final-promotion.v1", "status": "FAIL", "exit_status": 1, "error": f"{type(exc).__name__}: {exc}"}
        try:
            output = (ROOT / args.output).resolve()
            output.relative_to(ROOT.resolve())
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(failure, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        except (OSError, ValueError):
            pass
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return promotion_engine.EXIT_FAILED
    status = "PASS" if result.get("promotion_allowed") is True else (
        "BLOCKED_EXTERNAL" if result.get("exit_code") == promotion_engine.EXIT_BLOCKED_EXTERNAL else "FAIL"
    )
    summary = {
        "schema_version": "state-of-art-final-promotion.v1",
        "status": status,
        "exit_status": int(result["exit_code"]),
        "classification": result.get("classification"),
        "promotion_allowed": result.get("promotion_allowed"),
        "rejection_codes": result.get("rejection_codes", []),
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": result.get("classification"),
                "promotion_allowed": result.get("promotion_allowed"),
                "exit_code": result.get("exit_code"),
                "rejection_codes": result.get("rejection_codes", []),
            },
            sort_keys=True,
        )
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())

"""Separate current release output from the immutable restored control input."""

from pathlib import Path


CURRENT_RELEASE_EVIDENCE = ".runtime/release/release-evidence.json"
HISTORICAL_RELEASE_EVIDENCE = "docs/progress/release-evidence.json"


def release_output_path(root: Path, output: str) -> Path:
    """Reject historical destinations and filesystem aliases before generation."""

    destination = (root / output).resolve()
    historical = (root / HISTORICAL_RELEASE_EVIDENCE).resolve()
    if destination == historical or (
        destination.exists() and historical.exists() and destination.samefile(historical)
    ):
        raise ValueError("release output cannot overwrite the historical control input")
    return destination

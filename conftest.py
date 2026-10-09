"""Discover canonical sources for every pytest invocation (AUD07-21).

Paths are absolute and come from the same manifest as the Make/CI runners.
This also works when pytest is launched outside the repository using absolute
test paths. No application, service or environment variable is initialized.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scripts.phase13.pyenv import source_paths

for source in reversed([ROOT / "apps", *source_paths()]):
    path = str(source)
    if path not in sys.path:
        sys.path.insert(0, path)

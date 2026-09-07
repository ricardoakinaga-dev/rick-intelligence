"""Import the package under test and its owned shared contract dependency."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for package in ("locking", "contracts"):
    source = ROOT / "packages" / package / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

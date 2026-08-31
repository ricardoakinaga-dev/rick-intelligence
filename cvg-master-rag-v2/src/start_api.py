import os
from pathlib import Path

import uvicorn


def _load_local_env(env_path: Path | None = None) -> None:
    resolved_path = env_path or (Path(__file__).resolve().parent / ".env")
    if not resolved_path.exists():
        return

    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


def main() -> None:
    _load_local_env()
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, log_level="error")


if __name__ == "__main__":
    main()

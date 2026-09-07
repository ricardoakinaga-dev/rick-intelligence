"""Uvicorn entrypoint: `python -m main` or `uvicorn main:app`. Prints required deps."""

from app import create_app
from core.config import ApiSettings
import os

settings = ApiSettings.from_env()
app = create_app(settings)

if __name__ == "__main__":
    import uvicorn

    print(f"RICK API dev: env={settings.environment} legacy_adapters={settings.use_legacy_adapters}")
    print("Optional deps (only when RICK_API_USE_LEGACY=1): Qdrant, Redis, provider credentials.")
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("RICK_API_PORT", "8000")))

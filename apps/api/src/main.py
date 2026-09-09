"""Uvicorn entrypoint with explicit production composition loading."""

from app import create_app
from core.config import ApiSettings
from services.external_composition import load_external_providers
import os

settings = ApiSettings.from_env()


def create_entrypoint_app(settings: ApiSettings):
    """Build the app through the canonical external graph in production."""

    if settings.environment == "production":
        return create_app(settings, load_external_providers(settings))
    return create_app(settings)


app = create_entrypoint_app(settings)

if __name__ == "__main__":
    import uvicorn

    print(f"RICK API: env={settings.environment} legacy_adapters={settings.use_legacy_adapters}")
    print("Production composition: RICK_API_COMPOSITION=module:factory")
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("RICK_API_PORT", "8000")))

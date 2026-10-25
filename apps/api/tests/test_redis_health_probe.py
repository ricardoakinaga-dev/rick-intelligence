from types import SimpleNamespace

from core.config import ApiSettings
from services.external_composition import _redis_health_probe


def test_dev_and_test_use_liveness_while_production_requires_readiness():
    limiter = SimpleNamespace(health_check=lambda: True, readiness_check=lambda: False)
    for environment in ("test", "dev", "local"):
        probe = _redis_health_probe(ApiSettings(environment=environment), limiter)
        assert probe() is True
    for environment in ("production",):
        probe = _redis_health_probe(ApiSettings(environment=environment), limiter)
        assert probe() is False

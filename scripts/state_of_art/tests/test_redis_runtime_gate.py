from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_native_gate_forwards_private_pki_and_cannot_disable_verification(monkeypatch):
    import rick_locking
    from scripts.phase11 import redis_runtime_gate

    captured = {}
    def settings(**kwargs):
        captured.update(kwargs)
        raise ValueError("stop before any connection")

    monkeypatch.setattr(rick_locking, "RedisSettings", settings)
    monkeypatch.setenv("RICK_REDIS_TLS_CA_FILE", "/private/ca.crt")
    monkeypatch.setenv("RICK_REDIS_TLS_CERT_FILE", "/private/client.crt")
    monkeypatch.setenv("RICK_REDIS_TLS_KEY_FILE", "/private/client.key")
    monkeypatch.setenv("RICK_REDIS_VERIFY_TLS", "false")
    await redis_runtime_gate._run_checks(
        "rediss://default:test-password@localhost/0", require_tls=True, allow_nonlocal=False)
    assert captured["tls_ca_file"] == "/private/ca.crt"
    assert captured["tls_cert_file"] == "/private/client.crt"
    assert captured["tls_key_file"] == "/private/client.key"
    assert captured["verify_tls"] is True
    assert captured["require_tls"] is True


def test_owned_tls_fault_cannot_pause_a_foreign_container(monkeypatch):
    import asyncio
    from scripts.phase11 import local_tls_bootstrap as lab
    from scripts.phase11 import redis_fault_harness as fault

    monkeypatch.setenv("RICK_FORMAL_LAB_AUTHORIZED", "1")
    monkeypatch.setenv("RICK_REDIS_CONTAINER", "shared-dev-redis")
    monkeypatch.setenv("RICK_TLS_LAB_RUN_ID", "owned-run")
    commands = []
    def inspect(args, **kwargs):
        from types import SimpleNamespace
        commands.append(args)
        return SimpleNamespace(stdout='[{"Config":{"Labels":{"rick.phase3.owned-run":"another-run"}}}]')
    async def forbidden():
        pytest.fail("must reject ownership before fault injection")

    monkeypatch.setattr(lab.subprocess, "run", inspect)
    monkeypatch.setattr(fault, "_exercise", forbidden)
    with pytest.raises(ValueError, match="nonowned"):
        asyncio.run(lab.fault_only())
    assert len(commands) == 1 and "inspect" in commands[0]


def test_redis_runtime_gate_declares_recovery_and_fault_authority() -> None:
    source = (Path(__file__).parents[2] / "phase11" / "redis_runtime_gate.py").read_text(
        encoding="utf-8"
    )

    for case in ("heartbeat-renewal", "reconnect-recovery", "circuit-breaker-recovery"):
        assert case in source
    assert "RICK_REDIS_FAULT_HARNESS" in source

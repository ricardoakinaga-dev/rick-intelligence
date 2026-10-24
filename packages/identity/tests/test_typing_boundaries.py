"""Runtime contracts retained by the bounded identity typing changes."""

from datetime import datetime, timezone
from decimal import Decimal

import jwt
import pytest

from rick_identity.oidc import OIDCError, OIDCSettings, OIDCVerifier

from rick_identity.postgres import _db_float, _db_int, _epoch
from rick_identity.snapshots import bounded_text, known_role, valid_authorization_snapshot


@pytest.mark.parametrize("value", [None, True, 42, [], {}, object()])
def test_role_guard_rejects_non_text_without_coercion(value):
    assert bounded_text(value, 64) is False
    assert known_role(value) is False
    assert valid_authorization_snapshot({"role": value}) is False


@pytest.mark.parametrize("value", ["", " ", "unknown", "VETERINARIAN\x00", "v" * 65])
def test_role_guard_preserves_invalid_text_rejection(value):
    assert known_role(value) is False
    assert valid_authorization_snapshot({"role": value}) is False


@pytest.mark.parametrize("role", ["VETERINARIAN", "veterinarian", " veterinarian "])
def test_role_guard_preserves_legacy_and_canonical_labels(role):
    assert known_role(role) is True
    assert valid_authorization_snapshot({"role": role}) is True


@pytest.mark.parametrize("value", [True, 2, 2.75, "2", b"2", bytearray(b"2"), memoryview(b"2"), Decimal("2.75")])
def test_db_numeric_boundary_preserves_builtin_coercions(value):
    assert _db_int(value) == int(value)
    assert _db_float(value) == float(value)


@pytest.mark.parametrize("value, error", [(None, TypeError), (object(), TypeError), ([], TypeError), ("invalid", ValueError)])
def test_db_numeric_boundary_does_not_cast_away_runtime_failures(value, error):
    with pytest.raises(error):
        _db_int(value)
    with pytest.raises(error):
        _db_float(value)
    assert _epoch(value) is None


def test_epoch_preserves_datetime_path():
    value = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert _epoch(value) == value.timestamp()


def test_default_jwt_decoder_still_rejects_invalid_resolver_key():
    settings = OIDCSettings(issuer="https://issuer.example", audience="client", algorithms=("HS256",))
    token = jwt.encode(
        {"sub": "subject", "iss": settings.issuer, "aud": "client", "exp": 4_000_000_000},
        "synthetic-signing-secret-at-least-32-bytes", algorithm="HS256", headers={"kid": "key"},
    )
    verifier = OIDCVerifier(settings, key_resolver=lambda _kid: object())
    with pytest.raises(OIDCError) as error:
        verifier.verify(token)
    assert error.value.code == "invalid_token"


def test_custom_decoder_keeps_opaque_key_and_exact_verification_arguments():
    settings = OIDCSettings(issuer="https://issuer.example", audience="client", algorithms=("HS256",))
    token = jwt.encode({}, "synthetic-signing-secret-at-least-32-bytes", algorithm="HS256", headers={"kid": "key"})
    opaque_key = object()
    observed = {}
    claims = {"sub": "subject", "iss": settings.issuer, "aud": "client", "exp": 4_000_000_000}

    def decoder(value, **kwargs):
        assert value == token
        observed.update(kwargs)
        return claims

    verifier = OIDCVerifier(settings, key_resolver=lambda _kid: opaque_key, decoder=decoder)
    assert verifier.verify(token) == claims
    assert observed == {
        "key": opaque_key, "algorithms": ["HS256"], "audience": "client",
        "issuer": settings.issuer, "options": {"require": ["sub", "iss", "aud", "exp"]},
        "leeway": 30,
    }

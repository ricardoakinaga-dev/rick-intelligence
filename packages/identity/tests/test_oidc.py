from __future__ import annotations

import time

import jwt
import pytest

from rick_identity import (
    OIDCError,
    OIDCIdentityProvider,
    OIDCSettings,
    OIDCVerifier,
)


def _token(**overrides: object) -> str:
    claims = {
        "sub": "subject-1",
        "iss": "https://issuer.example",
        "aud": "rick-client",
        "exp": int(time.time()) + 600,
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "email": "user@example.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, "test-only-oidc-secret", algorithm="HS256", headers={"kid": "key-1"})


def _verifier() -> OIDCVerifier:
    return OIDCVerifier(
        OIDCSettings(
            issuer="https://issuer.example",
            audience="rick-client",
            algorithms=("HS256",),
        ),
        key_resolver=lambda kid: "test-only-oidc-secret" if kid == "key-1" else None,
    )


def test_verifier_requires_signature_issuer_audience_expiry_and_kid() -> None:
    verifier = _verifier()
    assert verifier.verify(_token())["sub"] == "subject-1"
    for token, code in (
        (_token(iss="https://other.example"), "issuer_mismatch"),
        (_token(aud="other-client"), "audience_mismatch"),
        (_token(exp=int(time.time()) - 600), "expired_token"),
    ):
        with pytest.raises(OIDCError) as error:
            verifier.verify(token)
        assert error.value.code == code

    with pytest.raises(OIDCError) as error:
        verifier.verify(jwt.encode({"sub": "subject-1"}, "test-only-oidc-secret", algorithm="HS256"))
    assert error.value.code == "key_not_found"


def test_identity_provider_requires_authoritative_membership_and_never_defaults_tenant() -> None:
    memberships = {
        ("subject-1", "tenant-a"): {
            "subject": "subject-1",
            "user_id": "user-1",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "role": "VETERINARIAN",
            "authorized_collection_ids": ["rag_phase0"],
        }
    }
    provider = OIDCIdentityProvider(
        _verifier(),
        membership_resolver=lambda subject, _claims, tenant: memberships.get((subject, tenant)),
    )
    snapshot = provider.validate_token(_token())
    assert snapshot.authenticated
    assert snapshot.user_id == "user-1"
    assert snapshot.tenant_id == "tenant-a"
    assert snapshot.permissions == [
        "cases.feedback", "cases.manage", "cases.read", "chat.query",
        "collections.read", "history.read", "sources.read",
    ]

    assert not provider.validate_token(_token(tenant_id="tenant-b")).authenticated
    assert not provider.validate_token(_token(workspace_id=None, tenant_id=None)).authenticated


def test_default_oidc_algorithms_are_asymmetric() -> None:
    settings = OIDCSettings(issuer="https://issuer.example", audience="rick-client")
    assert settings.algorithms == ("RS256", "ES256")

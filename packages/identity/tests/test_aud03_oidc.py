import time

import jwt
import pytest

from rick_identity import OIDCIdentityProvider, OIDCSettings, OIDCVerifier, PostgresUserStore


def membership():
    return {"subject": "subject", "user_id": "u", "tenant_id": "t", "workspace_id": "w",
            "role": "VETERINARIAN", "status": "active", "membership_status": "active",
            "authorized_collection_ids": [], "permission_overrides": {"add": [], "remove": []}}


def validate(record):
    secret = "synthetic-aud03-oidc-secret-32-bytes"
    token = jwt.encode({"iss": "https://issuer.example", "aud": "test", "sub": "subject",
                        "exp": time.time() + 600, "tenant_id": "t", "workspace_id": "foreign",
                        "role": "PLATFORM_ADMIN"}, secret, algorithm="HS256", headers={"kid": "test"})
    verifier = OIDCVerifier(OIDCSettings(issuer="https://issuer.example", audience="test", algorithms=("HS256",)),
                            key_resolver=lambda kid: secret)
    return OIDCIdentityProvider(verifier, membership_resolver=lambda *args: record).validate_token(token)


@pytest.mark.parametrize("key,value", [("status", "disabled"), ("membership_status", "inactive"),
    ("subject", "other"), ("tenant_id", "foreign"), ("workspace_id", None), ("role", None),
    ("role", "unknown"), ("user_id", None), ("authorized_collection_ids", "*"),
    ("permission_overrides", {"remove": "chat.query"})])
def test_invalid_authority_is_anonymous_even_with_admin_claims(key, value):
    record = membership()
    record[key] = value
    snapshot = validate(record)
    assert not snapshot.authenticated
    assert snapshot.permissions == []
    assert snapshot.allowed_collection_ids == []


@pytest.mark.parametrize("key", ["subject", "user_id", "tenant_id", "workspace_id", "role", "status", "membership_status", "authorized_collection_ids"])
def test_missing_authority_fields_cannot_be_completed_by_claims(key):
    record = membership()
    record.pop(key)
    assert not validate(record).authenticated


@pytest.mark.parametrize("grants", [[], ["allowed"], ["*"]])
def test_active_authority_controls_scope_even_with_foreign_workspace_admin_claims(grants):
    record = membership()
    record["authorized_collection_ids"] = grants
    snapshot = validate(record)
    assert snapshot.authenticated
    assert snapshot.canonical_role == "VETERINARIAN"
    assert snapshot.workspace_id == "w"
    assert snapshot.allowed_collection_ids == grants
    assert "*" not in snapshot.permissions


def test_postgres_membership_row_retains_active_status_and_empty_grants():
    record = PostgresUserStore._record({**membership(), "external_subject": "subject"})
    assert record is not None
    # The resolver maps the database's external_subject to its subject binding.
    record["subject"] = record["external_subject"]
    assert validate(record).authenticated
    record["membership_status"] = "disabled"
    assert not validate(record).authenticated


def test_resolver_failure_cannot_produce_authenticated_session():
    def unavailable(*args):
        raise RuntimeError("synthetic authority failure")

    verifier = OIDCVerifier(OIDCSettings(issuer="https://issuer.example", audience="test", algorithms=("HS256",)),
                            key_resolver=lambda kid: "synthetic-aud03-oidc-secret-32-bytes",
                            decoder=lambda *args, **kwargs: {"iss": "https://issuer.example", "sub": "subject",
                                                            "exp": time.time() + 600, "tenant_id": "t"})
    token = jwt.encode({}, "synthetic-aud03-oidc-secret-32-bytes", algorithm="HS256", headers={"kid": "test"})
    assert not OIDCIdentityProvider(verifier, membership_resolver=unavailable).validate_token(token).authenticated

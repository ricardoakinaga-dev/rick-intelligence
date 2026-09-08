"""Canonical identity package — user/session lifecycle source of truth."""

from rick_identity.passwords import hash_password, verify_password_hash
from rick_identity.protocols import CredentialVerifier, IdentityProvider, SessionStore, UserStore
from rick_identity.provider import IdentityError, IdentityProviderImpl, Pbkdf2Verifier, PlainTestVerifier
from rick_identity.stores import InMemorySessionStore, InMemoryUserStore
from rick_identity.oidc import (
    OIDCConfigurationError,
    OIDCError,
    OIDCIdentityProvider,
    OIDCSettings,
    OIDCVerifier,
)
from rick_identity.postgres import PostgresIdentityError, PostgresRecoveryStore, PostgresSessionStore, PostgresUserStore

__all__ = [
    "CredentialVerifier", "IdentityProvider", "SessionStore", "UserStore",
    "IdentityError", "IdentityProviderImpl", "Pbkdf2Verifier", "PlainTestVerifier",
    "InMemorySessionStore", "InMemoryUserStore",
    "OIDCConfigurationError", "OIDCError", "OIDCIdentityProvider",
    "OIDCSettings", "OIDCVerifier",
    "PostgresIdentityError", "PostgresRecoveryStore", "PostgresSessionStore", "PostgresUserStore",
    "hash_password", "verify_password_hash",
]

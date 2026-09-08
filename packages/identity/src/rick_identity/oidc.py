"""Fail-closed OIDC token verification and session resolution.

The adapter deliberately owns verification only. Discovery, JWKS fetching,
membership lookup, and token delivery are injected by the composition root so
importing this module never performs network I/O or reads ambient settings.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
import time

from rick_authorization import (
    AUTHORIZATION_SNAPSHOT_VERSION,
    allowed_collection_ids_for_user,
    canonical_role,
    legacy_role_label,
    normalize_permission_overrides,
    permissions_for_role,
)


class OIDCError(Exception):
    """Safe OIDC boundary failure identified by a stable code."""

    _CODES = frozenset({
        "invalid_configuration", "invalid_token", "key_not_found",
        "issuer_mismatch", "audience_mismatch", "expired_token",
        "membership_denied",
    })

    def __init__(self, code: str = "invalid_token") -> None:
        self.code = code if code in self._CODES else "invalid_token"
        super().__init__(self.code)


class OIDCConfigurationError(OIDCError, ValueError):
    def __init__(self) -> None:
        super().__init__("invalid_configuration")


@dataclass(frozen=True, slots=True)
class OIDCSettings:
    """Verification policy supplied by the deployment owner."""

    issuer: str
    audience: str | tuple[str, ...]
    algorithms: tuple[str, ...] = ("RS256", "ES256")
    clock_skew_seconds: int = 30
    max_token_chars: int = 16_384

    def __post_init__(self) -> None:
        # Asymmetric algorithms are the safe default. HS256 is accepted only
        # when a deployment explicitly supplies it and an injected resolver
        # owns the shared secret; it is never enabled by the default tuple.
        valid_algorithms = {"HS256", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
        valid_audience = (
            isinstance(self.audience, str) and bool(self.audience.strip())
        ) or (
            isinstance(self.audience, tuple)
            and bool(self.audience)
            and all(isinstance(item, str) and bool(item.strip()) for item in self.audience)
        )
        if (
            not isinstance(self.issuer, str)
            or not self.issuer.strip()
            or len(self.issuer) > 512
            or any(ord(char) < 0x21 or ord(char) == 0x7F for char in self.issuer)
            or not valid_audience
            or not isinstance(self.algorithms, tuple)
            or not self.algorithms
            or any(algorithm not in valid_algorithms for algorithm in self.algorithms)
            or isinstance(self.clock_skew_seconds, bool)
            or not isinstance(self.clock_skew_seconds, int)
            or not 0 <= self.clock_skew_seconds <= 300
            or isinstance(self.max_token_chars, bool)
            or not isinstance(self.max_token_chars, int)
            or not 256 <= self.max_token_chars <= 1_000_000
        ):
            raise OIDCConfigurationError()


def _safe_claim_text(claims: Mapping[str, object], name: str, *, maximum: int = 512) -> str | None:
    value = claims.get(name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


def _claim_list(claims: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = claims.get(name)
    if isinstance(value, str):
        values: Sequence[object] = (value,)
    elif isinstance(value, (list, tuple, set)):
        values = tuple(value)
    else:
        return ()
    return tuple(dict.fromkeys(
        item.strip() for item in values
        if isinstance(item, str) and item.strip() and len(item.strip()) <= 128
    ))


class OIDCVerifier:
    """Verify a signed OIDC JWT using an injected key resolver."""

    def __init__(
        self,
        settings: OIDCSettings,
        *,
        key_resolver: Callable[[str], object | None],
        decoder: Callable[..., Mapping[str, object]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(settings, OIDCSettings) or not callable(key_resolver) or not callable(clock):
            raise OIDCConfigurationError()
        self.settings = settings
        self._key_resolver = key_resolver
        self._clock = clock
        if decoder is None:
            try:
                import jwt
            except ImportError as exc:  # pragma: no cover - deployment dependency boundary
                raise OIDCConfigurationError() from exc
            decoder = jwt.decode
        if not callable(decoder):
            raise OIDCConfigurationError()
        self._decoder = decoder

    def verify(self, token: str) -> dict[str, object]:
        if (
            not isinstance(token, str)
            or not token.strip()
            or len(token) > self.settings.max_token_chars
            or any(ord(char) < 0x21 or ord(char) == 0x7F for char in token)
        ):
            raise OIDCError()
        try:
            import jwt

            header = jwt.get_unverified_header(token)
            if not isinstance(header, Mapping):
                raise OIDCError()
            algorithm = header.get("alg")
            kid = header.get("kid")
            if not isinstance(algorithm, str) or algorithm not in self.settings.algorithms:
                raise OIDCError()
            if not isinstance(kid, str) or not kid.strip() or len(kid) > 256:
                raise OIDCError("key_not_found")
            key = self._key_resolver(kid)
            if key is None:
                raise OIDCError("key_not_found")
            claims = self._decoder(
                token,
                key=key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                options={"require": ["sub", "iss", "aud", "exp"]},
                leeway=self.settings.clock_skew_seconds,
            )
        except OIDCError:
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "expired" in name:
                raise OIDCError("expired_token") from None
            if "issuer" in name:
                raise OIDCError("issuer_mismatch") from None
            if "audience" in name:
                raise OIDCError("audience_mismatch") from None
            raise OIDCError() from None
        if not isinstance(claims, Mapping):
            raise OIDCError()
        subject = _safe_claim_text(claims, "sub", maximum=256)
        issuer = _safe_claim_text(claims, "iss", maximum=512)
        if subject is None or issuer != self.settings.issuer:
            raise OIDCError("issuer_mismatch" if issuer != self.settings.issuer else "invalid_token")
        expiry = claims.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(float(expiry)):
            raise OIDCError()
        if float(expiry) + self.settings.clock_skew_seconds < float(self._clock()):
            raise OIDCError("expired_token")
        return {str(key): value for key, value in claims.items() if isinstance(key, str)}


MembershipResolver = Callable[[str, Mapping[str, object], str], Mapping[str, object] | None]


class OIDCIdentityProvider:
    """Bearer-token identity facade for an externally managed OIDC session."""

    production_safe = True

    def __init__(
        self,
        verifier: OIDCVerifier,
        *,
        membership_resolver: MembershipResolver,
        tenant_claim: str = "tenant_id",
        workspace_claim: str = "workspace_id",
        health_check: Callable[[], bool] | None = None,
    ) -> None:
        if not isinstance(verifier, OIDCVerifier) or not callable(membership_resolver) or (
            health_check is not None and not callable(health_check)
        ):
            raise OIDCConfigurationError()
        if not isinstance(tenant_claim, str) or not tenant_claim.strip() or len(tenant_claim) > 128:
            raise OIDCConfigurationError()
        if not isinstance(workspace_claim, str) or not workspace_claim.strip() or len(workspace_claim) > 128:
            raise OIDCConfigurationError()
        self.verifier = verifier
        self._membership_resolver = membership_resolver
        self._tenant_claim = tenant_claim
        self._workspace_claim = workspace_claim
        self._health_check = health_check

    def health_check(self) -> bool:
        """Use an injected IdP probe; configuration alone is not liveness."""

        if self._health_check is None:
            return False
        try:
            return self._health_check() is True
        except Exception:
            return False

    def validate_token(self, token: str | None):
        from rick_contracts.security import SessionSnapshot

        if not token:
            return SessionSnapshot(authenticated=False, session_state="anonymous")
        try:
            claims = self.verifier.verify(token)
            subject = _safe_claim_text(claims, "sub", maximum=256)
            tenant = _safe_claim_text(claims, self._tenant_claim, maximum=128)
            if subject is None or tenant is None:
                raise OIDCError("membership_denied")
            membership = self._membership_resolver(subject, claims, tenant)
            if not isinstance(membership, Mapping):
                raise OIDCError("membership_denied")
            if membership.get("subject") not in (None, subject) or membership.get("tenant_id") != tenant:
                raise OIDCError("membership_denied")
            workspace = _safe_claim_text(membership, "workspace_id", maximum=128)
            if workspace is None:
                workspace = _safe_claim_text(claims, self._workspace_claim, maximum=128)
            if workspace is None:
                raise OIDCError("membership_denied")
            role = canonical_role(membership.get("role") or claims.get("role"))
            permissions = permissions_for_role(
                role, normalize_permission_overrides(membership.get("permission_overrides"))
            )
            email = _safe_claim_text(membership, "email", maximum=256) or _safe_claim_text(claims, "email", maximum=256)
            user_id = _safe_claim_text(membership, "user_id", maximum=256) or subject
            allowed = allowed_collection_ids_for_user({
                "role": role,
                "authorized_collection_ids": membership.get("authorized_collection_ids", []),
            })
            return SessionSnapshot(
                authenticated=True,
                session_state="active",
                user_id=user_id,
                email=email,
                role=legacy_role_label(role),
                canonical_role=role,
                permissions=permissions,
                authorization_snapshot_version=AUTHORIZATION_SNAPSHOT_VERSION,
                authorization_state="AUTHORITATIVE",
                tenant_id=tenant,
                workspace_id=workspace,
                session_id=f"oidc:{subject}",
                allowed_collection_ids=allowed,
            )
        except OIDCError:
            return SessionSnapshot(authenticated=False, session_state="anonymous")

    def logout(self, _token: str | None) -> None:
        """OIDC logout is owned by the provider callback/session broker."""

    def login(self, **_kwargs: object) -> dict[str, object]:
        raise OIDCError("invalid_configuration")


__all__ = [
    "MembershipResolver", "OIDCConfigurationError", "OIDCError",
    "OIDCIdentityProvider", "OIDCSettings", "OIDCVerifier",
]

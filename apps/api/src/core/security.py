"""Security primitives: public allowlist, proxy trust, cookie/bearer precedence, response headers."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Iterable, Mapping

# Default-deny: everything not listed here requires an authenticated session.
PUBLIC_ALLOWLIST = frozenset(
    {
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/recovery"),
        ("POST", "/api/v1/auth/request-password-reset"),
        ("POST", "/api/v1/auth/confirm-password-reset"),
    }
)

# Compatibility endpoints are public only in the sense that they use API-key auth
# instead of cookie sessions; anonymous requests without a valid key are 401.
COMPAT_API_KEY_PATHS = frozenset({("GET", "/v1/models"), ("POST", "/v1/chat/completions")})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def constant_time_compare(presented: str, expected: str) -> bool:
    if not presented or not expected:
        return False
    a = presented.encode("utf-8")
    b = expected.encode("utf-8")
    return len(a) == len(b) and hmac.compare_digest(a, b)


def resolve_auth_precedence(cookie_token: str | None, bearer_token: str | None) -> tuple[str | None, str]:
    """Cookie wins over Bearer for browser safety.

    A malicious Bearer must never override an authenticated browser cookie.
    Bearer compatibility tokens apply only when no session cookie is present
    (compat/external domains). Returns (effective_token, source).
    """
    if cookie_token:
        return cookie_token, "cookie"
    if bearer_token:
        return bearer_token, "bearer"
    return None, "none"


def resolve_session_cookie(
    cookies: Mapping[str, str],
    configured_name: str,
    *,
    captured_compat_cookie: str | None = None,
) -> str | None:
    """Resolve the configured cookie before the legacy generic cookie.

    A few local clients historically sent ``session_cookie``.  It remains a
    compatibility fallback only when the configured cookie is absent; it can
    never override an explicitly configured session cookie.  Every consumer
    (auth, logout/revoke, and CSRF) must use this same precedence.
    """
    configured = cookies.get(configured_name)
    if configured:
        return configured
    if configured_name == "session_cookie":
        return configured
    return captured_compat_cookie or cookies.get("session_cookie")


def _is_trusted_proxy(address: str | None, trusted_proxies: Iterable[str]) -> bool:
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    for entry in trusted_proxies:
        try:
            if parsed in ipaddress.ip_network(entry, strict=False):
                return True
        except (TypeError, ValueError):
            continue
    return False


def get_client_ip(
    trust_forwarded: bool,
    direct_ip: str | None,
    forwarded_for: str | None,
    trusted_proxies: Iterable[str] = (),
) -> str | None:
    """Resolve the client address only across an explicitly trusted proxy chain.

    The middleware passes the configured proxy allowlist, so enabling forwarded
    headers without trusted proxies cannot turn a client header into an identity
    input.
    """
    proxy_allowlist = tuple(trusted_proxies or ())
    if trust_forwarded and forwarded_for:
        if _is_trusted_proxy(direct_ip, proxy_allowlist):
            chain = [item.strip() for item in forwarded_for.split(",") if item.strip()]
            # Proxies append addresses on the right. Find the first untrusted
            # hop from the right, ignoring malformed header entries.
            for candidate in reversed(chain):
                try:
                    parsed = ipaddress.ip_address(candidate)
                except (TypeError, ValueError):
                    continue
                if not _is_trusted_proxy(candidate, proxy_allowlist):
                    return str(parsed)[:64]
            # A fully trusted chain is unusual but valid; use its leftmost
            # valid hop. Invalid header fragments never become an address.
            for candidate in chain:
                try:
                    return str(ipaddress.ip_address(candidate))[:64]
                except (TypeError, ValueError):
                    continue
    return direct_ip

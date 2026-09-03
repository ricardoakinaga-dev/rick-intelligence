"""Security primitives: public allowlist, proxy trust, cookie/bearer precedence, response headers."""

from __future__ import annotations

import hmac

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


def get_client_ip(trust_forwarded: bool, direct_ip: str | None, forwarded_for: str | None) -> str | None:
    if trust_forwarded and forwarded_for:
        # Take the left-most entry; proxies append to the right.
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first[:64]
    return direct_ip

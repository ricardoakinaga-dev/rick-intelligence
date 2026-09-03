"""In-memory user/session stores. Storage only — no permission policy here."""

from __future__ import annotations

import hashlib
import secrets
import time


def new_token() -> str:
    return secrets.token_urlsafe(32)


def session_id_for_token(token: str) -> str:
    return hashlib.sha256(f"rick-session:{token}".encode("utf-8")).hexdigest()[:16]


class InMemoryUserStore:
    def __init__(self) -> None:
        self._by_email: dict[str, dict] = {}
        self._by_id: dict[str, dict] = {}

    def seed(self, record: dict) -> None:
        self.save(record)

    def get_by_email(self, email: str) -> dict | None:
        return self._by_email.get((email or "").strip().lower())

    def get_by_id(self, user_id: str) -> dict | None:
        return self._by_id.get(user_id)

    def save(self, record: dict) -> None:
        self._by_email[(record.get("email") or "").strip().lower()] = record
        self._by_id[record["user_id"]] = record


class InMemorySessionStore:
    def __init__(self, *, ttl_seconds: int = 8 * 3600) -> None:
        self._sessions: dict[str, dict] = {}
        self.ttl_seconds = ttl_seconds

    def create(self, record: dict) -> str:
        token = new_token()
        now = time.time()
        self._sessions[token] = {
            **record,
            "session_id": session_id_for_token(token),
            "created_at": now,
            "last_seen_at": now,
            "expires_at": now + self.ttl_seconds,
            "revoked_at": None,
            "revoke_reason": None,
        }
        return token

    def get(self, token: str) -> dict | None:
        return self._sessions.get(token)

    def delete(self, token: str) -> None:
        self._sessions.pop(token, None)

    def tokens_for_user(self, user_id: str) -> list[str]:
        return [t for t, r in self._sessions.items() if r.get("user_id") == user_id]

    def touch(self, token: str) -> None:
        record = self._sessions.get(token)
        if record is not None:
            record["last_seen_at"] = time.time()

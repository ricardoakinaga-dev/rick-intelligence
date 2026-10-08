"""In-memory user/session stores. Storage only — no permission policy here."""

from __future__ import annotations

import hashlib
import secrets
import time
from threading import RLock

from rick_identity.snapshots import legacy_snapshot, snapshot_payload, valid_authorization_snapshot


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

    def get_by_email_for_tenant(self, email: str, tenant_id: str) -> dict | None:
        record = self.get_by_email(email)
        if (
            record is None
            or record.get("tenant_id") != tenant_id
            or record.get("status", "active") != "active"
            or record.get("membership_status", "active") != "active"
        ):
            return None
        return record

    def get_unique_active_by_email(self, email: str) -> dict | None:
        record = self.get_by_email(email)
        if (
            record is None
            or record.get("status", "active") != "active"
            or record.get("membership_status", "active") != "active"
        ):
            return None
        return record

    def get_by_id(self, user_id: str) -> dict | None:
        return self._by_id.get(user_id)

    def get_by_id_for_tenant(self, user_id: str, tenant_id: str) -> dict | None:
        record = self._by_id.get(user_id)
        return record if record is not None and record.get("tenant_id") == tenant_id else None

    def get_by_id_for_tenant_workspace(
        self, user_id: str, tenant_id: str, workspace_id: str
    ) -> dict | None:
        record = self._by_id.get(user_id)
        if record is None:
            return None
        record_workspace = record.get("workspace_id", "default")
        return (
            record
            if record.get("tenant_id") == tenant_id and record_workspace == workspace_id
            else None
        )

    def list_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict]:
        return [
            record
            for record in self._by_id.values()
            if (tenant_id is None or record.get("tenant_id") == tenant_id)
            and (workspace_id is None or record.get("workspace_id") == workspace_id)
        ]

    def save(self, record: dict) -> None:
        user_id = record["user_id"]
        previous = self._by_id.get(user_id)
        if previous is not None:
            previous_email = (previous.get("email") or "").strip().lower()
            if previous_email and self._by_email.get(previous_email) is previous:
                self._by_email.pop(previous_email, None)
        self._by_email[(record.get("email") or "").strip().lower()] = record
        self._by_id[user_id] = record


class InMemorySessionStore:
    def __init__(self, *, ttl_seconds: int = 8 * 3600) -> None:
        self._sessions: dict[str, dict] = {}
        self._snapshot_lock = RLock()
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

    def update_authorization_snapshot(self, token: str, *, expected: dict, snapshot: dict) -> bool:
        """Persist a one-time legacy migration only while its source is current."""
        with self._snapshot_lock:
            record = self._sessions.get(token)
            if (record is None or record != expected or not legacy_snapshot(record)
                    or record.get("revoked_at") is not None or time.time() >= record.get("expires_at", 0)
                    or snapshot.get("authorization_state") != "MIGRATED"
                    or not valid_authorization_snapshot({**record, **snapshot})):
                return False
            record.update(snapshot_payload(snapshot))
            return True

    def delete(self, token: str) -> None:
        with self._snapshot_lock:
            self._sessions.pop(token, None)

    def tokens_for_user(self, user_id: str) -> list[str]:
        return [t for t, r in self._sessions.items() if r.get("user_id") == user_id]

    def touch(self, token: str) -> None:
        record = self._sessions.get(token)
        if record is not None:
            now = time.time()
            record["last_seen_at"] = now
            # Session expiry is idle/sliding, while revoked and invalidated
            # records remain terminal in the provider boundary.
            record["expires_at"] = now + self.ttl_seconds

    def records(self) -> list[dict]:
        """Return session records for administrative, already-scoped adapters."""
        return list(self._sessions.values())

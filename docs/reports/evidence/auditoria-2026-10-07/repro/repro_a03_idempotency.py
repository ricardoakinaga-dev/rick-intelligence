"""AUD07-01 reproduction: A03 - idempotency key replays across conversations.

Run from the repository root:

    python3 docs/reports/evidence/auditoria-2026-10-07/repro/repro_a03_idempotency.py

Exit code 0 means the defect was reproduced (baseline evidence). Exit code 1
means the second conversation was answered for its own message. Exit code 2
means the harness itself could not run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
for _pkg in (
    "contracts", "authorization", "identity", "observability", "knowledge",
    "ingestion", "retrieval", "providers", "locking", "professor", "evidence",
    "decision", "storage", "jobs",
):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

from services.audit import InMemoryAuditSink
from services.chat_history import InMemoryChatHistoryStore
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider
from services.knowledge_service import seed_demo_corpus


class _EchoBackend(StubChatBackend):
    async def generate(self, **kwargs):
        return {"answer": "ANSWER_FOR::" + str(kwargs.get("message", "")), "citations": []}


def main() -> int:
    from fastapi.testclient import TestClient

    from app import create_app
    from core.config import ApiSettings
    from dependencies.services import Providers
    from rick_knowledge import InMemoryKnowledgeStore

    settings = ApiSettings(cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False)
    knowledge = InMemoryKnowledgeStore()
    seed_demo_corpus(knowledge)
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=_EchoBackend(),
        chat_history=InMemoryChatHistoryStore(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        knowledge=knowledge,
    )
    app = create_app(settings, providers)

    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123", "tenant_id": "default"},
        )
        if login.status_code != 200:
            print(json.dumps({"harness_error": "login failed", "status": login.status_code}, indent=2))
            return 2

        key = "aud07-repro-key"
        first = client.post(
            "/api/v1/chat",
            json={"message": "ALPHA", "conversation_id": "conv-A", "idempotency_key": key},
        )
        retry = client.post(
            "/api/v1/chat",
            json={"message": "ALPHA", "conversation_id": "conv-A", "idempotency_key": key},
        )
        other = client.post(
            "/api/v1/chat",
            json={"message": "BETA", "conversation_id": "conv-B", "idempotency_key": key},
        )
        if first.status_code != 200:
            print(json.dumps({"harness_error": "first turn failed", "status": first.status_code,
                              "body": first.text[:400]}, indent=2))
            return 2

        first_body, retry_body, other_body = first.json(), retry.json(), other.json()
        cross_replay = bool(
            other.status_code == 200
            and "ANSWER_FOR::ALPHA" in str(other_body.get("answer"))
        )
        print(json.dumps({
            "finding": "A03",
            "retry_same_conversation": {
                "status": retry.status_code,
                "conversation_id": retry_body.get("conversation_id"),
                "answer": retry_body.get("answer"),
                "message_id": retry_body.get("message_id"),
            },
            "other_conversation": {
                "status": other.status_code,
                "conversation_id": other_body.get("conversation_id"),
                "answer": other_body.get("answer"),
                "message_id": other_body.get("message_id"),
            },
            "expected_other_conversation": "conv-B",
            "cross_conversation_replay_defect": cross_replay,
        }, indent=2))
    return 0 if cross_replay else 1


if __name__ == "__main__":
    raise SystemExit(main())

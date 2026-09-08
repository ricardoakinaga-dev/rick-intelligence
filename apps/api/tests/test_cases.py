"""REC-27: controlled human case record/review/feedback coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import create_app
from conftest import login_as, make_settings
from dependencies.services import Providers
from rick_contracts.cases import CaseCreateRequest
from rick_contracts.security import SessionSnapshot
from services.audit import InMemoryAuditSink
from services.case_store import InMemoryClinicalCaseStore, SQLiteClinicalCaseStore
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def _enabled_client(*, case_store=None):
    settings = make_settings(
        clinical_cases_enabled=True,
        clinical_cases_d04_enabled=True,
    )
    audit = InMemoryAuditSink()
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=audit,
        case_store=case_store or InMemoryClinicalCaseStore(),
    )
    return TestClient(create_app(settings, providers), raise_server_exceptions=False), audit


def _session(*, tenant="tenant-a", workspace="workspace-a", user="user-a"):
    return SessionSnapshot(
        authenticated=True,
        session_state="active",
        tenant_id=tenant,
        workspace_id=workspace,
        user_id=user,
        session_id=f"session-{user}",
        permissions=["cases.read", "cases.manage", "cases.feedback", "cases.review"],
    )


def test_contract_requires_structured_scope_and_rejects_unknown_fields():
    payload = CaseCreateRequest.model_validate({
        "title": "Registro",
        "summary": "Resumo humano",
        "hypotheses": [{"statement": "Hipótese registrada", "status": "open"}],
        "evidence": [{"source_type": "document", "source_id": "doc-1", "locator": "chunk-2"}],
    })
    assert payload.hypotheses[0].hypothesis_id is None
    assert payload.evidence[0].evidence_id is None
    with pytest.raises(ValidationError):
        CaseCreateRequest.model_validate({"title": "x", "summary": "y", "tenant_id": "caller-controlled"})
    with pytest.raises(ValidationError):
        CaseCreateRequest.model_validate({"title": "x", "summary": 42})


def test_gate_is_disabled_by_default(client):
    login_as(client, "admin@example.com")
    response = client.post("/api/v1/cases", json={"title": "Caso", "summary": "Resumo"})
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "conflict"
    assert "disabled" in body["message"]
    assert body["details"]["status"] == "disabled"


@pytest.mark.parametrize(
    "enabled,d04_enabled",
    [(True, False), (False, True)],
)
def test_both_feature_gates_are_required(enabled, d04_enabled):
    settings = make_settings(
        clinical_cases_enabled=enabled,
        clinical_cases_d04_enabled=d04_enabled,
    )
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        case_store=InMemoryClinicalCaseStore(),
    )
    with TestClient(create_app(settings, providers), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        response = client.get("/api/v1/cases")
        assert response.status_code == 409
        assert response.json()["error"]["details"]["status"] == "disabled"


def test_enabled_api_records_structured_case_review_feedback_catalog_and_audit():
    store = InMemoryClinicalCaseStore(agent_model_catalog=[{
        "agent_id": "agent-review-local",
        "model_id": "model-review-local",
        "catalog_version": "catalog-v1",
        "purpose": "human_review_assist",
    }, {
        "agent_id": "agent-revoked",
        "model_id": "model-revoked",
        "catalog_version": "catalog-v1",
        "status": "revoked",
        "purpose": "human_review_assist",
    }])
    client, audit = _enabled_client(case_store=store)
    with client:
        login_as(client, "admin@example.com")
        created = client.post("/api/v1/cases", json={
            "title": "Registro controlado",
            "summary": "Resumo digitado por uma pessoa.",
            "hypotheses": [{"statement": "Hipótese explicitamente registrada", "status": "open"}],
            "evidence": [{
                "source_type": "document", "source_id": "doc-123", "locator": "chunk-456",
                "label": "Referência fornecida pelo usuário",
            }],
            "tags": ["local"],
        })
        assert created.status_code == 201, created.text
        case = created.json()
        case_id = case["case_id"]
        assert case["clinical_scope_status"] == "record_review_feedback_only"
        assert case["record"] == case["summary"]
        assert case["hypotheses"][0]["hypothesis_id"].startswith("hypothesis-")
        assert case["evidence"][0]["evidence_id"].startswith("evidence-")
        assert case["agent_model"] is None

        catalog = client.get("/api/v1/cases/catalog/agents")
        assert catalog.status_code == 200
        assert catalog.json()["catalog_status"] == "configured"
        assert catalog.json()["items"][0]["model_id"] == "model-review-local"
        assert all(item["status"] == "authorized" for item in catalog.json()["items"])
        assert "model-revoked" not in {item["model_id"] for item in catalog.json()["items"]}

        updated = client.patch(f"/api/v1/cases/{case_id}", json={
            "summary": "Resumo revisado manualmente.",
            "hypotheses": [{
                "hypothesis_id": "hypothesis-existing",
                "statement": "Hipótese revisada por uma pessoa",
                "status": "deferred",
            }],
            "evidence": [{"evidence_id": "evidence-existing", "source_type": "manual", "source_id": "note-1"}],
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()["summary"] == "Resumo revisado manualmente."
        assert updated.json()["hypotheses"][0]["hypothesis_id"] == "hypothesis-existing"

        reviewed = client.post(f"/api/v1/cases/{case_id}/reviews", json={
            "decision": "needs_revision",
            "review_note": "Revisão humana registrada para retorno ao autor.",
        })
        assert reviewed.status_code == 201, reviewed.text
        assert reviewed.json()["reviewer_user_id"] == "admin"

        feedback = client.post(f"/api/v1/cases/{case_id}/feedback", json={
            "kind": "scope_note",
            "feedback_note": "Manter este módulo restrito ao registro humano.",
        })
        assert feedback.status_code == 201, feedback.text
        assert feedback.json()["feedback_user_id"] == "admin"

        detail = client.get(f"/api/v1/cases/{case_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["case"]["status"] == "reviewed"
        assert detail.json()["case"]["review_count"] == 1
        assert detail.json()["case"]["feedback_count"] == 1
        assert detail.json()["reviews"][0]["request_id"]
        assert detail.json()["feedback"][0]["request_id"]

        workspace = client.get("/api/v1/cases?scope=workspace")
        assert workspace.status_code == 200
        assert workspace.json()["total"] == 1

    actions = [item.get("action") for item in audit.events]
    assert "clinical_case.created" in actions
    assert "clinical_case.updated" in actions
    assert "clinical_case.reviewed" in actions
    assert "clinical_case.feedback_recorded" in actions


def test_case_mutation_requires_audit_before_persisting():
    class UnavailableAudit:
        def health_check(self):
            return False

        def emit(self, event):
            raise AssertionError("the store must not be called when audit is unavailable")

    settings = make_settings(clinical_cases_enabled=True, clinical_cases_d04_enabled=True)
    store = InMemoryClinicalCaseStore()
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=UnavailableAudit(),
        case_store=store,
    )
    with TestClient(create_app(settings, providers), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        response = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": "case-audit-failure"},
            json={"title": "Caso", "summary": "Resumo"},
        )
        assert response.status_code == 503
    assert store.list_cases(session=_session())["total"] == 0


def test_case_mutations_are_idempotent_for_a_stable_key():
    client, _audit = _enabled_client()
    with client:
        login_as(client, "admin@example.com")
        headers = {"Idempotency-Key": "case-create-stable"}
        first = client.post(
            "/api/v1/cases", headers=headers,
            json={"title": "Caso idempotente", "summary": "Resumo"},
        )
        second = client.post(
            "/api/v1/cases", headers=headers,
            json={"title": "Caso idempotente", "summary": "Resumo"},
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["case_id"] == second.json()["case_id"]
        case_id = first.json()["case_id"]

        review_headers = {"Idempotency-Key": "case-review-stable"}
        review_payload = {"decision": "recorded", "review_note": "Revisado"}
        first_review = client.post(
            f"/api/v1/cases/{case_id}/reviews", headers=review_headers, json=review_payload,
        )
        second_review = client.post(
            f"/api/v1/cases/{case_id}/reviews", headers=review_headers, json=review_payload,
        )
        assert first_review.status_code == second_review.status_code == 201
        assert first_review.json()["review_id"] == second_review.json()["review_id"]

        detail = client.get(f"/api/v1/cases/{case_id}")
        assert detail.json()["case"]["review_count"] == 1


def test_store_scope_is_tenant_workspace_and_owner_bounded():
    store = InMemoryClinicalCaseStore()
    owner = _session(user="owner")
    peer = _session(user="peer")
    other_workspace = _session(user="peer", workspace="workspace-b")
    other_tenant = _session(user="peer", tenant="tenant-b")
    item = store.create_case(session=owner, title="Caso", summary="Resumo", evidence=[{
        "source_type": "document", "source_id": "doc-1",
    }])
    case_id = item["case_id"]
    assert store.get_case(session=owner, case_id=case_id) is not None
    assert store.get_case(session=peer, case_id=case_id) is None
    assert store.get_case(session=peer, case_id=case_id, allow_workspace=True) is not None
    assert store.get_case(session=other_workspace, case_id=case_id, allow_workspace=True) is None
    assert store.get_case(session=other_tenant, case_id=case_id, allow_workspace=True) is None
    assert store.list_cases(session=peer)["total"] == 0
    assert store.list_cases(session=peer, owner_only=False)["total"] == 1


def test_sqlite_store_round_trip_and_legacy_compatible_record(tmp_path: Path):
    database = tmp_path / "clinical-cases.sqlite3"
    owner = _session()
    store = SQLiteClinicalCaseStore(database)
    item = store.create_case(
        session=owner,
        title="SQLite",
        summary="Resumo persistido",
        hypotheses=[{"statement": "Hipótese", "status": "open"}],
        evidence=[{"source_type": "chunk", "source_id": "chunk-1"}],
    )
    case_id = item["case_id"]
    store.close()

    reopened = SQLiteClinicalCaseStore(database)
    try:
        loaded = reopened.get_case(session=owner, case_id=case_id)
        assert loaded is not None
        assert loaded["summary"] == "Resumo persistido"
        assert loaded["hypotheses"][0]["hypothesis_id"].startswith("hypothesis-")
        assert loaded["evidence"][0]["source_id"] == "chunk-1"
    finally:
        reopened.close()


def test_sqlite_store_replays_stable_mutation_keys_without_duplicates(tmp_path: Path):
    store = SQLiteClinicalCaseStore(tmp_path / "idempotent.sqlite3")
    owner = _session()
    try:
        first = store.create_case(
            session=owner, title="SQLite idempotente", summary="Resumo", request_id="create-1",
        )
        second = store.create_case(
            session=owner, title="SQLite idempotente", summary="Resumo", request_id="create-1",
        )
        assert first["case_id"] == second["case_id"]

        review_one = store.add_review(
            session=owner, case_id=first["case_id"], decision="recorded",
            review_note="Revisado", request_id="review-1",
        )
        review_two = store.add_review(
            session=owner, case_id=first["case_id"], decision="recorded",
            review_note="Revisado", request_id="review-1",
        )
        assert review_one["review_id"] == review_two["review_id"]

        feedback_one = store.add_feedback(
            session=owner, case_id=first["case_id"], kind="scope_note",
            feedback_note="Observação", request_id="feedback-1",
        )
        feedback_two = store.add_feedback(
            session=owner, case_id=first["case_id"], kind="scope_note",
            feedback_note="Observação", request_id="feedback-1",
        )
        assert feedback_one["feedback_id"] == feedback_two["feedback_id"]
        assert len(store.list_reviews(session=owner, case_id=first["case_id"])) == 1
        assert len(store.list_feedback(session=owner, case_id=first["case_id"])) == 1
    finally:
        store.close()


def test_enabled_without_store_returns_explicit_503():
    settings = make_settings(clinical_cases_enabled=True, clinical_cases_d04_enabled=True)
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
    )
    with TestClient(create_app(settings, providers), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        response = client.get("/api/v1/cases")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"
        assert response.json()["error"]["details"]["status"] == "store_unavailable"

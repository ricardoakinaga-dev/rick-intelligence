"""Formal tenant/evidence composition over live disposable product services.

The HTTP API runs in an owned process with native PostgreSQL identity/session
stores. Positive controls precede every negative family. Timing is a bounded
local experiment, not a production side-channel certification. No default PASS
or production-safety attestation is returned for an unimplemented case.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import statistics
import time
import uuid

from scripts.phase11.formal_lab_resources import LabResources, publish, ROOT


def public_shape(value):
    if isinstance(value, dict):
        return {key: public_shape(child) for key, child in value.items()
                if key not in {"request_id", "correlation_id", "timestamp"}}
    if isinstance(value, list):
        return [public_shape(child) for child in value]
    return value


class TenantRuntime:
    external = True
    production_safe = False

    def __init__(self, run_id: str):
        self.owner = LabResources(run_id)
        self.run_id = self.owner.run_id
        self.authorized = True
        self.observations = []
        self.ready = False

    async def preflight(self):
        self.a, self.scope_a, self.user_a = self.owner.graph("a")
        self.b, self.scope_b, self.user_b = self.owner.graph("b")
        content = ("Segundo a fonte autorizada, o documento confirma o laboratório local. "
                   "As citações de fontes no RICK preservam a linhagem verificada.").encode()
        self.job_a = publish(self.a, self.scope_a, key="tenant-positive-a", content=content)
        self.job_b = publish(self.b, self.scope_b, key="tenant-positive-b", content=content)
        if self.job_a.status != "published" or self.job_b.status != "published":
            raise RuntimeError("tenant_fixture_publication_failed")
        self.client_a = self.owner.serve_api(self.a, self.scope_a, self.user_a)
        self.client_b = self.owner.serve_api(self.b, self.scope_b, self.user_b)
        # Both persisted sessions must exercise the same API event buffer and
        # query path; per-process isolation would hide cross-tenant leakage.
        self.client_b.base_url = self.client_a.base_url
        self.doc_a = self.job_a.document_id
        self.doc_b = self.job_b.document_id
        for client, document in ((self.client_a, self.doc_a), (self.client_b, self.doc_b)):
            if client.get(f"/api/v1/documents/{document}").status_code != 200:
                raise RuntimeError("tenant_http_positive_control_failed")
        from rick_evidence import EvidenceValidator
        from services.professor_backend import EvidenceDecisionGate
        self.scope = self.scope_a
        self.validator = EvidenceValidator(
            authority=EvidenceDecisionGate._KnowledgeAuthority(self.a.knowledge), require_authority=True)
        context = {"tenant_id": self.scope_a["tenant_id"], "workspace_id": self.scope_a["workspace_id"],
                   "allowed_collection_ids": [self.scope_a["collection_id"]]}
        retrieved = self.a.retrieval.retrieve(query="como funcionam as citacoes no rick", context=context)
        self.candidate = next(item.model_dump() for item in retrieved.evidence if item.document_id == self.doc_a)
        self.evidence = self.validator.issue(self.candidate, scope=self.scope)
        self.ready = True
        return {"status": "ready"}

    def _paired_denial(self, path: str, missing: str, *, params=None):
        actual = self.client_a.get(path, params=params)
        absent = self.client_a.get(missing, params=params)
        equal = actual.status_code == absent.status_code and public_shape(actual.json()) == public_shape(absent.json())
        return {"blocked": equal and actual.status_code in {403, 404},
                "allowed": False if equal and actual.status_code in {403, 404} else True,
                "status": "denied" if equal and actual.status_code in {403, 404} else "allowed",
                "metadata_leak_free": equal, "evidence_count": 0, "citation_count": 0}, {
                    "foreign_status": actual.status_code, "absent_status": absent.status_code,
                    "same_public_response": equal}

    async def run_negative_case(self, *, case, timeout_seconds):
        if not self.ready:
            raise RuntimeError("positive_controls_required")
        from rick_evidence import EvidenceValidationError
        name = case["case_id"]
        mutation = case["mutation"]
        measurement = {}
        response = {"blocked": False, "allowed": True, "status": "allowed"}
        if name in {"forged-evidence-id", "stale-document-version", "wrong-checksum", "unknown-chunk"}:
            if name == "stale-document-version":
                try:
                    self.validator.issue(self.candidate, scope=self.scope,
                                         document_version=mutation["document_version"])
                except EvidenceValidationError:
                    denied = True
                else:
                    denied = False
            elif name == "unknown-chunk":
                try:
                    self.validator.issue({**self.candidate, "chunk_id": mutation["chunk_id"]}, scope=self.scope)
                except EvidenceValidationError:
                    denied = True
                else:
                    denied = False
            else:
                field = "evidence_id" if name == "forged-evidence-id" else "checksum"
                invalid = self.evidence.model_copy(update={field: mutation[field]})
                denied = not self.validator.validate_evidence(invalid, expected_scope=self.scope).valid
            response = {"blocked": denied, "allowed": not denied,
                        "status": "denied" if denied else "allowed", "evidence_count": 0}
            measurement = {"positive_evidence_valid": self.validator.validate_evidence(
                self.evidence, expected_scope=self.scope).valid, "mutated_evidence_rejected": denied}
        elif name in {"cross-tenant-document", "error-shape-differential", "tenant-id-enumeration"}:
            params = {"tenant_id": self.scope_b["tenant_id"]} if name == "tenant-id-enumeration" else None
            response, measurement = self._paired_denial(f"/api/v1/documents/{self.doc_b}",
                                                       "/api/v1/documents/missing-" + uuid.uuid4().hex, params=params)
        elif name == "unauthorized-collection":
            observed = self.client_a.get("/api/v1/documents", params={"collection_id": self.scope_b["collection_id"]})
            denied = observed.status_code in {403, 404} or (observed.status_code == 200 and
                       not observed.json().get("items") and observed.json().get("total") == 0)
            response = {"blocked": denied, "allowed": not denied, "status": "denied" if denied else "allowed"}
            measurement = {"http_status": observed.status_code, "foreign_collection_denied": denied}
        elif name == "document-count-enumeration":
            before = self.client_a.get("/api/v1/documents").json()
            key = "foreign-count-" + uuid.uuid4().hex
            job = publish(self.b, self.scope_b, key=key, content=key.encode())
            after = self.client_a.get("/api/v1/documents").json()
            equal = public_shape(before) == public_shape(after) and job.status == "published"
            response = {"blocked": equal, "allowed": not equal, "status": "denied" if equal else "allowed",
                        "metadata_leak_free": equal}
            measurement = {"foreign_write_published": job.status == "published", "actor_list_unchanged": equal}
        elif name == "object-existence-enumeration":
            # Download/read is mediated by the document HTTP boundary; prove
            # the foreign object actually exists before comparing denials.
            from rick_storage import ObjectScope
            payload = self.job_b.payload
            scope = ObjectScope(tenant_id=self.scope_b["tenant_id"], workspace_id=self.scope_b["workspace_id"],
                                source_id=payload["object_source_id"])
            exists = bool(self.b.object_store.get(scope, payload["object_key"], max_bytes=16384))
            response, measurement = self._paired_denial(f"/api/v1/documents/{self.doc_b}",
                                                       "/api/v1/documents/missing-" + uuid.uuid4().hex)
            measurement["foreign_object_positive_control"] = exists
            if not exists:
                response = {"allowed": True}
        elif name == "job-existence-enumeration":
            response, measurement = self._paired_denial(f"/api/v1/ingestion/jobs/{self.job_b.job_id}",
                                                       "/api/v1/ingestion/jobs/missing-" + uuid.uuid4().hex)
        elif name == "collection-existence-enumeration":
            before = self.client_a.get("/api/v1/collections").json()
            other = self.client_a.get("/api/v1/collections", params={"collection_id": self.scope_b["collection_id"]}).json()
            encoded = json.dumps(other)
            safe = public_shape(before) == public_shape(other) and self.scope_b["collection_id"] not in encoded
            response = {"blocked": safe, "allowed": not safe, "status": "denied" if safe else "allowed",
                        "metadata_leak_free": safe}
            measurement = {"foreign_collection_present": self.b.knowledge.get_collection(
                self.scope_b["workspace_id"], self.scope_b["collection_id"], tenant_id=self.scope_b["tenant_id"]) is not None,
                "actor_list_unchanged": safe}
        elif name == "telemetry-identifier-enumeration":
            self.client_b.get(f"/api/v1/documents/{self.doc_b}",
                              headers={"X-Request-ID": mutation["request_id"]})
            observed = self.client_a.get("/api/v1/admin/metrics", params={"trace_id": mutation["trace_id"]})
            forbidden = (mutation["trace_id"], mutation["request_id"], self.scope_b["tenant_id"],
                         self.user_b, self.doc_b, self.job_b.job_id)
            safe = observed.status_code in {200, 403} and not any(value in observed.text for value in forbidden)
            response = {"blocked": safe, "allowed": not safe, "status": "filtered" if safe else "allowed",
                        "metadata_leak_free": safe}
            measurement = {"http_status": observed.status_code, "foreign_identifiers_filtered": safe}
        elif name == "timing-sensitive-identifier":
            foreign, absent = [], []
            paths = (f"/api/v1/documents/{self.doc_b}", "/api/v1/documents/missing-" + uuid.uuid4().hex)
            statuses = []
            for index in range(32):
                for which in (index % 2, 1 - index % 2):
                    start = time.perf_counter()
                    observed = self.client_a.get(paths[which])
                    (foreign if which == 0 else absent).append((time.perf_counter() - start) * 1000)
                    statuses.append(observed.status_code)
            first, second = statistics.median(foreign), statistics.median(absent)
            # Frozen diagnostic lab bound, not an approved production SLA.
            safe = set(statuses) == {404} and abs(first - second) <= 5 and max(first, second) / max(.001, min(first, second)) <= 2
            response = {"blocked": safe, "allowed": not safe, "status": "denied" if safe else "allowed",
                        "timing_leak_free": safe}
            measurement = {"samples_per_group": 32, "foreign_p50_ms": first, "absent_p50_ms": second,
                           "max_p50_delta_ms": 5, "max_p50_ratio": 2, "local_bound_satisfied": safe,
                           "foreign_samples_ms": foreign, "absent_samples_ms": absent}
        elif name == "path-traversal-polyglot-file":
            marker = mutation["polyglot_marker"]
            body = b"%PDF-1.7\n" + marker.encode() + b"\nPK\x03\x04invalid-archive"
            observed = self.client_a.post("/api/v1/documents/upload", files={
                "file": (mutation["filename"], body, mutation["content_type"])},
                data={"collection_id": self.scope_a["collection_id"]})
            safe = observed.status_code in {400, 413, 415, 422}
            measurement = {"upload_http_status": observed.status_code, "parser_rejected": safe}
            response = {"blocked": safe, "allowed": not safe, "status": "denied" if safe else "allowed"}
        elif name == "prompt-injection-document":
            marker = mutation["injection_marker"]
            content = (mutation["document_text"] + " " + marker).encode()
            job = publish(self.a, self.scope_a, key="injection-" + uuid.uuid4().hex, content=content)
            observed = self.client_a.post("/api/v1/chat", json={
                "message": "como funcionam as citacoes no rick", "conversation_id": "injection-" + uuid.uuid4().hex})
            payload = observed.json()
            metadata = payload.get("metadata", {})
            citations = payload.get("citations", [])
            action = metadata.get("decision_action")
            # A validated citation to untrusted text is not evidence that its
            # instructions were followed. Check the attack's requested effect
            # (disclosing credentials), while retaining the generated action
            # and citation count in the raw observation for human review.
            safe_response = action in {"ABSTAIN", "ESCALATE"} or (
                action == "ANSWER" and bool(citations) and metadata.get("publication_validation") == "verified"
                and "hidden credentials" not in payload.get("answer", "").lower()
                and "reveal" not in payload.get("answer", "").lower())
            denied = (observed.status_code == 200 and safe_response
                      and marker not in observed.text and job.status == "published")
            response = {"blocked": denied, "allowed": not denied, "status": "filtered" if denied else "allowed"}
            measurement = {"source_published": job.status == "published", "http_status": observed.status_code,
                           "decision_action": metadata.get("decision_action"), "citation_count": len(citations),
                           "marker_disclosed": marker in observed.text, "local_fixture_only": True}
        else:
            raise ValueError("unimplemented_tenant_negative")
        self.observations.append({"case_id": name, "measurement": measurement,
                                  "blocked": response.get("blocked") is True})
        return response

    async def cleanup(self):
        try:
            await self.owner.close()
        finally:
            output = ROOT / ".runtime/phase-3/formal-local" / self.owner.run_id / "tenant-observations.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"production_safe": False, "closed": self.owner.closed,
                "observations": self.observations}, sort_keys=True, indent=2) + "\n")


def create_runtime(run_id: str = ""):
    return TenantRuntime(run_id or uuid.uuid4().hex)

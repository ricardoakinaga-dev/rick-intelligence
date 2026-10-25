"""Explicit golden composition using the real disposable product graph.

The composition observes physical stages and executes replacement failures.
It never supplies approved faithfulness or corpus authority. Those come only
from an explicitly supplied evaluator; absence remains an evidence gap.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import uuid
import time
import hashlib

from scripts.phase11.formal_lab_resources import LabResources, ROOT
from scripts.phase11.golden_runtime_gate import GoldenRuntime, GateBlocked


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StageTrace:
    def __init__(self):
        self.records = []

    @contextmanager
    def operation(self, name):
        record = {"stage": name, "status": "running", "started_at": now()}
        self.records.append(record)
        try:
            yield
        except BaseException:
            record.update(status="FAIL", finished_at=now())
            raise
        else:
            record.update(status="PASS", finished_at=now())

    def snapshot(self):
        return list(self.records)


class InjectedFailure(RuntimeError):
    pass


class Hooks:
    def __init__(self):
        self.point = None
        self.hits = 0

    def hit(self, point):
        if point == self.point:
            self.hits += 1
            raise InjectedFailure(point)


def observe(target, method, stage, trace, *, before=None, after=None):
    original = getattr(target, method)
    if inspect.iscoroutinefunction(original):
        @wraps(original)
        async def asynchronous(*args, **kwargs):
            with trace.operation(stage):
                if before:
                    before(*args, **kwargs)
                result = await original(*args, **kwargs)
                if after:
                    after(result, *args, **kwargs)
                return result
        setattr(target, method, asynchronous)
    else:
        @wraps(original)
        def synchronous(*args, **kwargs):
            with trace.operation(stage):
                if before:
                    before(*args, **kwargs)
                result = original(*args, **kwargs)
                if after:
                    after(result, *args, **kwargs)
                return result
        setattr(target, method, synchronous)


class NormalizingParser:
    production_safe = True
    process_isolated = True

    def __init__(self, original, trace, hooks):
        self.original, self.trace, self.hooks = original, trace, hooks

    def run(self, *args, **kwargs):
        with self.trace.operation("parse"):
            parsed = self.original.run(*args, **kwargs)
        self.hooks.hit("after_extraction")
        with self.trace.operation("normalize"):
            return replace(parsed, text=unicodedata.normalize("NFC", parsed.text),
                           pages=[replace(page, text=unicodedata.normalize("NFC", page.text)) for page in parsed.pages])


class ObservedChunker:
    __slots__ = ("original", "trace", "hooks")

    def __init__(self, original, trace, hooks):
        self.original, self.trace, self.hooks = original, trace, hooks

    @property
    def __dict__(self):
        # The canonical checkpoint fingerprints chunker configuration. Do not
        # inject callback objects into that durable JSON configuration.
        return vars(self.original)

    def chunk(self, *args, **kwargs):
        with self.trace.operation("chunk"):
            result = self.original.chunk(*args, **kwargs)
        self.hooks.hit("after_chunking")
        return result


class EvidencePort:
    """Reject stale/forged projections explicitly before issuing evidence.

    This stricter runtime policy is deliberately explicit; the default package
    authority continues to canonicalize untrusted fields for compatibility.
    """
    def __init__(self, validator, trace):
        self.validator, self.trace = validator, trace
        self.authority = validator.authority

    def issue(self, candidate, *, scope, document_version=None):
        from rick_evidence import EvidenceValidationError
        value = candidate if isinstance(candidate, dict) else candidate.model_dump()
        issued = self.validator.issue(value, scope=scope, document_version=document_version)
        for field in ("document_version", "checksum"):
            if value.get(field) is not None and value[field] != getattr(issued, field):
                raise EvidenceValidationError("runtime_projection_mismatch")
        return issued

    def build_bundle(self, *, query, candidates, scope, document_version=None):
        from rick_evidence import EvidenceBundle
        with self.trace.operation("evidence"):
            items = [self.issue(item, scope=scope, document_version=document_version) for item in candidates]
            return EvidenceBundle.build(**scope, query=query, evidence=items)

    def validate_bundle(self, *args, **kwargs):
        return self.validator.validate_bundle(*args, **kwargs)


class GoldenComposition:
    def __init__(self, run_id, fixture):
        self.owner = LabResources(run_id)
        self.fixture = fixture
        self.scope = {"tenant_id": f"golden-tenant-{run_id[:12]}",
                      "workspace_id": f"golden-workspace-{run_id[:12]}",
                      "collection_id": f"golden-collection-{run_id[:12]}"}
        try:
            self.graph, _, self.user = self.owner.graph(scope=self.scope)
            self.trace = StageTrace()
            self.hooks = Hooks()
            self.verified_at = None
            self.latest_job = None
            self.baseline_document = None
            self.fault_observations = []
            handler = inspect.getclosurevars(self.graph.worker.registry.get("ingest")).nonlocals["handler"]
            self.pipeline = handler.ingestion
            self.pipeline.parser_runner = NormalizingParser(self.pipeline.parser_runner, self.trace, self.hooks)
            self.pipeline.chunker = ObservedChunker(self.pipeline.chunker, self.trace, self.hooks)
            observe(self.pipeline.embeddings, "embed", "embed", self.trace,
                    after=lambda *_args, **_kwargs: self.hooks.hit("after_embedding"))
            observe(self.graph.object_store, "put", "object", self.trace,
                    before=lambda *_args, **_kwargs: self.hooks.hit("after_upload"),
                    after=lambda *_args, **_kwargs: self.hooks.hit("after_object_store"))
            observe(self.graph.queue, "enqueue", "durable_job", self.trace,
                    after=lambda *_args, **_kwargs: self.hooks.hit("after_enqueue"))
            observe(self.graph.vector_store, "upsert_points", "qdrant", self.trace,
                    before=lambda *_args, **_kwargs: self.hooks.hit("during_qdrant"))
            original_count = self.graph.vector_store.count_for_document

            def count(document_id, collection_id, **kwargs):
                self.hooks.hit("before_verification")
                with self.trace.operation("verify"):
                    value = original_count(document_id, collection_id, **kwargs)
                    if value > 0 and self.verified_at is None:
                        self.verified_at = now()
                self.hooks.hit("after_verification")
                return value
            self.graph.vector_store.count_for_document = count
            original_status = self.graph.knowledge.set_document_status

            def status(document_id, state, **kwargs):
                if state == "published":
                    self.hooks.hit("before_publish")
                    with self.trace.operation("publish"):
                        result = original_status(document_id, state, **kwargs)
                    self.hooks.hit("after_publish")
                    return result
                return original_status(document_id, state, **kwargs)
            self.graph.knowledge.set_document_status = status
            from rick_evidence import EvidenceValidator
            from services.professor_backend import EvidenceDecisionGate
            validator = EvidenceValidator(authority=EvidenceDecisionGate._KnowledgeAuthority(self.graph.knowledge),
                                          require_authority=True)
            self.evidence = EvidencePort(validator, self.trace)
        except BaseException:
            # Factories run synchronously. Explicit cleanup remains available
            # to the caller; constructor errors cannot silently attest PASS.
            if self.owner.server:
                self.owner.server.shutdown()
                self.owner.server.server_close()
            raise

    def upload(self, source, **kwargs):
        kwargs.pop("display_filename", None)
        with self.trace.operation("upload"):
            self.latest_job = self.graph.ingestion.submit_upload(source, **kwargs)
            return self.latest_job

    def run_once(self, **kwargs):
        with self.trace.operation("worker"):
            result = self.graph.worker.run_once(wait=True)
        # Explicit, scoped reconciliation of the committed lineage projection.
        # Qdrant was written before the PostgreSQL publication timestamp existed.
        # Do not invent that field in a returned search view: persist it in the
        # real index under the same collection/document guards, then reread it.
        if self.latest_job:
            job = self.graph.queue.get(self.latest_job["job_id"],
                tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
            if job and job.status == "published" and job.document_id:
                from rick_knowledge import build_point_payload
                with self.graph.knowledge.collection_guard(**self.scope), self.graph.knowledge.mutation_guard(
                    "document:" + job.document_id):
                    document = self.graph.knowledge.get_document(job.document_id,
                        tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
                    if document is None or document.status != "published":
                        raise RuntimeError("publication_changed_during_projection_reconciliation")
                    chunks = self.graph.knowledge.get_chunks(job.document_id,
                        tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
                    by_id = {chunk.chunk_id: chunk for chunk in chunks}
                    points = self.graph.vector_store.snapshot_document(job.document_id, self.scope["collection_id"],
                        tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
                    if len(points) != len(chunks):
                        raise RuntimeError("projection_reconciliation_incomplete")
                    for point in points:
                        point["payload"] = build_point_payload(chunk=by_id[point["payload"]["chunk_id"]], document=document)
                    if self.graph.vector_store.upsert_points(points) != len(points):
                        raise RuntimeError("projection_reconciliation_failed")
        return result

    def count(self, document_id, collection_id, **kwargs):
        # Gate versions passing both positional and named collection_id must
        # not invoke the native port with duplicate argument bindings.
        return self.graph.vector_store.count_for_document(document_id, collection_id, **kwargs)

    def search(self, vector, **kwargs):
        return [hit.payload for hit in self.graph.vector_store.query(vector, **kwargs)]

    def snapshot(self):
        if not self.latest_job:
            return {}
        record = self.graph.queue.get_by_idempotency(**self.scope,
            idempotency_key="golden-" + self.owner.run_id)
        if record is None or not record.document_id:
            return {}
        document = self.graph.knowledge.get_document(record.document_id,
            tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
        chunks = self.graph.knowledge.get_chunks(record.document_id,
            tenant_id=self.scope["tenant_id"], workspace_id=self.scope["workspace_id"])
        return {**asdict(document), "checksum": "sha256:" + document.content_checksum.removeprefix("sha256:"),
                "verified_at": self.verified_at, "index_version": chunks[0].index_version if chunks else None}

    def retrieve(self, **kwargs):
        with self.trace.operation("retrieve"):
            return self.graph.retrieval.retrieve(**kwargs)

    async def generate(self, *, query, context, conversation_id, **kwargs):
        # An approved claim evaluator is not replaced with structural citation
        # presence or a number invented by this local composition.
        with self.trace.operation("professor"):
            result = await self.graph.chat_backend.generate(message=query,
                context={**context, "user_id": self.user,
                         "permissions": ["sources.read", "chat.query", "history.read"]},
                conversation_id=conversation_id, history=[])
        if "faithfulness" not in result.get("metadata", {}):
            raise GateBlocked("approved_claim_support_evaluator_required")
        return result

    def decide(self, decision_input):
        from rick_decision import DecisionLayer
        with self.trace.operation("decision"):
            return DecisionLayer().decide(decision_input)

    def render(self, *, professor_output, decision, evidence_bundle, **kwargs):
        with self.trace.operation("response"):
            if getattr(decision.action, "value", decision.action) != "ANSWER":
                raise ValueError("answer_not_authorized")
            return professor_output

    async def fault(self, *, point, baseline, scope, fixture, **kwargs):
        # A queue retry from one point cannot contaminate another point. Each
        # case gets a fresh real tenant, baseline publication and owned graph.
        case = GoldenComposition(uuid.uuid4().hex[:16], fixture)
        try:
            case.upload(fixture.content, **case.scope, filename=fixture.filename,
                        idempotency_key="golden-" + case.owner.run_id)
            case.run_once()
            case_baseline = case.snapshot()
            if (case_baseline.get("document_version") != baseline["document_version"]
                    or case_baseline.get("checksum") != baseline["checksum"]):
                raise RuntimeError("fault_baseline_not_equivalent")
            observed = case.execute_fault(point=point, baseline=case_baseline,
                                          scope=case.scope, fixture=fixture)
            self.fault_observations.append({"point": point, "case_run_id": case.owner.run_id, **observed})
            return observed
        finally:
            await case.cleanup()

    def execute_fault(self, *, point, baseline, scope, fixture):
        """Observe actual injected replacement outcomes, never prefill booleans."""
        document = self.graph.knowledge.get_document(baseline["document_id"],
            tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
        key = "fault-" + uuid.uuid4().hex
        self.hooks.point, self.hooks.hits = point, 0
        failed = False
        job = None
        try:
            try:
                self.graph.ingestion.submit_upload(fixture.content + key.encode(), **scope,
                    filename="replacement.txt", idempotency_key=key, operation="reindex",
                    document_id=document.document_id)
            except Exception:
                if self.hooks.hits == 0:
                    raise
                failed = True
            else:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    self.graph.worker.run_once(wait=True)
                    job = self.graph.queue.get_by_idempotency(**scope, idempotency_key=key)
                    if job and job.status in {"failed", "dead", "cancelled", "published"}:
                        break
                    if point == "before_publish" and self.hooks.hits and job:
                        pending = self.graph.knowledge.get_publication(job.job_id, **scope)
                        if pending and pending["outcome"] == "pending":
                            break
                    time.sleep(.05)
                failed = bool(job and job.status in {"failed", "dead", "cancelled"})
        finally:
            self.hooks.point = None
        current = self.graph.knowledge.get_document(document.document_id,
            tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
        preserved = bool(current and current.status == "published"
            and current.document_version == document.document_version
            and current.content_checksum == document.content_checksum)
        # Replay the exact upload/idempotency key against persisted state. The
        # queue identity and object digest must not change after the fault.
        replay_verified = False
        try:
            replay = self.graph.ingestion.submit_upload(fixture.content + key.encode(), **scope,
                filename="replacement.txt", idempotency_key=key, operation="reindex",
                document_id=document.document_id)
            persisted = self.graph.queue.get_by_idempotency(**scope, idempotency_key=key)
            replay_verified = bool(persisted and replay["job_id"] == persisted.job_id
                and (job is None or persisted.job_id == job.job_id))
        except Exception:
            pass
        import psycopg
        persisted = self.graph.queue.get_by_idempotency(**scope, idempotency_key=key)
        recovered_from_pending = False
        if point == "before_publish" and persisted:
            receipt = self.graph.knowledge.get_publication(persisted.job_id, **scope)
            if receipt and receipt["outcome"] == "pending" and preserved:
                for _ in range(3):
                    persisted = self.graph.queue.reconcile_publication(persisted.job_id, **scope)
                    if persisted and persisted.status == "published":
                        recovered_from_pending = True
                        break
                    time.sleep(.1)
        failed_attempts = succeeded_attempts = 0
        if persisted:
            with psycopg.connect(self.graph.settings.external_database_dsn, connect_timeout=5) as connection:
                failed_attempts, succeeded_attempts = connection.execute(
                    "SELECT count(*) FILTER (WHERE state='FAILED'), count(*) FILTER (WHERE state='SUCCEEDED') "
                    "FROM rick_ingestion_job_attempts WHERE job_id=%s", (persisted.job_id,)).fetchone()
            if persisted.status != "published" and failed_attempts > 0:
                failed = True
        observed = {"injected": self.hooks.hits > 0, "failed": failed,
            "last_verified_preserved": preserved, "published_version": current.document_version if current else None,
            "published_checksum": "sha256:" + current.content_checksum.removeprefix("sha256:") if current else None,
            "new_version_published": bool(job and job.status == "published"), "replay_verified": replay_verified}
        observed.update(failed_attempts=failed_attempts, succeeded_attempts=succeeded_attempts,
                        queue_state=persisted.status if persisted else None)
        if (point == "after_publish" or recovered_from_pending) and persisted and persisted.status == "published":
            committed = self.graph.knowledge.get_document(persisted.document_id,
                tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
            receipt = self.graph.knowledge.get_publication(persisted.job_id, **scope)
            chunks = self.graph.knowledge.get_chunks(persisted.document_id,
                tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
            count = self.graph.vector_store.count_for_document(persisted.document_id, scope["collection_id"],
                tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
            expected = hashlib.sha256(fixture.content + key.encode()).hexdigest()
            previous = self.graph.knowledge.get_document(document.document_id,
                tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
            consistent = bool(committed and committed.status == "published"
                and committed.content_checksum.removeprefix("sha256:") == expected
                and len(chunks) == count > 0 and receipt and receipt["outcome"] == "committed"
                and receipt["document_id"] == persisted.document_id)
            observed.update(publication_outcome="committed", committed_document_id=persisted.document_id,
                failed=False, new_version_published=True,
                committed_version=committed.document_version if committed else None,
                committed_checksum=committed.content_checksum if committed else None,
                receipt_bound_to_job=bool(receipt and receipt["job_id"] == persisted.job_id),
                projection_consistent=consistent, point_count=count, chunk_count=len(chunks),
                previous_version_retired=bool(previous and previous.status == "unpublished"),
                recovered_from_pending=recovered_from_pending,
                baseline_preserved_while_pending=preserved if recovered_from_pending else False)
            observed["status"] = "PASS" if (consistent and self.hooks.hits > 0 and replay_verified
                and succeeded_attempts == 1 and observed["previous_version_retired"]) else "FAIL"
            self.fault_observations.append({"point": point, **observed})
            return observed
        observed["status"] = "PASS" if (observed["injected"] and failed and preserved
            and replay_verified and not observed["new_version_published"]) else "FAIL"
        self.fault_observations.append({"point": point, **observed})
        return observed

    async def cleanup(self, **kwargs):
        try:
            await self.owner.close()
        finally:
            output = ROOT / ".runtime/phase-3/formal-local" / self.owner.run_id / "golden-observations.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"production_safe": False, "closed": self.owner.closed,
                "stage_trace": self.trace.snapshot(), "faults": self.fault_observations}, indent=2) + "\n")


def build_golden_runtime(*, run_id, fixture, **kwargs):
    composition = GoldenComposition(run_id, fixture)
    graph = composition.graph
    return GoldenRuntime(upload=SimpleNamespace(submit_upload=composition.upload),
        object_store=graph.object_store, queue=graph.queue,
        worker=SimpleNamespace(run_once=composition.run_once), ingestion=composition.pipeline,
        knowledge=graph.knowledge, embeddings=graph._embedding_adapter,
        vector_store=SimpleNamespace(count_for_document=composition.count, search=composition.search),
        retrieval=SimpleNamespace(retrieve=composition.retrieve), evidence=composition.evidence,
        professor=SimpleNamespace(generate=composition.generate), decision=SimpleNamespace(decide=composition.decide),
        response=SimpleNamespace(render=composition.render), failure_matrix=SimpleNamespace(run=composition.fault),
        stage_trace=composition.trace, lineage=composition, authorized=True, external=True,
        production_safe=False, preflight=lambda: graph.knowledge.health_check() and graph.queue.health_check(),
        cleanup=composition.cleanup, runtime_metadata={"vector_backend": "qdrant", "provider_fixture": True,
            "claim_support_evaluator": "NOT_CONFIGURED", "projection_reconciliation": "explicit_local_harness"})

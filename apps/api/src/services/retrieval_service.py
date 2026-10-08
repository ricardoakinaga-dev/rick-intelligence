"""Retrieval application service behind the root Professor backend.

    The service owns the retrieval engine and preserves the extracted retrieval
    engine's provenance. A configured vector store is rehydrated on first use so
    a process restart cannot silently produce an empty index.
"""

from __future__ import annotations

import os
import inspect
from itertools import islice
from collections.abc import Mapping

from rick_retrieval import (
    BM25FReranker,
    DeterministicHashEmbedding,
    InMemoryBackend,
    RetrievalEngine,
    RetrievalOptions,
    retrieval_quality_score,
)
from rick_contracts.rag import EvidenceDto, RetrievalResultDto

from services.knowledge_service import (
    LifecycleAuthorityError,
    resolve_collection_state,
    resolve_document_state,
)


MAX_REHYDRATED_POINTS = 100_000


def _bounded_points(
    reader,
    *,
    tenant_id: str,
    workspace_id: str,
    allowed_collection_ids: list[str],
) -> list[dict]:
    try:
        points = reader(
            limit=MAX_REHYDRATED_POINTS,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids,
        )
    except TypeError:
        # A vector reader without the scope contract cannot be used for
        # restart rehydration. Fetching a global point snapshot here would
        # widen the tenant boundary before the retrieval engine filters it.
        raise ValueError("vector reader does not accept authorization scope") from None
    snapshot = list(islice(points, MAX_REHYDRATED_POINTS + 1))
    if len(snapshot) > MAX_REHYDRATED_POINTS:
        raise ValueError("complete point snapshot exceeds read limit")
    return snapshot


def root_retrieval_enabled() -> bool:
    return (os.getenv("RICK_API_ROOT_RETRIEVAL") or "1").strip() == "1"


def _document_value(document: object, name: str, default: object = None) -> object:
    if isinstance(document, Mapping):
        return document.get(name, default)
    return getattr(document, name, default)


class RetrievalApplicationService:
    def __init__(self, *, knowledge, vectors=None, embeddings=None, backend=None, fallback=None) -> None:
        self.knowledge = knowledge
        self.vectors = vectors
        self.embeddings = embeddings or DeterministicHashEmbedding()
        self.engine = RetrievalEngine(
            backend=backend or InMemoryBackend(),
            fallback=fallback,
            reranker=BM25FReranker(),
            embed=self.embeddings.embed,
        )
        self._indexed = False
        self._points_attached = False
        self._points: list[dict] = []
        self._provenance: dict[str, dict] = {}

    def _ensure_index(self, context: Mapping[str, object]) -> None:
        if self._indexed:
            return
        if not self._points_attached and self.vectors is not None:
            all_points = getattr(self.vectors, "all_points", None)
            if callable(all_points):
                tenant_id = context.get("tenant_id")
                workspace_id = context.get("workspace_id")
                allowed = context.get("allowed_collection_ids") or []
                if not (
                    isinstance(tenant_id, str)
                    and tenant_id
                    and isinstance(workspace_id, str)
                    and workspace_id
                    and isinstance(allowed, list)
                ):
                    raise ValueError("retrieval scope is incomplete")
                self._points = _bounded_points(
                    all_points,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    allowed_collection_ids=allowed,
                )
        chunks = []
        for point in self._points:
            payload = point.get("payload") if isinstance(point, dict) else None
            if not isinstance(payload, dict):
                continue
            document_id = payload.get("document_id")
            chunk_id = payload.get("chunk_id")
            workspace_id = payload.get("workspace_id")
            tenant_id = payload.get("tenant_id")
            collection_id = payload.get("collection_id")
            text = payload.get("text")
            vector = point.get("vector")
            if not all(
                isinstance(value, str) and bool(value)
                for value in (document_id, chunk_id, tenant_id, workspace_id, collection_id, text)
            ) or not isinstance(vector, (list, tuple)):
                continue
            # A vector write can fail after partially persisting points. Never
            # make processing/failed/deleted metadata searchable on refresh.
            if self.knowledge is not None:
                getter = getattr(self.knowledge, "get_document", None)
                document = None
                if callable(getter):
                    try:
                        parameters = inspect.signature(getter).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    names = {parameter.name for parameter in parameters}
                    scoped = {"tenant_id", "workspace_id"}.issubset(names) or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    )
                    if scoped:
                        document = getter(
                            document_id,
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                        )
                if document is None or _document_value(document, "status") != "published":
                    continue
                if (
                    _document_value(document, "workspace_id") != workspace_id
                    or _document_value(document, "collection_id") != collection_id
                    or _document_value(document, "tenant_id") != tenant_id
                ):
                    continue
            self._provenance[chunk_id] = dict(payload)
            chunks.append({
                "chunk_id": chunk_id, "document_id": document_id,
                "workspace_id": workspace_id, "collection_id": collection_id,
                "tenant_id": tenant_id,
                "text": text, "vector": vector,
                "source": payload.get("source", payload.get("document_filename", "")),
                "document_filename": payload.get("document_filename", payload.get("source", "")),
                "title": payload.get("title", ""), "page_start": payload.get("page_start"),
                "page_end": payload.get("page_end", payload.get("page_start")),
                "section": payload.get("section"), "checksum": payload.get("checksum", ""),
                "document_version": payload.get("document_version", ""),
            })
        self.engine.attach_index(chunks)
        self._indexed = True

    def attach_points(self, points: list[dict]) -> None:
        self._points = list(points)
        self._points_attached = True
        self._provenance = {}
        self._indexed = False

    def _collection_state(self, lifecycle: dict[str, str], *, tenant_id: str,
                          workspace_id: str, collection_id: str) -> str:
        """Resolve one collection through the canonical lifecycle authority.

        The verdict is memoized for this query only: a hot index must not keep
        serving a collection that was archived after it was built.
        """

        cached = lifecycle.get(collection_id)
        if cached is None:
            cached = resolve_collection_state(
                self.knowledge,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                collection_id=collection_id,
            )
            lifecycle[collection_id] = cached
        return cached

    def _admitted(self, context: Mapping[str, object], lifecycle: dict[str, str]) -> bool:
        """Deny the query before ranking when no granted collection is active.

        A wildcard grant cannot name one collection, so it is admitted here and
        each projected item still resolves its own collection below.
        """

        allowed = context.get("allowed_collection_ids") or []
        tenant_id = context.get("tenant_id")
        workspace_id = context.get("workspace_id")
        if not isinstance(tenant_id, str) or not isinstance(workspace_id, str):
            raise LifecycleAuthorityError("lifecycle scope is incomplete")
        concrete = [
            value for value in allowed
            if isinstance(value, str) and value and value != "*"
        ]
        if not concrete:
            return True
        states = [
            self._collection_state(
                lifecycle, tenant_id=tenant_id, workspace_id=workspace_id,
                collection_id=value,
            )
            for value in concrete
        ]
        return "active" in states

    def _projectable(self, item: object, context: Mapping[str, object],
                     lifecycle: dict[str, str]) -> bool:
        """Revalidate collection and document lifecycle at the response edge."""

        tenant_id = context.get("tenant_id")
        workspace_id = context.get("workspace_id")
        collection_id = _document_value(item, "collection_id")
        document_id = _document_value(item, "document_id")
        if not all(
            isinstance(value, str) and value
            for value in (tenant_id, workspace_id, collection_id, document_id)
        ):
            return False
        if self._collection_state(
            lifecycle, tenant_id=tenant_id, workspace_id=workspace_id,
            collection_id=collection_id,
        ) != "active":
            return False
        return resolve_document_state(
            self.knowledge,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            document_id=document_id,
        ) == "published"

    @staticmethod
    def _lifecycle_denied(query: str, context: Mapping[str, object]) -> RetrievalResultDto:
        return RetrievalResultDto(
            query=query,
            evidence=[],
            candidate_count=0,
            selected_count=0,
            backend="",
            fallback_used=False,
            metadata={
                "authorization": "lifecycle_denied",
                "workspace_id": context.get("workspace_id", ""),
                "tenant_id": context.get("tenant_id", ""),
            },
        )

    def retrieve(self, *, query: str, context: dict, top_k: int = 3) -> RetrievalResultDto:
        allowed = context.get("allowed_collection_ids") or []
        lifecycle: dict[str, str] = {}
        if allowed and not self._admitted(context, lifecycle):
            return self._lifecycle_denied(query, context)
        if allowed:
            self._ensure_index(context)
        result = self.engine.retrieve(query=query, context=context,
                                      options=RetrievalOptions(top_k=top_k, rerank=True))
        evidence = []
        for raw in result.evidence:
            if not self._projectable(raw, context, lifecycle):
                continue
            item = dict(raw)
            payload = self._provenance.get(str(item.get("chunk_id", "")), {})
            for field in ("source", "title", "section", "checksum", "document_version"):
                if not item.get(field) and payload.get(field):
                    item[field] = payload[field]
            for field in ("page_start", "page_end"):
                if item.get(field) is None and payload.get(field) is not None:
                    item[field] = payload[field]
            quality = retrieval_quality_score(item, result.query)
            item["retrieval_quality_score"] = quality
            # Legacy clients still consume this field; the contract docs make
            # clear that it is the same uncalibrated ranking signal.
            item["confidence_score"] = quality
            # Tenant is an authorization boundary, not public source
            # provenance. Preserve it in the internal DTO until the final
            # consumer validates scope; HTTP projections still omit it.
            evidence.append(EvidenceDto.model_validate(item))
        return RetrievalResultDto(
            query=result.query,
            evidence=evidence,
            candidate_count=result.candidate_count,
            selected_count=(
                result.selected_count
                if len(evidence) == len(result.evidence)
                else len(evidence)
            ),
            backend=result.backend,
            fallback_used=result.fallback_used,
            metadata={
                **({"authorization": result.metadata["authorization"]}
                   if "authorization" in result.metadata else {}),
                "workspace_id": context.get("workspace_id", ""),
                "tenant_id": context["tenant_id"],
            },
        )

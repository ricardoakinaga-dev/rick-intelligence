"""Root Professor backend adapter for the canonical chat service.

This module is the only API-facing adapter between the root orchestration
package and HTTP.  It does not reimplement retrieval, citation validation, or
provider retry policy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
import asyncio
import inspect

from core.otel import record_safe_exception, stage_span
from rick_authorization import permission_granted
from rick_contracts.chat import Citation
from rick_contracts.professor import ProfessorRequest
from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, ProviderMessage, ProviderToolCallDelta
from rick_contracts.security import RetrievalContext
from rick_professor import ProfessorLimits, ProfessorOrchestrator

_DEFAULT_REQUEST_CLASSIFIER = object()


class ProfessorBackendError(Exception):
    """Safe API-adapter failure with a stable stage only."""

    _ALLOWED = {"lease_unavailable", "lease_lost", "retrieval_failed", "provider_failed", "citation_invalid"}

    def __init__(self, stage: str) -> None:
        self.stage = stage if stage in self._ALLOWED else "provider_failed"
        super().__init__(self.stage)


class ProviderChatAdapter:
    """Adapt the typed provider client to Professor's `complete` port."""

    def __init__(self, provider) -> None:
        self.provider = provider

    async def complete(
        self, *, messages: Sequence[ProviderMessage], conversation_id: str
    ) -> ChatCompletionResult:
        correlation_id = f"chat-{conversation_id}"[:128]
        with stage_span("provider.chat_completion", attributes={"provider.operation": "chat_completion"}) as span:
            try:
                return await self.provider.chat_completion(
                    messages=messages,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                record_safe_exception(span, exc)
                raise

    def stream(self, *, messages: Sequence[ProviderMessage], conversation_id: str) -> AsyncIterator[ChatCompletionChunk]:
        async def iterate() -> AsyncIterator[ChatCompletionChunk]:
            with stage_span("provider.chat_completion.stream", attributes={"provider.operation": "chat_completion_stream"}) as span:
                try:
                    target = getattr(self.provider, "chat_completion_stream", None)
                    if callable(target):
                        stream = target(messages=messages, correlation_id=f"chat-{conversation_id}"[:128])
                        if hasattr(stream, "__await__"):
                            stream = await stream
                        try:
                            async for chunk in stream:
                                yield chunk if isinstance(chunk, ChatCompletionChunk) else ChatCompletionChunk.model_validate(chunk)
                        finally:
                            close = getattr(stream, "aclose", None)
                            if callable(close):
                                await close()
                        return
                    result = await self.complete(messages=messages, conversation_id=conversation_id)
                    yield ChatCompletionChunk(
                        model=result.model, delta=result.content, finish_reason=result.finish_reason,
                        correlation_id=result.correlation_id, usage=result.usage,
                        tool_calls=[
                            ProviderToolCallDelta(index=index, **call.model_dump())
                            for index, call in enumerate(result.tool_calls)
                        ] if result.tool_calls else None,
                    )
                except Exception as exc:
                    record_safe_exception(span, exc)
                    raise
        return iterate()


class EvidenceDecisionGate:
    """Issue authoritative evidence before the Professor sees retrieval output.

    Retrieval remains responsible for ranking and ACL filtering. This adapter
    adds the server-issued evidence bundle and deterministic decision policy at
    the application seam, so caller-provided evidence IDs never become trusted
    by the Professor. A low quality result gets one bounded retrieval retry;
    every other non-answer decision is returned as an empty evidence set.
    """

    class _KnowledgeAuthority:
        """Resolve retrieval projections against canonical PostgreSQL knowledge."""

        def __init__(self, knowledge) -> None:
            self.knowledge = knowledge

        def resolve(self, candidate: object, *, scope) -> Mapping[str, object] | None:
            raw = candidate if isinstance(candidate, Mapping) else {}
            document_id = raw.get("document_id")
            chunk_id = raw.get("chunk_id")
            if not isinstance(document_id, str) or not document_id.strip():
                return None
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                return None
            try:
                document = self.knowledge.get_document(
                    document_id,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
                if document is None or (
                    document.document_id != document_id
                    or document.tenant_id != scope.tenant_id
                    or document.workspace_id != scope.workspace_id
                    or document.collection_id != scope.collection_id
                ):
                    return None
                if document.status != "published":
                    return None
                collection = self.knowledge.get_collection(
                    scope.workspace_id, scope.collection_id, tenant_id=scope.tenant_id,
                )
                if collection is None or (
                    collection.tenant_id != scope.tenant_id
                    or collection.workspace_id != scope.workspace_id
                    or collection.collection_id != scope.collection_id
                    or collection.status != "active"
                ):
                    return None
                get_chunks = self.knowledge.get_chunks
                try:
                    parameters = inspect.signature(get_chunks).parameters.values()
                except (TypeError, ValueError):
                    parameters = ()
                names = {parameter.name for parameter in parameters}
                scoped_chunks = {"tenant_id", "workspace_id"}.issubset(names) or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
                if scoped_chunks:
                    chunks = get_chunks(
                        document_id,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                    )
                else:
                    # The in-memory/SQLite compatibility stores expose the
                    # historical document-only chunk read. The document was
                    # already resolved with the complete scope above; retain
                    # the boundary by revalidating every returned chunk.
                    chunks = get_chunks(document_id)
            except Exception:
                return None
            chunk = next(
                (
                    item for item in chunks
                    if getattr(item, "chunk_id", None) == chunk_id
                    and getattr(item, "document_id", None) == document_id
                    and getattr(item, "tenant_id", None) == scope.tenant_id
                ),
                None,
            )
            if chunk is None:
                return None
            return {
                "tenant_id": document.tenant_id,
                "workspace_id": document.workspace_id,
                "collection_id": document.collection_id,
                "document_id": document.document_id,
                "document_version": document.document_version,
                "document_checksum": document.content_checksum,
                "chunk_id": chunk.chunk_id,
                "source": getattr(document, "display_filename", "") or getattr(document, "filename", ""),
                "title": (
                    getattr(document, "title", "")
                    or getattr(document, "display_filename", "")
                    or getattr(document, "filename", "")
                ),
                "checksum": chunk.checksum or document.content_checksum,
                "text": chunk.text,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section,
                "retrieval_score": raw.get("retrieval_score", raw.get("score", 0.0)),
                "reranking_score": raw.get("reranking_score", raw.get("rerank_score", 0.0)),
            }

    def __init__(
        self, retrieval, *, knowledge=None,
        request_classifier=_DEFAULT_REQUEST_CLASSIFIER,
        authorization_revalidator=None,
    ) -> None:
        from rick_decision import (
            CitationSupportMetrics,
            DecisionAction,
            DecisionInput,
            DecisionLayer,
            DecisionPolicy,
            DomainRisk,
            IntentClarity,
            UserIntent,
            ClinicalDomainPolicy,
            RequestClassification,
            classify_request,
        )
        from rick_evidence import EvidenceBundle, EvidenceScope, EvidenceValidator

        self.retrieval = retrieval
        self.request_classifier = (
            ClinicalDomainPolicy()
            if request_classifier is _DEFAULT_REQUEST_CLASSIFIER else request_classifier
        )
        self.authorization_revalidator = authorization_revalidator
        self._classify_request = classify_request
        self._RequestClassification = RequestClassification
        self._CitationSupportMetrics = CitationSupportMetrics
        self._DecisionAction = DecisionAction
        self._DecisionInput = DecisionInput
        self._DecisionPolicy = DecisionPolicy
        self._DomainRisk = DomainRisk
        self._IntentClarity = IntentClarity
        self._UserIntent = UserIntent
        self._EvidenceBundle = EvidenceBundle
        self._EvidenceScope = EvidenceScope
        authority = self._KnowledgeAuthority(knowledge) if knowledge is not None else None
        self.validator = EvidenceValidator(
            max_bundle_items=8,
            authority=authority,
            require_authority=knowledge is not None,
        )
        self.decision_layer = DecisionLayer(evidence_validator=self.validator)

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if isinstance(value, Mapping):
            return value
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            result = dump()
            if isinstance(result, Mapping):
                return result
        return {}

    @staticmethod
    async def _call(target, **kwargs):
        is_async = inspect.iscoroutinefunction(target) or inspect.iscoroutinefunction(getattr(target, "__call__", None))
        result = target(**kwargs) if is_async else await asyncio.to_thread(target, **kwargs)
        return await result if inspect.isawaitable(result) else result

    def _citation_support_metrics(
        self,
        payload: Mapping[str, object],
    ) -> tuple[object | None, bool]:
        """Parse an explicitly observed metric payload without inventing one.

        The second return value distinguishes an absent observation from a
        malformed one.  A malformed observation is deliberately converted to
        a zero structural signal by the caller so a bad metadata value cannot
        fall back to the legacy bundle-exists path.
        """

        raw_metadata = payload.get("metadata")
        if not isinstance(raw_metadata, Mapping):
            return None, False
        metadata = dict(raw_metadata)
        raw: Mapping[str, object] | None = None
        nested = metadata.get("citation_support_metrics")
        if isinstance(nested, Mapping):
            raw = nested
        elif "citation_support_metrics" in metadata:
            return None, True
        else:
            nested_support = metadata.get("citation_support")
            if isinstance(nested_support, Mapping):
                raw = nested_support
            elif "citation_support" in metadata:
                return None, True
            elif any(
                key in metadata
                for key in (
                    "citation_precision",
                    "citation_recall",
                    "citation_completeness",
                    "unsupported_claim_rate",
                    "faithfulness",
                    "citation_support_status",
                    "citation_evaluated_claims",
                )
            ):
                raw = metadata
            else:
                return None, False

        values: dict[str, object] = {}
        for key in (
            "status",
            "citation_precision",
            "citation_recall",
            "citation_completeness",
            "unsupported_claim_rate",
            "faithfulness",
            "evaluated_claims",
            "source",
        ):
            if key in raw:
                values[key] = raw[key]
        aliases = {
            "status": ("status", "citation_support_status"),
            "evaluated_claims": ("evaluated_claims", "citation_evaluated_claims", "claim_count"),
            "source": ("source", "citation_support_source"),
        }
        for target, names in aliases.items():
            if target in values:
                continue
            for name in names:
                if name in raw:
                    values[target] = raw[name]
                    break
        try:
            return self._CitationSupportMetrics.model_validate(values), True
        except Exception:
            return None, True

    def _structural_citation_support(self, bundle: object | None) -> float:
        """Return only the observed bundle/citation-registry validity signal."""

        if bundle is None:
            return 0.0
        report = self.validator.validate_bundle(bundle)
        return 1.0 if report.valid and report.evidence_count > 0 else 0.0

    def _decision_input(
        self,
        *,
        context: Mapping[str, object],
        bundle: object | None,
        evidence_count: int,
        retrieval_quality: float,
        attempt: int,
        citation_support_metrics: object | None = None,
        citation_metrics_present: bool = False,
        classification=None,
        retry_available: bool = True,
    ):
        tenant_id = context.get("tenant_id") if bundle is not None else None
        workspace_id = context.get("workspace_id") if bundle is not None else None
        collection_id = getattr(bundle, "collection_id", None) if bundle is not None else None
        # A malformed explicitly supplied observation must not fall back to a
        # passing structural signal. An absent observation retains the legacy
        # pre-generation registry check for compatibility; strict runtime
        # gates use the typed metrics field directly.
        structural_citation_support = (
            0.0
            if citation_metrics_present and citation_support_metrics is None
            else self._structural_citation_support(bundle)
        )
        policy = self._DecisionPolicy(
            min_retrieval_quality=0.50,
            min_citation_support=1.0,
            min_provider_confidence_signal=0.0,
            max_retrieval_attempts=1,
        )
        if not isinstance(classification, self._RequestClassification):
            classification = self._RequestClassification("unavailable", "request_policy_unavailable")
        return self._DecisionInput(
            evidence_bundle=bundle,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=collection_id,
            retrieval_quality=max(0.0, min(1.0, float(retrieval_quality))),
            evidence_count=evidence_count,
            # This legacy scalar means only that the server-issued citation
            # registry validated. It is not claim-level citation support.
            citation_support=structural_citation_support,
            citation_support_metrics=citation_support_metrics,
            # This is an availability signal for the already composed typed
            # provider port. It is not presented as a model confidence score.
            provider_confidence_signal=1.0,
            domain_risk=classification.domain_risk,
            user_intent=classification.intent,
            human_review_required=classification.human_review_required,
            policy_allows_answer=classification.allows_answer and self.validator.authority is not None,
            policy=policy,
            retrieval_attempt=attempt,
            retrieval_available=retry_available,
        )

    def _issue_candidates(
        self,
        *,
        query: str,
        context: Mapping[str, object],
        candidates: Sequence[object],
    ) -> tuple[list[dict[str, object]], object | None, float]:
        tenant_id = context.get("tenant_id")
        workspace_id = context.get("workspace_id")
        allowed = context.get("allowed_collection_ids")
        if not (
            isinstance(tenant_id, str)
            and isinstance(workspace_id, str)
            and isinstance(allowed, list)
            and allowed
        ):
            return [], None, 0.0

        # EvidenceBundle is deliberately single-collection. Deterministically
        # select the first authorized collection returned by retrieval and keep
        # other authorized collections for a separate request/turn.
        selected_collection: str | None = None
        issued: list[object] = []
        normalized: list[dict[str, object]] = []
        quality_values: list[float] = []
        for raw in candidates:
            candidate = dict(self._mapping(raw))
            collection_id = candidate.get("collection_id")
            if not isinstance(collection_id, str) or not collection_id:
                continue
            if "*" not in allowed and collection_id not in allowed:
                continue
            if selected_collection is not None and collection_id != selected_collection:
                continue
            scope = self._EvidenceScope(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                collection_id=collection_id,
            )
            authoritative = None
            if self.validator.authority is not None:
                try:
                    authoritative = self.validator.authority.resolve(candidate, scope=scope)
                except Exception:
                    authoritative = None
                if not isinstance(authoritative, Mapping):
                    continue
            try:
                evidence = self.validator.issue(
                    candidate,
                    scope=scope,
                    _resolved_candidate=authoritative,
                )
            except Exception:
                # Missing or malformed provenance is not a reason to trust a
                # legacy identifier. It is simply excluded from generation.
                continue
            if any(item.evidence_id == evidence.evidence_id for item in issued):
                continue
            selected_collection = collection_id
            raw_quality = candidate.get(
                "retrieval_quality_score", candidate.get("confidence_score", 0.0)
            )
            # Never return the retrieval projection's text or provenance to
            # Professor. Evidence.issue() may have resolved a canonical
            # record, so the public candidate must be reconstructed from that
            # immutable object rather than updated in place.
            normalized.append(
                {
                    "evidence_id": evidence.evidence_id,
                    "tenant_id": evidence.tenant_id,
                    "workspace_id": evidence.workspace_id,
                    "collection_id": evidence.collection_id,
                    "document_id": evidence.document_id,
                    "document_version": evidence.document_version,
                    "document_checksum": (
                        authoritative.get("document_checksum")
                        if isinstance(authoritative, Mapping) else None
                    ),
                    "chunk_id": evidence.chunk_id,
                    "source": evidence.source,
                    "title": (
                        authoritative.get("title", "")
                        if isinstance(authoritative, Mapping)
                        else candidate.get("title", "")
                    ),
                    "checksum": evidence.checksum,
                    "text": evidence.text,
                    "page_start": evidence.page_start,
                    "page_end": evidence.page_end,
                    "section": evidence.section,
                    "retrieval_quality_score": raw_quality,
                    # Ranking signals are not provenance. Preserve only the
                    # bounded typed scores needed by Professor's existing
                    # approval threshold; source text and identity above
                    # come exclusively from the issued Evidence object.
                    "confidence_score": raw_quality,
                    "score": candidate.get("score", 0.0),
                    "rank": candidate.get("rank", 0),
                    "dense_score": candidate.get("dense_score", 0.0),
                    "sparse_score": candidate.get("sparse_score", 0.0),
                    "reranking_score": evidence.reranking_score,
                    "retrieval_score": evidence.retrieval_score,
                }
            )
            issued.append(evidence)
            try:
                quality = float(raw_quality)
            except (TypeError, ValueError):
                quality = 0.0
            if quality == quality and quality not in (float("inf"), float("-inf")):
                quality_values.append(max(0.0, min(1.0, quality)))
            if len(normalized) >= 8:
                break

        if selected_collection is None or not issued:
            return [], None, 0.0
        scope = self._EvidenceScope(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=selected_collection,
        )
        bundle = self._EvidenceBundle.build_from_scope(
            scope=scope,
            query=query,
            evidence=issued,
        )
        return normalized, bundle, max(quality_values or [0.0])

    async def retrieve(self, *, query: str, context: dict, history: Sequence[str] = ()) -> dict[str, object]:
        target = getattr(self.retrieval, "retrieve", None)
        if not callable(target):
            raise TypeError("retrieval dependency has no retrieve callable")
        last_payload: dict[str, object] = {"evidence": []}
        last_decision = None
        classification = self._classify_request(self.request_classifier, query, history=history)
        retry_query = classification.retry_query
        retry_available = isinstance(retry_query, str) and retry_query.strip() != query.strip()
        initial_action = None
        for attempt in range(2):
            with stage_span("retrieval", attributes={"retrieval.attempt": attempt}) as retrieval_span:
                try:
                    with stage_span("stores.retrieval", attributes={"store.operation": "retrieve"}) as stores_span:
                        try:
                            raw_result = await self._call(
                                target, query=query if attempt == 0 else retry_query,
                                context={**context, "allowed_collection_ids": list(context.get("allowed_collection_ids") or [])},
                            )
                        except Exception as exc:
                            record_safe_exception(stores_span, exc)
                            raise
                    payload = dict(self._mapping(raw_result))
                    raw_evidence = payload.get("evidence", [])
                    candidates = (
                        list(raw_evidence)
                        if isinstance(raw_evidence, Sequence)
                        and not isinstance(raw_evidence, (str, bytes, bytearray))
                        else []
                    )
                    with stage_span("evidence.validation", attributes={"evidence.candidates": len(candidates)}) as evidence_span:
                        try:
                            normalized, bundle, quality = await asyncio.to_thread(
                                self._issue_candidates,
                                query=query,
                                context=context,
                                candidates=candidates,
                            )
                        except Exception as exc:
                            record_safe_exception(evidence_span, exc)
                            raise
                    citation_support_metrics, citation_metrics_present = self._citation_support_metrics(payload)
                    decision_input = self._decision_input(
                        context=context,
                        bundle=bundle,
                        evidence_count=len(normalized),
                        retrieval_quality=quality,
                        attempt=attempt,
                        citation_support_metrics=citation_support_metrics,
                        citation_metrics_present=citation_metrics_present,
                        classification=classification,
                        retry_available=retry_available,
                    )
                    with stage_span("decision.policy", attributes={"decision.attempt": attempt}) as decision_span:
                        try:
                            decision = self.decision_layer.decide(decision_input)
                        except Exception as exc:
                            record_safe_exception(decision_span, exc)
                            raise
                except Exception as exc:
                    record_safe_exception(retrieval_span, exc)
                    raise
            last_payload = payload
            last_decision = decision
            if initial_action is None:
                initial_action = decision.action.value
            if decision.action is not self._DecisionAction.RETRIEVE_AGAIN:
                break

        raw_metadata = last_payload.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        metadata.update(classification.metadata())
        metadata.update({
            "decision_initial_action": initial_action,
            "retrieval_strategy": "original" if last_decision.retrieval_attempt == 0 else "policy_topic_terms_v1",
            "evidence_collection_mode": "first_valid_single_collection",
            "semantic_support_status": "NOT_EVALUATED",
        })
        if last_decision is not None:
            metadata.update(
                {
                    "decision_action": last_decision.action.value,
                    "decision_reason": last_decision.reason_code,
                    "decision_attempt": last_decision.retrieval_attempt,
                    "evidence_bundle_id": last_decision.evidence_bundle_id,
                }
            )
        if last_decision is not None and last_decision.action is self._DecisionAction.ANSWER:
            last_payload["evidence"] = normalized
            last_payload["selected_count"] = len(normalized)
        else:
            last_payload["evidence"] = []
            last_payload["selected_count"] = 0
        last_payload["metadata"] = metadata
        return last_payload

    async def validate_publication(
        self, *, context: dict, evidence: Sequence[Mapping[str, object]],
        cited_evidence_ids: Sequence[str],
    ) -> bool:
        """Re-resolve the full prompt snapshot at the final delivery boundary.

        A live authorization callback is a server composition port, never a
        request field. Its result may narrow, but cannot expand, request scope.
        No snapshot or grant is cached on this shared gate between requests.
        """
        if self.validator.authority is None or not 1 <= len(evidence) <= 8:
            return False
        original = dict(context)
        original_permissions = original.get("permissions")
        if not isinstance(original_permissions, list) or not permission_granted(
            role=None, permissions=original_permissions, required="chat.query", authoritative=True,
        ):
            return False
        current = original
        if self.authorization_revalidator is not None:
            try:
                current = await self._call(self.authorization_revalidator, context={
                    **original,
                    "allowed_collection_ids": list(original.get("allowed_collection_ids") or []),
                    "permissions": list(original.get("permissions") or []),
                })
            except Exception:
                return False
            if not isinstance(current, Mapping) or any(
                current.get(key) != original.get(key)
                for key in ("tenant_id", "workspace_id", "user_id")
            ):
                return False
            permissions = current.get("permissions")
            if not isinstance(permissions, list) or not permission_granted(
                role=None, permissions=permissions, required="chat.query", authoritative=True,
            ):
                return False
        allowed = original.get("allowed_collection_ids")
        refreshed = current.get("allowed_collection_ids")
        if not isinstance(allowed, list) or not isinstance(refreshed, list):
            return False
        if any(not isinstance(value, str) for value in [*allowed, *refreshed]):
            return False
        if any(not isinstance(item, Mapping) for item in evidence):
            return False
        ids = [item.get("evidence_id") for item in evidence]
        if (
            any(not isinstance(value, str) for value in [*ids, *cited_evidence_ids])
            or len(set(ids)) != len(ids)
            or not cited_evidence_ids or not set(cited_evidence_ids).issubset(ids)
        ):
            return False
        if len({item.get("collection_id") for item in evidence}) != 1:
            return False

        def revalidate() -> bool:
            for item in evidence:
                collection_id = item.get("collection_id")
                if ("*" not in allowed and collection_id not in allowed) or (
                    "*" not in refreshed and collection_id not in refreshed
                ):
                    return False
                scope = self._EvidenceScope(
                    tenant_id=original.get("tenant_id"), workspace_id=original.get("workspace_id"),
                    collection_id=collection_id,
                )
                authoritative = self.validator.authority.resolve(item, scope=scope)
                if not isinstance(authoritative, Mapping):
                    return False
                fresh = self.validator.issue(item, scope=scope, _resolved_candidate=authoritative)
                if fresh.evidence_id != item.get("evidence_id"):
                    return False
                if (
                    not item.get("document_checksum")
                    or item.get("document_checksum") != authoritative.get("document_checksum")
                    or item.get("title", "") != authoritative.get("title", "")
                ):
                    return False
            return True

        try:
            return await asyncio.to_thread(revalidate)
        except Exception:
            return False

    async def validate_cached_response(
        self, *, context: Mapping[str, object], response: Mapping[str, object],
    ) -> bool:
        """Revalidate every source before returning an idempotent cached answer."""
        metadata = response.get("metadata")
        citations = response.get("citations")
        if not isinstance(citations, Sequence) or isinstance(citations, (str, bytes, bytearray)):
            return False
        if not citations:
            return not (
                isinstance(metadata, Mapping)
                and metadata.get("evidence_status") == "APPROVED_EVIDENCE"
            )
        authority = self.validator.authority
        if authority is None or not 1 <= len(citations) <= 8:
            return False

        def resolve_snapshot() -> tuple[list[dict[str, object]], list[str]] | None:
            evidence: list[dict[str, object]] = []
            cited_ids: list[str] = []
            for citation in citations:
                if not isinstance(citation, Mapping):
                    return None
                collection_id = citation.get("collection_id")
                if not isinstance(collection_id, str) or not collection_id:
                    return None
                scope = self._EvidenceScope(
                    tenant_id=context.get("tenant_id"),
                    workspace_id=context.get("workspace_id"),
                    collection_id=collection_id,
                )
                authoritative = authority.resolve(citation, scope=scope)
                if not isinstance(authoritative, Mapping):
                    return None
                if (
                    (citation.get("checksum") is not None
                     and citation.get("checksum") != authoritative.get("checksum"))
                    or (citation.get("title") is not None
                        and citation.get("title") != authoritative.get("title"))
                ):
                    return None
                issued = self.validator.issue(
                    citation, scope=scope, _resolved_candidate=authoritative,
                )
                cited_ids.append(issued.evidence_id)
                evidence.append({
                    "evidence_id": issued.evidence_id,
                    "document_id": issued.document_id,
                    "chunk_id": issued.chunk_id,
                    "collection_id": issued.collection_id,
                    "document_checksum": authoritative.get("document_checksum"),
                    "title": authoritative.get("title", ""),
                })
            return evidence, cited_ids

        try:
            snapshot = await asyncio.to_thread(resolve_snapshot)
        except Exception:
            return False
        if snapshot is None:
            return False
        evidence, cited_ids = snapshot
        return await self.validate_publication(
            context=dict(context), evidence=evidence, cited_evidence_ids=cited_ids,
        )


class OwnedLeaseAdapter:
    """Expose the Professor owner-token port over a root LeaseClient.

    `LeaseClient.acquire()` intentionally generates its own owner token for
    high-level callers. Professor already owns a per-run token, so this seam
    uses the client's validated low-level owner-bound operations instead.
    """

    def __init__(self, client) -> None:
        self.client = client

    async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict[str, bool]:
        acquired = await self.client.acquire_owned(key, owner, ttl_ms)
        return {"acquired": acquired}

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> dict[str, bool]:
        renewed = await self.client.renew_owned(key, owner, ttl_ms)
        return {"renewed": renewed}

    async def release(self, *, key: str, owner: str) -> dict[str, bool]:
        released = await self.client.release_owned(key, owner)
        return {"released": released}


class ProfessorChatBackend:
    """ChatBackend implementation backed by root retrieval + Professor."""

    provider_kind = "professor"

    def __init__(
        self, *, retrieval, provider, lease=None, knowledge=None,
        limits: ProfessorLimits | None = None,
        request_classifier=_DEFAULT_REQUEST_CLASSIFIER,
        authorization_revalidator=None,
    ) -> None:
        self.retrieval = retrieval
        self.evidence_gate = EvidenceDecisionGate(
            retrieval, knowledge=knowledge, request_classifier=request_classifier,
            authorization_revalidator=authorization_revalidator,
        )
        self.provider = ProviderChatAdapter(provider)
        self.lease = OwnedLeaseAdapter(lease) if lease is not None else None
        self.orchestrator = ProfessorOrchestrator(
            retrieval=self.evidence_gate,
            chat_provider=self.provider,
            lease_manager=self.lease,
            limits=limits,
            require_publication_revalidation=True,
        )

    def readiness_check(self) -> bool:
        """Assert that the composed grounded chat wrapper is usable locally."""

        return self.lease is not None and callable(getattr(self.provider.provider, "chat_completion", None))

    async def validate_cached_response(
        self, *, context: Mapping[str, object], response: Mapping[str, object],
    ) -> bool:
        return await self.evidence_gate.validate_cached_response(context=context, response=response)

    async def generate(self, *, message: str, context: dict, conversation_id: str,
                       history: list[dict[str, str]] | None = None) -> dict:
        prior = []
        for item in list(history or [])[-50:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            try:
                prior.append(ProviderMessage(role=item["role"], content=str(item.get("content") or "")[:2_000]))
            except Exception:
                continue
        request = ProfessorRequest(
            query=message,
            conversation_id=conversation_id,
            retrieval_context=RetrievalContext.model_validate(context),
            history=prior,
        )
        result = await self.orchestrator.run(request)
        if result.evidence_status == "GENERATION_FAILED":
            raise ProfessorBackendError(str(result.metadata.get("failure_stage", "provider_failed")))
        if result.evidence_status == "CITATION_INVALID":
            raise ProfessorBackendError("citation_invalid")
        return {
            "answer": result.answer,
            "citations": [c.model_dump(mode="json") for c in result.citations],
            "metadata": {
                "backend": "professor",
                "evidence_status": result.evidence_status,
                **result.metadata,
            },
        }

    def generate_stream(self, *, message: str, context: dict, conversation_id: str,
                        history: list[dict[str, str]] | None = None):
        """Yield provider deltas and a final citation-validated result."""
        prior = []
        for item in list(history or [])[-50:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            try:
                prior.append(ProviderMessage(role=item["role"], content=str(item.get("content") or "")[:2_000]))
            except Exception:
                continue
        request = ProfessorRequest(
            query=message,
            conversation_id=conversation_id,
            retrieval_context=RetrievalContext.model_validate(context),
            history=prior,
        )

        async def stream():
            async with aclosing(self.orchestrator.stream(request)) as source:
                async for event in source:
                    if event.get("kind") == "delta":
                        yield {"type": "delta", "delta": str(event.get("delta") or ""), "provisional": True}
                        continue
                    result = event.get("response")
                    if result is None:
                        continue
                    if result.evidence_status == "GENERATION_FAILED":
                        raise ProfessorBackendError(str(result.metadata.get("failure_stage", "provider_failed")))
                    if result.evidence_status == "CITATION_INVALID":
                        raise ProfessorBackendError("citation_invalid")
                    yield {
                        "type": "final",
                        "result": {
                            "answer": result.answer,
                            "citations": [c.model_dump(mode="json") for c in result.citations],
                            "metadata": {
                                "backend": "professor", "evidence_status": result.evidence_status,
                                **result.metadata,
                            },
                        },
                    }
        return stream()

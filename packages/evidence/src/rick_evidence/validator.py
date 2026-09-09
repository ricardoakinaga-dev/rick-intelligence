"""Fail-closed validation and deterministic citation support checks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field

from rick_evidence.models import (
    Evidence,
    EvidenceBundle,
    EvidenceScope,
    _ContractModel,
    _MAX_TEXT_CHARS,
    _bounded_text,
    _finite_score,
    _read,
    _token,
    server_bundle_id,
    server_evidence_id,
)


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "a", "as", "o", "os", "e", "and", "or", "de", "da", "do", "das", "dos",
        "um", "uma", "uns", "umas", "the", "of", "to", "in", "on", "for", "with",
        "is", "are", "be", "this", "that", "it", "que", "se", "em", "no", "na",
        "nos", "nas", "por", "para", "com", "um", "uma", "é", "ao", "aos",
    }
)


class EvidenceValidationError(ValueError):
    """Safe validation failure with a stable, non-content error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EvidenceValidationReport(_ContractModel):
    """Result of validating a complete evidence bundle."""

    valid: bool
    error_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    evidence_count: int = Field(default=0, ge=0, le=100)
    bundle_id: str | None = None


class CitationValidationReport(_ContractModel):
    """Result of resolving citation identifiers against one bundle."""

    valid: bool
    error_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    cited_count: int = Field(default=0, ge=0, le=100)
    resolved_count: int = Field(default=0, ge=0, le=100)


class ClaimSupportReport(_ContractModel):
    """Deterministic lexical support signal, explicitly not entailment."""

    valid: bool
    error_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    cited_count: int = Field(default=0, ge=0, le=100)
    claim_token_count: int = Field(default=0, ge=0, le=10_000)
    matched_token_count: int = Field(default=0, ge=0, le=10_000)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceAuthority(Protocol):
    """Synchronous canonical source used before evidence issuance.

    Retrieval output is an untrusted projection.  A production authority must
    resolve the document/chunk again inside the already authorized scope and
    return the canonical text, checksum and version fields.
    """

    def resolve(
        self,
        candidate: object,
        *,
        scope: EvidenceScope,
    ) -> Mapping[str, object] | None: ...


def _scope(value: EvidenceScope | Mapping[str, object]) -> EvidenceScope:
    if isinstance(value, EvidenceScope):
        return value
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("invalid_scope")
    try:
        return EvidenceScope.model_validate(dict(value))
    except Exception as exc:
        raise EvidenceValidationError("invalid_scope") from exc


def _candidate_value(candidate: object, *names: str, default: object = None) -> object:
    for name in names:
        value = _read(candidate, name, None)
        if value is not None:
            return value
    return default


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORDS.findall(value)
        if token.casefold() not in _STOP_WORDS
    }


@dataclass(frozen=True, slots=True)
class EvidenceValidator:
    """Issue evidence from retrieval candidates and validate citation use.

    The validator does not authorize a request.  It receives an already
    authorized :class:`EvidenceScope` from the caller and rejects candidates
    whose explicit scope conflicts with it.  A retrieval ``evidence_id`` is
    ignored and replaced by a fresh digest generated from this package's
    complete provenance payload.
    """

    max_bundle_items: int = 20
    max_text_chars: int = _MAX_TEXT_CHARS
    min_claim_token_coverage: float = 0.80
    authority: EvidenceAuthority | None = None
    require_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.max_bundle_items, int) or isinstance(self.max_bundle_items, bool):
            raise TypeError("max_bundle_items must be an integer")
        if self.max_bundle_items < 0 or self.max_bundle_items > 100:
            raise ValueError("max_bundle_items is out of range")
        if not isinstance(self.max_text_chars, int) or isinstance(self.max_text_chars, bool):
            raise TypeError("max_text_chars must be an integer")
        if self.max_text_chars < 1 or self.max_text_chars > _MAX_TEXT_CHARS:
            raise ValueError("max_text_chars is out of range")
        _finite_score(self.min_claim_token_coverage, name="min_claim_token_coverage")
        if not 0.0 <= self.min_claim_token_coverage <= 1.0:
            raise ValueError("min_claim_token_coverage must be between zero and one")
        if self.require_authority and self.authority is None:
            raise ValueError("authoritative evidence resolution is required")

    def _resolve_authoritative(
        self,
        candidate: object,
        *,
        scope: EvidenceScope,
    ) -> object:
        """Replace retrieval fields with a canonical, scope-bound record."""

        if self.authority is None:
            if self.require_authority:
                raise EvidenceValidationError("authoritative_resolution_unavailable")
            return candidate
        resolver = getattr(self.authority, "resolve", None)
        if not callable(resolver):
            raise EvidenceValidationError("authoritative_resolution_unavailable")
        try:
            resolved = resolver(candidate, scope=scope)
        except EvidenceValidationError:
            raise
        except Exception as exc:
            raise EvidenceValidationError("authoritative_resolution_failed") from exc
        if not isinstance(resolved, Mapping):
            raise EvidenceValidationError("authoritative_evidence_missing")
        resolved_value = dict(resolved)
        for name in ("tenant_id", "workspace_id", "collection_id"):
            if resolved_value.get(name) != getattr(scope, name):
                raise EvidenceValidationError("authoritative_scope_mismatch")
        for name in ("document_id", "chunk_id"):
            supplied = _read(candidate, name, None)
            authoritative = resolved_value.get(name)
            if supplied is not None and authoritative != supplied:
                raise EvidenceValidationError("authoritative_identity_mismatch")
        return resolved_value

    def issue(
        self,
        candidate: object,
        *,
        scope: EvidenceScope | Mapping[str, object],
        document_version: str | None = None,
        _resolved_candidate: Mapping[str, object] | None = None,
    ) -> Evidence:
        """Issue one server-owned evidence item from a retrieval candidate."""

        expected = _scope(scope)
        candidate_scope = {
            name: _read(candidate, name, None)
            for name in ("tenant_id", "workspace_id", "collection_id")
        }
        for name, supplied in candidate_scope.items():
            if supplied is not None and supplied != getattr(expected, name):
                raise EvidenceValidationError("candidate_scope_mismatch")

        candidate = (
            dict(_resolved_candidate)
            if _resolved_candidate is not None
            else self._resolve_authoritative(candidate, scope=expected)
        )
        for name in ("tenant_id", "workspace_id", "collection_id"):
            if candidate.get(name) != getattr(expected, name):
                raise EvidenceValidationError("authoritative_scope_mismatch")

        version = document_version
        candidate_version = _candidate_value(candidate, "document_version", "version")
        if version is not None and candidate_version is not None and candidate_version != version:
            raise EvidenceValidationError("document_version_mismatch")
        if version is None:
            version = candidate_version
        if not isinstance(version, str) or not version.strip():
            raise EvidenceValidationError("document_version_missing")

        text = _candidate_value(candidate, "text", "excerpt", default=None)
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > self.max_text_chars:
            raise EvidenceValidationError("invalid_excerpt")
        source = _candidate_value(candidate, "source", "document_filename", default=None)
        checksum = _candidate_value(candidate, "checksum", "content_checksum", default=None)
        document_id = _candidate_value(candidate, "document_id", default=None)
        chunk_id = _candidate_value(candidate, "chunk_id", default=None)
        if not all(isinstance(value, str) and value.strip() for value in (source, checksum, document_id, chunk_id)):
            raise EvidenceValidationError("incomplete_provenance")

        try:
            return Evidence.issue(
                tenant_id=expected.tenant_id,
                workspace_id=expected.workspace_id,
                collection_id=expected.collection_id,
                document_id=document_id,
                document_version=version,
                chunk_id=chunk_id,
                source=source,
                checksum=checksum,
                text=text,
                page_start=_candidate_value(candidate, "page_start", "page"),
                page_end=_candidate_value(candidate, "page_end"),
                section=_candidate_value(candidate, "section", "heading"),
                retrieval_score=_candidate_value(candidate, "retrieval_score", "score", default=0.0),
                reranking_score=_candidate_value(
                    candidate,
                    "reranking_score",
                    "rerank_score",
                    "bm25f_score",
                    default=0.0,
                ),
            )
        except EvidenceValidationError:
            raise
        except Exception as exc:
            raise EvidenceValidationError("invalid_evidence_candidate") from exc

    def build_bundle(
        self,
        *,
        query: str,
        candidates: Iterable[object],
        scope: EvidenceScope | Mapping[str, object],
        document_version: str | None = None,
    ) -> EvidenceBundle:
        """Issue a bounded, single-scope bundle from retrieval output."""

        items: list[Evidence] = []
        for candidate in candidates:
            if len(items) >= self.max_bundle_items:
                raise EvidenceValidationError("evidence_limit_exceeded")
            items.append(self.issue(candidate, scope=scope, document_version=document_version))
        expected = _scope(scope)
        try:
            return EvidenceBundle.build(
                tenant_id=expected.tenant_id,
                workspace_id=expected.workspace_id,
                collection_id=expected.collection_id,
                query=query,
                evidence=items,
            )
        except EvidenceValidationError:
            raise
        except Exception as exc:
            raise EvidenceValidationError("invalid_evidence_bundle") from exc

    # Short aliases keep the integration seam readable without introducing a
    # second implementation or a second contract.
    issue_evidence = issue
    issue_bundle = build_bundle

    def validate_bundle(
        self,
        bundle: object,
        *,
        expected_scope: EvidenceScope | Mapping[str, object] | None = None,
    ) -> EvidenceValidationReport:
        """Validate scope, server identifiers, and the complete citation map."""

        if not isinstance(bundle, EvidenceBundle):
            return EvidenceValidationReport(valid=False, error_codes=("bundle_type_invalid",))
        errors: list[str] = []
        if expected_scope is not None:
            try:
                scope = _scope(expected_scope)
            except EvidenceValidationError as exc:
                errors.append(exc.code)
            else:
                if bundle.scope != scope:
                    errors.append("bundle_scope_mismatch")
        identifiers: list[str] = []
        for item in bundle.evidence:
            if not isinstance(item, Evidence):
                errors.append("evidence_type_invalid")
                continue
            if item.scope != bundle.scope:
                errors.append("evidence_scope_mismatch")
            if item.evidence_id != server_evidence_id(item):
                errors.append("evidence_id_invalid")
            identifiers.append(item.evidence_id)
        if len(identifiers) != len(set(identifiers)):
            errors.append("duplicate_evidence_id")
        expected_map = {identifier: f"[cite:{identifier}]" for identifier in identifiers}
        if bundle.citation_map != expected_map:
            errors.append("citation_map_invalid")
        if bundle.bundle_id != server_bundle_id(bundle):
            errors.append("bundle_id_invalid")
        return EvidenceValidationReport(
            valid=not errors,
            error_codes=tuple(dict.fromkeys(errors)),
            evidence_count=len(bundle.evidence),
            bundle_id=bundle.bundle_id,
        )

    def validate_evidence(
        self,
        evidence: object,
        *,
        expected_scope: EvidenceScope | Mapping[str, object] | None = None,
    ) -> EvidenceValidationReport:
        """Validate one issued item before it enters a bundle or response."""

        if not isinstance(evidence, Evidence):
            return EvidenceValidationReport(valid=False, error_codes=("evidence_type_invalid",))
        errors: list[str] = []
        if expected_scope is not None:
            try:
                scope = _scope(expected_scope)
            except EvidenceValidationError as exc:
                errors.append(exc.code)
            else:
                if evidence.scope != scope:
                    errors.append("evidence_scope_mismatch")
        if evidence.evidence_id != server_evidence_id(evidence):
            errors.append("evidence_id_invalid")
        return EvidenceValidationReport(
            valid=not errors,
            error_codes=tuple(dict.fromkeys(errors)),
            evidence_count=1,
        )

    def validate_citations(
        self,
        bundle: object,
        cited_evidence_ids: Sequence[str],
    ) -> CitationValidationReport:
        """Resolve citation IDs only against the server-issued bundle registry."""

        if not isinstance(bundle, EvidenceBundle):
            return CitationValidationReport(valid=False, error_codes=("bundle_type_invalid",))
        bundle_report = self.validate_bundle(bundle)
        if not bundle_report.valid:
            return CitationValidationReport(
                valid=False,
                error_codes=("bundle_invalid",),
            )
        if isinstance(cited_evidence_ids, (str, bytes, bytearray)):
            return CitationValidationReport(valid=False, error_codes=("citation_sequence_invalid",))
        identifiers = list(cited_evidence_ids)
        errors: list[str] = []
        if not identifiers:
            errors.append("citation_missing")
        if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
            errors.append("citation_id_invalid")
        if len(identifiers) != len(set(identifiers)):
            errors.append("duplicate_citation")
        resolved = sum(1 for identifier in identifiers if identifier in bundle.citation_map)
        if resolved != len(identifiers):
            errors.append("unknown_citation")
        return CitationValidationReport(
            valid=not errors,
            error_codes=tuple(dict.fromkeys(errors)),
            cited_count=len(identifiers),
            resolved_count=resolved,
        )

    def validate_claim_support(
        self,
        *,
        claim: str,
        bundle: object,
        cited_evidence_ids: Sequence[str],
    ) -> ClaimSupportReport:
        """Return a bounded lexical support signal for a cited claim.

        This is a deterministic screening signal.  It does not establish
        entailment, truth, probability, or domain correctness; callers should
        keep human or domain-specific review in the decision policy where
        required.
        """

        citation_report = self.validate_citations(bundle, cited_evidence_ids)
        errors = list(citation_report.error_codes)
        if not isinstance(claim, str):
            errors.append("claim_invalid")
            return ClaimSupportReport(
                valid=False,
                error_codes=tuple(dict.fromkeys(errors)),
                cited_count=citation_report.cited_count,
            )
        try:
            normalized_claim = _bounded_text(claim, name="claim", maximum=self.max_text_chars)
        except Exception:
            errors.append("claim_invalid")
            return ClaimSupportReport(
                valid=False,
                error_codes=tuple(dict.fromkeys(errors)),
                cited_count=citation_report.cited_count,
            )
        claim_tokens = _meaningful_tokens(normalized_claim)
        if not claim_tokens:
            errors.append("claim_has_no_terms")
        evidence_tokens: set[str] = set()
        if isinstance(bundle, EvidenceBundle):
            by_id = {item.evidence_id: item for item in bundle.evidence}
            for identifier in cited_evidence_ids:
                item = by_id.get(identifier)
                if item is not None:
                    evidence_tokens.update(_meaningful_tokens(item.text))
        matched = len(claim_tokens & evidence_tokens)
        coverage = matched / len(claim_tokens) if claim_tokens else 0.0
        if coverage < self.min_claim_token_coverage:
            errors.append("claim_support_below_threshold")
        return ClaimSupportReport(
            valid=not errors,
            error_codes=tuple(dict.fromkeys(errors)),
            cited_count=citation_report.cited_count,
            claim_token_count=len(claim_tokens),
            matched_token_count=matched,
            coverage=coverage,
        )

    validate_claim = validate_claim_support
    def validate(
        self,
        value: object,
        *,
        expected_scope: EvidenceScope | Mapping[str, object] | None = None,
    ) -> EvidenceValidationReport:
        """Dispatch validation for either one item or a complete bundle."""

        if isinstance(value, Evidence):
            return self.validate_evidence(value, expected_scope=expected_scope)
        return self.validate_bundle(value, expected_scope=expected_scope)


__all__ = [
    "ClaimSupportReport",
    "CitationValidationReport",
    "EvidenceAuthority",
    "EvidenceValidationError",
    "EvidenceValidationReport",
    "EvidenceValidator",
]

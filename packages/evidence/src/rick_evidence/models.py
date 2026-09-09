"""Immutable server-issued evidence models.

Evidence identifiers are content-addressed by the trusted server boundary.
They are not caller-selected labels.  The digest includes the complete
provenance tuple and excerpt, so changing a source, scope, version, or chunk
produces a different identifier and an old identifier cannot be reused for
the changed object.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVIDENCE_CONTRACT_VERSION = "evidence-contract-v1"
EVIDENCE_BUNDLE_CONTRACT_VERSION = "evidence-bundle-v1"

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_EVIDENCE_ID = re.compile(r"^ev_[0-9a-f]{32}$")
_BUNDLE_ID = re.compile(r"^eb_[0-9a-f]{32}$")
_MAX_QUERY_CHARS = 20_000
_MAX_SOURCE_CHARS = 2_000
_MAX_SECTION_CHARS = 1_000
_MAX_TEXT_CHARS = 1_000_000

_EVIDENCE_DIGEST_FIELDS = (
    "tenant_id",
    "workspace_id",
    "collection_id",
    "document_id",
    "document_version",
    "chunk_id",
    "source",
    "page_start",
    "page_end",
    "section",
    "checksum",
    "text",
    "retrieval_score",
    "reranking_score",
)


class _ContractModel(BaseModel):
    """Strict, immutable base for the package's serialized contracts."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _FrozenDict(dict[str, str]):
    """A JSON-serializable mapping that cannot be changed after issuance."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("issued citation maps are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _token(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if not value or len(value) > 128 or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")
    return value


def _bounded_text(value: object, *, name: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its limit")
    return value


def _optional_text(value: object, *, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, name=name, maximum=maximum, required=True)


def _finite_score(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if abs(value) > 1_000_000_000:
        raise ValueError(f"{name} exceeds its limit")
    return value


def _page(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 0 or value > 10_000_000:
        raise ValueError(f"{name} exceeds its limit")
    return value


class EvidenceScope(_ContractModel):
    """The complete authorization and collection scope of an evidence item."""

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)

    @field_validator("tenant_id", "workspace_id", "collection_id", mode="before")
    @classmethod
    def validate_scope_token(cls, value: object, info) -> str:
        return _token(value, name=info.field_name)


def _evidence_payload(value: object) -> dict[str, Any]:
    return {name: _read(value, name) for name in _EVIDENCE_DIGEST_FIELDS}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def server_evidence_id(value: object) -> str:
    """Return the deterministic identifier the server assigns to evidence."""

    digest = hashlib.sha256(_canonical_json(_evidence_payload(value))).hexdigest()
    return f"ev_{digest[:32]}"


def _bundle_payload(value: object) -> dict[str, Any]:
    return {
        "tenant_id": _read(value, "tenant_id"),
        "workspace_id": _read(value, "workspace_id"),
        "collection_id": _read(value, "collection_id"),
        "query": _read(value, "query"),
        "evidence_ids": [
            _read(item, "evidence_id")
            for item in (_read(value, "evidence", ()) or ())
        ],
    }


def server_bundle_id(value: object) -> str:
    """Return the deterministic identifier the server assigns to a bundle."""

    digest = hashlib.sha256(_canonical_json(_bundle_payload(value))).hexdigest()
    return f"eb_{digest[:32]}"


class Evidence(_ContractModel):
    """A server-issued excerpt with complete source provenance.

    Callers should use :meth:`issue` or :class:`rick_evidence.EvidenceValidator`
    to construct this model.  The post-validation digest check also rejects a
    caller-supplied identifier that does not match the complete server-owned
    evidence payload.
    """

    contract_version: Literal[EVIDENCE_CONTRACT_VERSION] = EVIDENCE_CONTRACT_VERSION
    evidence_id: str = Field(min_length=35, max_length=35, pattern=_EVIDENCE_ID.pattern)

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)

    source: str = Field(min_length=1, max_length=_MAX_SOURCE_CHARS)
    page_start: int | None = Field(default=None, ge=0, le=10_000_000)
    page_end: int | None = Field(default=None, ge=0, le=10_000_000)
    section: str | None = Field(default=None, max_length=_MAX_SECTION_CHARS)
    checksum: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=_MAX_TEXT_CHARS)

    retrieval_score: float
    reranking_score: float

    @field_validator(
        "tenant_id",
        "workspace_id",
        "collection_id",
        "document_id",
        "document_version",
        "chunk_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: object, info) -> str:
        return _token(value, name=info.field_name)

    @field_validator("source", "checksum", mode="before")
    @classmethod
    def validate_required_reference(cls, value: object, info) -> str:
        return _bounded_text(value, name=info.field_name, maximum=2_000 if info.field_name == "source" else 256)

    @field_validator("text", mode="before")
    @classmethod
    def validate_excerpt(cls, value: object) -> str:
        return _bounded_text(value, name="text", maximum=_MAX_TEXT_CHARS)

    @field_validator("section", mode="before")
    @classmethod
    def validate_section(cls, value: object) -> str | None:
        return _optional_text(value, name="section", maximum=_MAX_SECTION_CHARS)

    @field_validator("page_start", "page_end", mode="before")
    @classmethod
    def validate_page(cls, value: object, info) -> int | None:
        return _page(value, name=info.field_name)

    @field_validator("retrieval_score", "reranking_score", mode="before")
    @classmethod
    def validate_score(cls, value: object, info) -> float:
        return _finite_score(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_server_identity_and_pages(self) -> "Evidence":
        if self.page_start is not None and self.page_end is not None and self.page_end < self.page_start:
            raise ValueError("page_end must not precede page_start")
        if self.evidence_id != server_evidence_id(self):
            raise ValueError("evidence_id must be server-generated")
        return self

    @classmethod
    def issue(
        cls,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        document_id: str,
        document_version: str,
        chunk_id: str,
        source: str,
        checksum: str,
        text: str,
        page_start: int | None = None,
        page_end: int | None = None,
        section: str | None = None,
        retrieval_score: float = 0.0,
        reranking_score: float = 0.0,
    ) -> "Evidence":
        """Issue an evidence object and generate its identifier server-side."""

        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "document_id": document_id,
            "document_version": document_version,
            "chunk_id": chunk_id,
            "source": source,
            "page_start": page_start,
            "page_end": page_end,
            "section": section,
            "checksum": checksum,
            "text": text,
            "retrieval_score": retrieval_score,
            "reranking_score": reranking_score,
        }
        # Normalize the same values that field validators normalize before
        # hashing.  Validation still happens again in model_validate below.
        for name in (
            "tenant_id",
            "workspace_id",
            "collection_id",
            "document_id",
            "document_version",
            "chunk_id",
        ):
            payload[name] = _token(payload[name], name=name)
        payload["source"] = _bounded_text(payload["source"], name="source", maximum=_MAX_SOURCE_CHARS)
        payload["checksum"] = _bounded_text(payload["checksum"], name="checksum", maximum=256)
        payload["text"] = _bounded_text(payload["text"], name="text", maximum=_MAX_TEXT_CHARS)
        payload["section"] = _optional_text(payload["section"], name="section", maximum=_MAX_SECTION_CHARS)
        payload["page_start"] = _page(payload["page_start"], name="page_start")
        payload["page_end"] = _page(payload["page_end"], name="page_end")
        payload["retrieval_score"] = _finite_score(payload["retrieval_score"], name="retrieval_score")
        payload["reranking_score"] = _finite_score(payload["reranking_score"], name="reranking_score")
        payload["evidence_id"] = server_evidence_id(payload)
        return cls.model_validate(payload)

    @property
    def scope(self) -> EvidenceScope:
        return EvidenceScope(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
        )

    @property
    def citation_marker(self) -> str:
        """The only citation marker that can resolve to this evidence."""

        return f"[cite:{self.evidence_id}]"

    @property
    def page(self) -> int | None:
        """Compatibility view for sources that expose one page number."""

        return self.page_start


class EvidenceBundle(_ContractModel):
    """A server-issued, single-scope collection of evidence and citations."""

    contract_version: Literal[EVIDENCE_BUNDLE_CONTRACT_VERSION] = EVIDENCE_BUNDLE_CONTRACT_VERSION
    bundle_id: str = Field(min_length=35, max_length=35, pattern=_BUNDLE_ID.pattern)

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple, max_length=100)
    citation_map: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("tenant_id", "workspace_id", "collection_id", mode="before")
    @classmethod
    def validate_scope_token(cls, value: object, info) -> str:
        return _token(value, name=info.field_name)

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, value: object) -> str:
        return _bounded_text(value, name="query", maximum=_MAX_QUERY_CHARS)

    @model_validator(mode="after")
    def validate_scope_citations_and_identity(self) -> "EvidenceBundle":
        expected_scope = (self.tenant_id, self.workspace_id, self.collection_id)
        evidence_ids: list[str] = []
        for item in self.evidence:
            if (item.tenant_id, item.workspace_id, item.collection_id) != expected_scope:
                raise ValueError("all evidence must share the bundle scope")
            evidence_ids.append(item.evidence_id)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate evidence identifiers are not allowed")
        expected_map = {identifier: f"[cite:{identifier}]" for identifier in evidence_ids}
        if self.citation_map != expected_map:
            raise ValueError("citation_map must be server-generated from bundle evidence")
        if self.bundle_id != server_bundle_id(self):
            raise ValueError("bundle_id must be server-generated")
        object.__setattr__(self, "citation_map", _FrozenDict(self.citation_map))
        return self

    @classmethod
    def build(
        cls,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        query: str,
        evidence: tuple[Evidence, ...] | list[Evidence] = (),
    ) -> "EvidenceBundle":
        """Build a bundle and derive its ID and citation map on the server."""

        items = tuple(evidence)
        normalized_tenant_id = _token(tenant_id, name="tenant_id")
        normalized_workspace_id = _token(workspace_id, name="workspace_id")
        normalized_collection_id = _token(collection_id, name="collection_id")
        normalized_query = _bounded_text(query, name="query", maximum=_MAX_QUERY_CHARS)
        payload: dict[str, Any] = {
            "tenant_id": normalized_tenant_id,
            "workspace_id": normalized_workspace_id,
            "collection_id": normalized_collection_id,
            "query": normalized_query,
            "evidence": items,
        }
        identifiers = [item.evidence_id for item in items if isinstance(item, Evidence)]
        if len(identifiers) != len(items):
            raise TypeError("evidence must contain Evidence objects")
        payload["bundle_id"] = server_bundle_id(payload)
        payload["citation_map"] = {
            identifier: f"[cite:{identifier}]" for identifier in identifiers
        }
        return cls.model_validate(payload)

    @classmethod
    def issue(cls, **kwargs: Any) -> "EvidenceBundle":
        """Alias emphasizing that bundles are issued by the server boundary."""

        return cls.build(**kwargs)

    @classmethod
    def build_from_scope(
        cls,
        *,
        scope: EvidenceScope,
        query: str,
        evidence: tuple[Evidence, ...] | list[Evidence] = (),
    ) -> "EvidenceBundle":
        """Build a bundle from the typed scope used by the evidence adapter."""

        return cls.build(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            collection_id=scope.collection_id,
            query=query,
            evidence=evidence,
        )

    @property
    def scope(self) -> EvidenceScope:
        return EvidenceScope(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
        )

    @property
    def citation_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    def citation_for(self, evidence_id: str) -> str | None:
        return self.citation_map.get(evidence_id)


__all__ = [
    "EVIDENCE_BUNDLE_CONTRACT_VERSION",
    "EVIDENCE_CONTRACT_VERSION",
    "Evidence",
    "EvidenceBundle",
    "EvidenceScope",
    "server_bundle_id",
    "server_evidence_id",
]

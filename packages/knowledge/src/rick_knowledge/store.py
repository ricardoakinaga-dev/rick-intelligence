"""Knowledge store protocol + hermetic in-memory implementation.

Lifecycle: draft → processing → published; unpublish keeps metadata+index refs
but excludes from retrieval; delete removes metadata, chunks and index refs
(no orphaned chunks). Upsert by stable IDs is idempotent.
"""

from __future__ import annotations

from rick_knowledge.publication import PublicationStore
from rick_knowledge.fencing import OwnershipLostError
from asyncio import CancelledError

from typing import ContextManager, Iterable, Protocol
from copy import deepcopy
from threading import RLock
from rick_knowledge.fencing import catalog_collection_ids, select_catalog_collection, collection_guard_key, collection_mutation, document_mutation, require_deleted_snapshot, require_unchanged_tombstone

from rick_knowledge.models import DOCUMENT_STATUSES, Chunk, Collection, Document, materialize_lineage


class KnowledgeStore(Protocol):
    def get_ingestion_checkpoint(self, job_id: str, *, tenant_id: str, workspace_id: str, collection_id: str) -> dict | None: ...
    def begin_ingestion_checkpoint(self, job: object) -> dict: ...
    def save_ingestion_checkpoint(self, job: object, *, fingerprint: dict, artifacts: dict) -> dict: ...
    def finish_ingestion_checkpoint(self, job: object) -> None: ...
    def request_ingestion_cancel(self, job: object) -> None: ...
    def begin_publication(self, job: object, *, document_attempt: str | None = None, ready_count: int = 0) -> None: ...
    def publication_decision_guard(self, record: dict) -> ContextManager: ...
    def save_publication_snapshot(self, job: object) -> None: ...
    def get_publication(self, job_id: str, *, tenant_id: str, workspace_id: str,
                        collection_id: str) -> dict | None: ...
    def resolve_publication(self, record: dict, outcome: str) -> dict: ...
    def request_publication_cancel(self, job: object) -> None: ...
    def mutation_guard(self, key: str) -> ContextManager: ...
    def collection_guard(self, *, tenant_id: str, workspace_id: str, collection_id: str) -> ContextManager: ...
    def ensure_collection(self, collection: Collection) -> Collection: ...
    def restore_deleted_document(self, snapshot: Document, chunks: list[Chunk]) -> None: ...
    def upsert_collection(self, collection: Collection) -> None: ...
    def get_collection(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        tenant_id: str,
    ) -> Collection | None: ...
    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]: ...
    def upsert_document(self, document: Document) -> None: ...
    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None: ...
    def list_documents(
        self,
        workspace_id: str,
        collection_id: str | None = None,
        *,
        tenant_id: str,
        after_document_id: str | None = None,
        limit: int | None = None,
        statuses: Iterable[str] | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]: ...
    def set_document_status(self, document_id: str, status: str) -> None: ...
    def delete_document(self, document_id: str) -> int: ...
    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None: ...
    def get_chunks(self, document_id: str) -> list[Chunk]: ...


class InMemoryKnowledgeStore(PublicationStore):
    def __init__(self) -> None:
        # Tenant is part of collection identity. A workspace and collection
        # name may legitimately be reused by independent tenants.
        self._collections: dict[tuple[str, str, str], Collection] = {}
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, list[Chunk]] = {}
        self._tombstones: set[str] = set()
        self._mutation_lock = RLock()
        self._publications = {}
        self._ingestion_checkpoints = {}
        self._publication_lock = RLock()

    def ingestion_checkpoint_guard(self, job):
        return self._publication_lock

    def _read_ingestion_checkpoint(self, job_id, tenant_id, workspace_id, collection_id):
        with self._publication_lock:
            return deepcopy(self._ingestion_checkpoints.get((tenant_id, workspace_id, collection_id, job_id)))

    def _write_ingestion_checkpoint(self, record):
        from rick_knowledge.publication import encode_checkpoint
        encode_checkpoint(record)
        with self._publication_lock:
            key = tuple(record[k] for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id'))
            self._ingestion_checkpoints[key] = deepcopy(record)

    def _read_publication(self, job_id, tenant_id, workspace_id, collection_id):
        with self._publication_lock:
            return deepcopy(self._publications.get((tenant_id, workspace_id, collection_id, job_id)))

    def _write_publication(self, record):
        with self._publication_lock:
            key = tuple(record[k] for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id'))
            candidate = deepcopy(record)
            current = self._publications.get(key)
            if current and current['attempt_id'] == candidate['attempt_id']:
                if current['outcome'] != 'pending':
                    candidate['outcome'] = current['outcome']
                candidate['cancel_requested'] = candidate['cancel_requested'] or current['cancel_requested']
                if candidate['cancel_requested'] and candidate['outcome'] == 'failed':
                    candidate['outcome'] = 'cancelled'
            self._publications[key] = candidate

    def _mark_publication_cancel(self, job):
        with self._publication_lock:
            record = self._publications.get((job.tenant_id, job.workspace_id, job.collection_id, job.job_id))
            if record and record['attempt_id'] == job.metadata['publication_attempt'] and record['outcome'] == 'pending':
                record['cancel_requested'] = True

    def publication_decision_guard(self, record):
        return self._publication_lock

    def mutation_guard(self, key: str):
        """Shared by every pipeline using this store, including compensation."""
        return self._mutation_lock

    def collection_guard(self, *, tenant_id: str, workspace_id: str, collection_id: str):
        return self.mutation_guard(collection_guard_key(tenant_id=tenant_id,
            workspace_id=workspace_id, collection_id=collection_id))

    @collection_mutation
    def ensure_collection(self, collection: Collection) -> Collection:
        with self._mutation_lock:
            key = (collection.tenant_id, collection.workspace_id, collection.collection_id)
            if key not in self._collections:
                if collection.status not in {"active", "archived"}:
                    raise ValueError("unknown collection status")
                # The alias decorator has already chosen the new physical
                # parent. Re-entering upsert could select the historical row.
                self._collections[key] = deepcopy(collection)
            return deepcopy(self._collections[key])

    def restore_deleted_document(self, snapshot: Document, chunks: list[Chunk]) -> None:
        """Explicit maintenance seam for a failed delete, never ordinary upsert."""
        with self.mutation_guard("document:" + snapshot.document_id):
            current = self.get_document(snapshot.document_id)
            snapshot = require_deleted_snapshot(current, snapshot)
            before, before_chunks = deepcopy(current), self.get_chunks(snapshot.document_id)
            self._tombstones.discard(snapshot.document_id)
            self._documents[snapshot.document_id] = deepcopy(snapshot)
            try:
                self.replace_document_chunks(snapshot.document_id, chunks)
            except (Exception, CancelledError):
                self._documents[snapshot.document_id] = before
                self._chunks[snapshot.document_id] = before_chunks
                self._tombstones.add(snapshot.document_id)
                raise

    @collection_mutation
    def upsert_collection(self, collection: Collection) -> None:
        if collection.status not in {"active", "archived"}:
            raise ValueError("unknown collection status")
        with self._mutation_lock:
            self._collections[(collection.tenant_id, collection.workspace_id, collection.collection_id)] = deepcopy(collection)

    def get_collection(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        tenant_id: str,
    ) -> Collection | None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        with self._mutation_lock:
            return select_catalog_collection(
                [self._collections.get((tenant_id.strip(), workspace_id, key))
                 for key in catalog_collection_ids(collection_id)], collection_id)

    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        tenant = tenant_id.strip()
        return sorted(
            (
                deepcopy(c) for c in list(self._collections.values())
                if c.workspace_id == workspace_id and c.tenant_id == tenant
            ),
            key=lambda c: c.collection_id,
        )

    @document_mutation
    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {document.status}")
        existing = self._documents.get(document.document_id)
        if (document.document_id in self._tombstones or (existing and existing.status == "deleted")) and document.status != "deleted":
            raise ValueError("deleted documents cannot transition; ingest a new version")
        if existing and (
            existing.tenant_id != document.tenant_id
            or existing.workspace_id != document.workspace_id
            or existing.collection_id != document.collection_id
        ):
            raise ValueError("document scope cannot change")
        materialize_lineage(document, published=document.status == "published")
        if existing and existing.status == "deleted":
            document = require_unchanged_tombstone(existing, document)
        self._documents[document.document_id] = deepcopy(document) if document.status == "deleted" else document
        if document.status == "deleted":
            self._tombstones.add(document.document_id)

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        if document_id in self._tombstones:
            document.status = "deleted"
        if tenant_id is not None and document.tenant_id != tenant_id:
            return None
        if workspace_id is not None and document.workspace_id != workspace_id:
            return None
        return deepcopy(document) if document.status == "deleted" else document

    def list_documents(
        self,
        workspace_id: str,
        collection_id: str | None = None,
        *,
        tenant_id: str,
        after_document_id: str | None = None,
        limit: int | None = None,
        statuses: Iterable[str] | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]:
        """Return visible documents in one workspace, in stable order.

        Deleted documents remain as tombstones so their stable identity cannot
        be resurrected accidentally, but they are not part of a read/list
        surface. Collection filtering is optional for application-level ACL
        narrowing.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        tenant = tenant_id.strip()
        status_filter = set(statuses) if statuses is not None else None
        collection_scope = set(allowed_collection_ids) if allowed_collection_ids is not None else None
        documents = sorted(
            (
                document
                for document in self._documents.values()
                if document.workspace_id == workspace_id
                and document.tenant_id == tenant
                and (collection_id is None or document.collection_id == collection_id)
                and (
                    collection_scope is None
                    or "*" in collection_scope
                    or document.collection_id in collection_scope
                )
                and document.status != "deleted"
                and document.document_id not in self._tombstones
                and (status_filter is None or document.status in status_filter)
            ),
            key=lambda document: document.document_id,
        )
        if after_document_id is not None:
            documents = [document for document in documents if document.document_id > after_document_id]
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise ValueError("limit must be a non-negative integer")
            documents = documents[:limit]
        return documents

    @document_mutation
    def set_document_status(self, document_id: str, status: str) -> None:
        if status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {status}")
        document = self._documents.get(document_id)
        if document is None:
            raise KeyError(document_id)
        with self._publication_lock:
            if status == 'published' and any(r['outcome'] == 'pending' and r['cancel_requested']
                    and self._publication_matches(r, document) for r in self._publications.values()):
                raise OwnershipLostError('publication cancelled before commit')
            # No resurrection of deleted documents; no published<-deleted shortcuts.
            if (document_id in self._tombstones or document.status == "deleted") and status != "deleted":
                raise ValueError("deleted documents cannot transition; ingest a new version")
            if status == "deleted":
                document = self._documents[document_id] = deepcopy(document)
            # Prepare receipt facts before mutating the document so a rejected
            # snapshot cannot leave a partial in-memory publication.
            decisions = [(record, self._committed_publication(record))
                for record in self._publications.values()
                if status == 'published' and record['outcome'] == 'pending'
                and self._publication_matches(record, document)]
            document.status = status
            if status == "deleted":
                self._tombstones.add(document_id)
            materialize_lineage(document, published=status == "published")
            for record, committed in decisions:
                record.update(committed)

    @document_mutation
    def delete_document(self, document_id: str) -> int:
        chunks = self._chunks.pop(document_id, [])
        document = self._documents.get(document_id)
        if document is not None:
            document = self._documents[document_id] = deepcopy(document)
            document.status = "deleted"
            self._tombstones.add(document_id)
        return len(chunks)

    @document_mutation
    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        document = self._documents.get(document_id)
        if document is None:
            raise KeyError(document_id)
        if (document_id in self._tombstones or document.status == "deleted") and chunks:
            raise ValueError("deleted documents cannot receive chunks")
        for chunk in chunks:
            if chunk.document_id != document_id:
                raise ValueError("chunk document_id does not match parent")
            if chunk.tenant_id != document.tenant_id:
                raise ValueError("chunk tenant_id does not match parent")
        self._chunks[document_id] = list(chunks)

    def get_chunks(self, document_id: str) -> list[Chunk]:
        return list(self._chunks.get(document_id, []))

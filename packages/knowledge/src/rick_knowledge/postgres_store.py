"""DB-API PostgreSQL knowledge adapter.

The domain package does not import psycopg or open a socket. A connection
factory is injected by the application composition root, which keeps startup
and tests deterministic while still giving production a transactional store.
Every read carries tenant and workspace scope at the SQL boundary.
"""

from __future__ import annotations

from rick_knowledge.publication import PublicationStore
from rick_knowledge.fencing import OwnershipLostError
from asyncio import CancelledError
import json

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol
from threading import local

from rick_knowledge.json_boundary import decode_metadata, encode_metadata
from rick_knowledge.fencing import catalog_collection_ids, select_catalog_collection, advisory_key, collection_guard_key, collection_mutation, document_mutation, require_deleted_snapshot, require_unchanged_tombstone
from rick_knowledge.models import (
    DOCUMENT_STATUSES,
    Chunk,
    Collection,
    Document,
    _timestamp_text,
    materialize_lineage,
)


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresKnowledgeError(RuntimeError):
    """Stable adapter failure without retaining database details."""

    def __init__(self, code: str = "storage_unavailable") -> None:
        self.code = code if code in {"storage_unavailable", "invalid_input", "not_found", "conflict"} else "storage_unavailable"
        super().__init__(self.code)


def _json_value(value: object) -> dict[str, object] | None:
    return decode_metadata(value)


def _row_timestamp(value: object) -> str | None:
    try:
        return _timestamp_text(value)
    except ValueError:
        return None


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names: list[str] = []
    for item in description:
        name = getattr(item, "name", None)
        if not isinstance(name, str) and isinstance(item, (tuple, list)) and item:
            name = item[0]
        if isinstance(name, str):
            names.append(name)
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _bounded_limit(value: int | None, *, default: int = 100, maximum: int = 1_000) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise PostgresKnowledgeError("invalid_input")
    return value


class PostgresKnowledgeStore(PublicationStore):
    """Transactional implementation of the canonical ``KnowledgeStore`` port."""

    def __init__(
        self,
        connection_factory: Callable[[], DbConnection],
        *,
        created_by: str | None = None,
        close_connections: bool = True,
        max_page_size: int = 1_000,
    ) -> None:
        if not callable(connection_factory):
            raise PostgresKnowledgeError("invalid_input")
        if not isinstance(max_page_size, int) or isinstance(max_page_size, bool) or not 1 <= max_page_size <= 10_000:
            raise PostgresKnowledgeError("invalid_input")
        if created_by is not None and (not isinstance(created_by, str) or not created_by.strip() or len(created_by) > 256):
            raise PostgresKnowledgeError("invalid_input")
        self._connection_factory = connection_factory
        self._created_by = created_by.strip() if isinstance(created_by, str) else None
        self._close_connections = close_connections
        self._max_page_size = max_page_size
        self._guards = local()
        self._restore_sessions = local()

    def restore_deleted_document(self, snapshot: Document, chunks: list[Chunk]) -> None:
        with self.mutation_guard("document:" + snapshot.document_id):
            with self._session(write=True) as (connection, cursor):
                self._execute(cursor, "SELECT * FROM rick_documents WHERE document_id=%s FOR UPDATE",
                              (snapshot.document_id,))
                row = self._fetchone(cursor)
                try:
                    snapshot = require_deleted_snapshot(self._document(row) if row else None, snapshot)
                except ValueError:
                    raise PostgresKnowledgeError("conflict") from None
                inherited = getattr(self._restore_sessions, "connection", None)
                self._restore_sessions.connection = connection
                try:
                    self._execute(cursor, "UPDATE rick_documents SET status=%s WHERE document_id=%s",
                                  (snapshot.status, snapshot.document_id))
                    self.replace_document_chunks(snapshot.document_id, chunks)
                finally:
                    self._restore_sessions.connection = inherited

    @contextmanager
    def ingestion_checkpoint_guard(self, job):
        # Serialize absent-row claims as well as updates. The inherited session
        # makes intent creation and cancellation propagation one PG transaction.
        with self._session(write=True) as (connection, cursor):
            key = json.dumps([job.tenant_id, job.workspace_id, job.collection_id, job.job_id])
            self._execute(cursor, "SET LOCAL statement_timeout = '5000ms'")
            self._execute(cursor, "SELECT pg_advisory_xact_lock(%s)", (advisory_key('ingestion-checkpoint:' + key),))
            inherited = getattr(self._restore_sessions, 'connection', None)
            self._restore_sessions.connection = connection
            try:
                yield
            finally:
                self._restore_sessions.connection = inherited

    def _read_ingestion_checkpoint(self, job_id, tenant_id, workspace_id, collection_id):
        with self._session() as (_, cursor):
            self._execute(cursor, "SET LOCAL statement_timeout = '5000ms'")
            self._execute(cursor, """SELECT record FROM rick_ingestion_checkpoints
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s AND job_id=%s""",
                (tenant_id, workspace_id, collection_id, job_id))
            row = self._fetchone(cursor)
            return row['record'] if row else None

    def _write_ingestion_checkpoint(self, record):
        from rick_knowledge.publication import encode_checkpoint
        encoded = encode_checkpoint(record)
        with self._session(write=True) as (_, cursor):
            self._execute(cursor, """INSERT INTO rick_ingestion_checkpoints
                (tenant_id, workspace_id, collection_id, job_id, record)
                VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
                ON CONFLICT(tenant_id, workspace_id, collection_id, job_id)
                DO UPDATE SET record=excluded.record""",
                (*[record[k] for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id')], encoded))

    def _read_publication(self, job_id, tenant_id, workspace_id, collection_id):
        with self._session() as (_, cursor):
            self._execute(cursor, "SET LOCAL statement_timeout = '5000ms'")
            self._execute(cursor, """SELECT tenant_id, workspace_id, collection_id, job_id,
                document_id, attempt_id, document_attempt, outcome, cancel_requested, ready_count, job_snapshot FROM rick_publication_receipts
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s AND job_id=%s""",
                (tenant_id, workspace_id, collection_id, job_id))
            return self._fetchone(cursor)

    def _publication_commit_time(self):
        # resolve_publication inherits the row-locked decision transaction.
        with self._session() as (_, cursor):
            self._execute(cursor, 'SELECT EXTRACT(EPOCH FROM clock_timestamp())::double precision AS finished_at')
            return self._fetchone(cursor)['finished_at']

    def _write_publication(self, record):
        keys = ('tenant_id', 'workspace_id', 'collection_id', 'job_id', 'document_id',
                'attempt_id', 'document_attempt', 'outcome', 'cancel_requested', 'ready_count', 'job_snapshot')
        with self._session(write=True) as (_, cursor):
            self._execute(cursor, "SET LOCAL statement_timeout = '5000ms'")
            self._execute(cursor, """INSERT INTO rick_publication_receipts
                (tenant_id, workspace_id, collection_id, job_id, document_id, attempt_id, document_attempt, outcome, cancel_requested, ready_count, job_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
                ON CONFLICT(tenant_id, workspace_id, collection_id, job_id) DO UPDATE SET
                document_id=excluded.document_id, attempt_id=excluded.attempt_id,
                document_attempt=excluded.document_attempt, ready_count=excluded.ready_count, job_snapshot=excluded.job_snapshot,
                outcome=CASE WHEN rick_publication_receipts.attempt_id=excluded.attempt_id AND rick_publication_receipts.outcome<>'pending'
                    THEN rick_publication_receipts.outcome WHEN rick_publication_receipts.attempt_id=excluded.attempt_id
                    AND rick_publication_receipts.cancel_requested AND excluded.outcome='failed'
                    THEN 'cancelled' ELSE excluded.outcome END,
                cancel_requested=excluded.cancel_requested OR
                    (rick_publication_receipts.attempt_id=excluded.attempt_id AND rick_publication_receipts.cancel_requested)""",
                tuple(encode_metadata(record[k]) if k == 'job_snapshot' else record[k] for k in keys))

    @contextmanager
    def publication_decision_guard(self, record):
        # Lock the receipt row so request-only cancellation and the document
        # commit have a single transaction winner, without needing a lease.
        with self._session(write=True) as (connection, cursor):
            self._execute(cursor, """SELECT attempt_id FROM rick_publication_receipts
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s AND job_id=%s FOR UPDATE""",
                tuple(record[k] for k in ('tenant_id','workspace_id','collection_id','job_id')))
            row = self._fetchone(cursor)
            if row is None or row['attempt_id'] != record['attempt_id']:
                raise OwnershipLostError('publication attempt changed')
            inherited = getattr(self._restore_sessions, 'connection', None)
            self._restore_sessions.connection = connection
            try:
                yield
            finally:
                self._restore_sessions.connection = inherited

    def _mark_publication_cancel(self, job):
        with self._session(write=True) as (_, cursor):
            self._execute(cursor, "SET LOCAL statement_timeout = '5000ms'")
            self._execute(cursor, """UPDATE rick_publication_receipts SET cancel_requested=TRUE
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s AND job_id=%s
                AND attempt_id=%s AND outcome='pending'""",
                (job.tenant_id, job.workspace_id, job.collection_id, job.job_id,
                 job.metadata['publication_attempt']))

    @contextmanager
    def mutation_guard(self, key: str):
        """Session advisory lock across committed knowledge and vector effects.

        The injected factory must provide a dedicated connection for this guard.
        Nested calls on this adapter/thread reuse the lock; ordinary write sessions
        remain short and commit independently. No migration is required.
        """
        held = getattr(self._guards, "held", None)
        if held is None:
            held = self._guards.held = set()
        if key in held:
            yield
            return
        connection = None
        cursor = None
        acquired = False
        try:
            try:
                connection = self._connection_factory()
                cursor = connection.cursor()
                self._execute(cursor, "SET LOCAL statement_timeout = '15000ms'")
                self._execute(cursor, "SELECT pg_advisory_lock(%s)", (advisory_key(key),))
                acquired = True
            except Exception:
                raise PostgresKnowledgeError() from None
            held.add(key)
            yield
        finally:
            held.discard(key)
            try:
                if connection is not None:
                    connection.rollback()
                if acquired:
                    self._execute(cursor, "SELECT pg_advisory_unlock(%s)", (advisory_key(key),))
                    connection.rollback()
            except Exception:
                # A connection whose lock could not be released cannot safely
                # return to a pool, even in close_connections=False mode.
                if connection is not None:
                    connection.close()
                raise PostgresKnowledgeError() from None
            finally:
                try:
                    if cursor is not None:
                        close_cursor = getattr(cursor, "close", None)
                        if callable(close_cursor):
                            close_cursor()
                finally:
                    if connection is not None and self._close_connections:
                        connection.close()

    def collection_guard(self, *, tenant_id: str, workspace_id: str, collection_id: str):
        return self.mutation_guard(collection_guard_key(tenant_id=tenant_id,
            workspace_id=workspace_id, collection_id=collection_id))

    @collection_mutation
    def ensure_collection(self, collection: Collection) -> Collection:
        if collection.status not in {"active", "archived"} or collection.version <= 0:
            raise PostgresKnowledgeError("invalid_input")
        try:
            metadata_json = encode_metadata(collection.metadata)
        except ValueError:
            raise PostgresKnowledgeError("invalid_input") from None
        creator = self._creator(collection.metadata, self._created_by)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                INSERT INTO rick_collections
                    (tenant_id, workspace_id, collection_id, title, description, status, version, created_by, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
                ON CONFLICT (tenant_id, workspace_id, collection_id) DO NOTHING
            """, (collection.tenant_id, collection.workspace_id, collection.collection_id,
                   collection.title, collection.description, collection.status, collection.version,
                   creator, metadata_json))
            self._execute(cursor, """
                SELECT tenant_id, workspace_id, collection_id, title, description, status, version, metadata
                FROM rick_collections WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s
            """, (collection.tenant_id, collection.workspace_id, collection.collection_id))
            row = self._fetchone(cursor)
            result = self._collection(row) if row else None
            if result is None:
                raise PostgresKnowledgeError("conflict")
            return result

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        inherited = getattr(self._restore_sessions, "connection", None)
        if inherited is not None:
            cursor = inherited.cursor()
            try:
                yield inherited, cursor
            finally:
                close_cursor = getattr(cursor, "close", None)
                if callable(close_cursor):
                    close_cursor()
            return
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresKnowledgeError()
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except (CancelledError, SystemExit, KeyboardInterrupt):
            # Preserve the supported signal after rolling back our own write
            # transaction. A borrowed transaction remains the owner's duty.
            if write and connection is not None:
                connection.rollback()
            raise
        except (PostgresKnowledgeError, OwnershipLostError):
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresKnowledgeError() from None
        finally:
            if cursor is not None:
                close_cursor = getattr(cursor, "close", None)
                if callable(close_cursor):
                    try:
                        close_cursor()
                    except Exception:
                        pass
            if self._close_connections and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise PostgresKnowledgeError()
        execute(query, params)

    @staticmethod
    def _fetchone(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _fetchall(cursor: object) -> list[dict[str, object]]:
        rows = getattr(cursor, "fetchall", lambda: [])()
        return [_row_dict(cursor, row) for row in rows]

    @staticmethod
    def _creator(metadata: Mapping[str, object], fallback: str | None) -> str:
        value = metadata.get("created_by") or fallback
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
            raise PostgresKnowledgeError("invalid_input")
        return value.strip()

    @staticmethod
    def _collection(row: Mapping[str, object]) -> Collection | None:
        metadata = _json_value(row.get("metadata"))
        if metadata is None:
            return None
        return Collection(
            tenant_id=str(row.get("tenant_id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            collection_id=str(row.get("collection_id") or ""),
            title=str(row.get("title") or ""),
            description=str(row.get("description") or ""),
            status=str(row.get("status") or "active"),
            version=int(row.get("version") or 1),
            metadata=metadata,
        )

    @staticmethod
    def _document(row: Mapping[str, object]) -> Document | None:
        metadata = _json_value(row.get("metadata"))
        if metadata is None:
            return None
        return Document(
            document_id=str(row.get("document_id") or ""),
            tenant_id=str(row.get("tenant_id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            collection_id=str(row.get("collection_id") or ""),
            document_version=str(row.get("document_version") or ""),
            content_checksum=str(row.get("content_checksum") or ""),
            filename=str(row.get("filename") or row.get("object_key") or ""),
            display_filename=str(row.get("display_filename") or ""),
            title=str(row.get("title") or ""),
            source_type=str(row.get("source_type") or ""),
            mime_type=str(row.get("mime_type") or ""),
            language=row.get("language") if isinstance(row.get("language"), str) else None,
            status=str(row.get("status") or "draft"),
            parser_version=str(row.get("parser_version") or ""),
            chunker_version=str(row.get("chunker_version") or ""),
            embedding_model=str(row.get("embedding_model") or ""),
            embedding_version=str(row.get("embedding_version") or ""),
            metadata=metadata,
            ingestion_version=str(row.get("ingestion_version") or row.get("document_version") or ""),
            object_ref=str(
                row.get("object_ref")
                or row.get("object_key")
                or row.get("filename")
                or row.get("display_filename")
                or ""
            ),
            created_at=_row_timestamp(row.get("created_at")),
            published_at=_row_timestamp(row.get("published_at")),
        )

    @staticmethod
    def _chunk(row: Mapping[str, object]) -> Chunk | None:
        metadata = _json_value(row.get("metadata"))
        if metadata is None:
            return None
        return Chunk(
            chunk_id=str(row.get("chunk_id") or ""),
            document_id=str(row.get("document_id") or ""),
            tenant_id=str(row.get("tenant_id") or ""),
            parent_chunk_id=row.get("parent_chunk_id") if isinstance(row.get("parent_chunk_id"), str) else None,
            chunk_index=int(row.get("chunk_index") or 0),
            text=str(row.get("text") or ""),
            page_start=row.get("page_start") if isinstance(row.get("page_start"), int) else None,
            page_end=row.get("page_end") if isinstance(row.get("page_end"), int) else None,
            section=row.get("section") if isinstance(row.get("section"), str) else None,
            heading=None,
            token_count=int(row.get("token_count") or 0),
            checksum=str(row.get("checksum") or ""),
            parser_version=str(row.get("parser_version") or ""),
            chunker_version=str(row.get("chunker_version") or ""),
            embedding_version=str(row.get("embedding_version") or ""),
            index_version=str(row.get("index_version") or ""),
            metadata=metadata,
        )

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._fetchone(cursor) is not None
        except PostgresKnowledgeError:
            return False

    @collection_mutation
    def upsert_collection(self, collection: Collection) -> None:
        if collection.status not in {"active", "archived"} or collection.version <= 0:
            raise PostgresKnowledgeError("invalid_input")
        if not isinstance(collection.metadata, Mapping):
            raise PostgresKnowledgeError("invalid_input")
        try:
            metadata_json = encode_metadata(collection.metadata)
        except ValueError:
            raise PostgresKnowledgeError("invalid_input") from None
        creator = self._creator(collection.metadata, self._created_by)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                INSERT INTO rick_collections
                    (tenant_id, workspace_id, collection_id, title, description, status, version, created_by, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
                ON CONFLICT (tenant_id, workspace_id, collection_id) DO UPDATE SET
                    title = EXCLUDED.title, description = EXCLUDED.description,
                    status = EXCLUDED.status, version = EXCLUDED.version,
                    metadata = EXCLUDED.metadata, updated_at = NOW()
            """, (collection.tenant_id, collection.workspace_id, collection.collection_id,
                   collection.title, collection.description, collection.status, collection.version, creator,
                   metadata_json))

    def get_collection(self, workspace_id: str, collection_id: str, *, tenant_id: str) -> Collection | None:
        keys = catalog_collection_ids(collection_id)
        if len(keys) > 1:
            with self._session() as (_connection, cursor):
                self._execute(cursor, """
                    SELECT tenant_id, workspace_id, collection_id, title, description, status, version, metadata
                    FROM rick_collections
                    WHERE tenant_id = %s AND workspace_id = %s AND collection_id = ANY(%s)
                """, (tenant_id, workspace_id, list(keys)))
                rows = self._fetchall(cursor)
            return select_catalog_collection([self._collection(row) for row in rows], collection_id)
        with self._session() as (_connection, cursor):
            self._execute(cursor, """
                SELECT tenant_id, workspace_id, collection_id, title, description, status, version, metadata
                FROM rick_collections
                WHERE tenant_id = %s AND workspace_id = %s AND collection_id = %s
            """, (tenant_id, workspace_id, collection_id))
            row = self._fetchone(cursor)
        return self._collection(row) if row else None

    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]:
        with self._session() as (_connection, cursor):
            self._execute(cursor, """
                SELECT tenant_id, workspace_id, collection_id, title, description, status, version, metadata
                FROM rick_collections
                WHERE tenant_id = %s AND workspace_id = %s
                ORDER BY collection_id
            """, (tenant_id, workspace_id))
            rows = self._fetchall(cursor)
        return [item for row in rows if (item := self._collection(row)) is not None]

    @document_mutation
    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise PostgresKnowledgeError("invalid_input")
        try:
            materialize_lineage(document, published=document.status == "published")
        except ValueError:
            raise PostgresKnowledgeError("invalid_input") from None
        if not isinstance(document.metadata, Mapping):
            raise PostgresKnowledgeError("invalid_input")
        creator = self._creator(document.metadata, self._created_by)
        metadata = dict(document.metadata or {})
        try:
            metadata_json = encode_metadata(metadata)
        except ValueError:
            raise PostgresKnowledgeError("invalid_input") from None
        object_key = str(metadata.get("object_key") or document.object_ref or document.filename or document.document_id)
        byte_size = metadata.get("byte_size", 0)
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise PostgresKnowledgeError("invalid_input")
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "SELECT * "
                         "FROM rick_documents WHERE document_id = %s FOR UPDATE", (document.document_id,))
            existing = self._fetchone(cursor)
            if existing and (
                existing.get("tenant_id") != document.tenant_id
                or existing.get("workspace_id") != document.workspace_id
                or existing.get("collection_id") != document.collection_id
            ):
                # A caller must never be able to move a document primary key
                # across scopes through an upsert.
                raise PostgresKnowledgeError("conflict")
            if existing and existing.get("status") == "deleted" and document.status != "deleted":
                raise PostgresKnowledgeError("conflict")
            if existing and existing.get("status") == "deleted":
                try:
                    document = require_unchanged_tombstone(self._document(existing), document)
                except ValueError:
                    raise PostgresKnowledgeError("conflict") from None
                return
            self._execute(cursor, """
                INSERT INTO rick_documents
                    (document_id, tenant_id, workspace_id, collection_id, document_version,
                     content_checksum, object_key, object_ref, ingestion_version, byte_size,
                     title, display_filename,
                     mime_type, status, parser_version, chunker_version, embedding_model,
                     embedding_version, created_by, filename, source_type, language, metadata,
                     created_at, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id, workspace_id = EXCLUDED.workspace_id,
                    collection_id = EXCLUDED.collection_id, document_version = EXCLUDED.document_version,
                    content_checksum = EXCLUDED.content_checksum, object_key = EXCLUDED.object_key,
                    object_ref = EXCLUDED.object_ref, ingestion_version = EXCLUDED.ingestion_version,
                    byte_size = EXCLUDED.byte_size, title = EXCLUDED.title,
                    display_filename = EXCLUDED.display_filename, mime_type = EXCLUDED.mime_type,
                    status = EXCLUDED.status, parser_version = EXCLUDED.parser_version,
                    chunker_version = EXCLUDED.chunker_version, embedding_model = EXCLUDED.embedding_model,
                    embedding_version = EXCLUDED.embedding_version, filename = EXCLUDED.filename,
                    source_type = EXCLUDED.source_type, language = EXCLUDED.language,
                    metadata = EXCLUDED.metadata,
                    published_at = CASE
                        WHEN EXCLUDED.status = 'published'
                          THEN COALESCE(EXCLUDED.published_at, rick_documents.published_at, NOW())
                        ELSE COALESCE(EXCLUDED.published_at, rick_documents.published_at)
                    END,
                    updated_at = NOW()
            """, (
                document.document_id, document.tenant_id, document.workspace_id, document.collection_id,
                document.document_version, document.content_checksum, object_key, document.object_ref,
                document.ingestion_version, byte_size,
                document.title, document.display_filename or document.filename, document.mime_type,
                document.status, document.parser_version, document.chunker_version,
                document.embedding_model, document.embedding_version, creator, document.filename,
                document.source_type, document.language, metadata_json,
                document.created_at, document.published_at,
            ))

    @staticmethod
    def _document_scope_where(
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[str, tuple[object, ...]]:
        if (tenant_id is None) != (workspace_id is None):
            raise PostgresKnowledgeError("invalid_input")
        if tenant_id is None:
            return "document_id = %s", (document_id,)
        return (
            "tenant_id = %s AND workspace_id = %s AND document_id = %s",
            (tenant_id, workspace_id, document_id),
        )

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None:
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"SELECT * FROM rick_documents WHERE {where}", params)
            row = self._fetchone(cursor)
        return self._document(row) if row else None

    def get_document_for_tenant(self, document_id: str, *, tenant_id: str) -> Document | None:
        """Resolve a document without widening beyond one tenant.

        This seam is used by platform administrators, who may be authorized
        to choose a different workspace after the document identity has been
        resolved. Workspace-sensitive mutations still require both values.
        """

        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise PostgresKnowledgeError("invalid_input")
        with self._session() as (_connection, cursor):
            self._execute(
                cursor,
                "SELECT * FROM rick_documents WHERE document_id = %s AND tenant_id = %s",
                (document_id, tenant_id),
            )
            row = self._fetchone(cursor)
        return self._document(row) if row else None

    def list_documents(
        self, workspace_id: str, collection_id: str | None = None, *, tenant_id: str,
        after_document_id: str | None = None, limit: int | None = None,
        statuses: Iterable[str] | None = None, allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]:
        result_limit = min(_bounded_limit(limit, default=100, maximum=self._max_page_size), self._max_page_size)
        clauses = ["tenant_id = %s", "workspace_id = %s", "status <> 'deleted'"]
        params: list[object] = [tenant_id, workspace_id]
        if collection_id is not None:
            clauses.append("collection_id = %s")
            params.append(collection_id)
        if statuses is not None:
            values = tuple(dict.fromkeys(statuses))
            if not values or any(status not in DOCUMENT_STATUSES for status in values):
                return []
            clauses.append("status = ANY(%s)")
            params.append(list(values))
        if allowed_collection_ids is not None:
            allowed = tuple(dict.fromkeys(allowed_collection_ids))
            if "*" not in allowed:
                if not allowed:
                    return []
                clauses.append("collection_id = ANY(%s)")
                params.append(list(allowed))
        if after_document_id is not None:
            clauses.append("document_id > %s")
            params.append(after_document_id)
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"SELECT * FROM rick_documents WHERE {' AND '.join(clauses)} ORDER BY document_id LIMIT %s", tuple(params + [result_limit]))
            rows = self._fetchall(cursor)
        return [item for row in rows if (item := self._document(row)) is not None]

    def count_documents(self, workspace_id: str, *, tenant_id: str, collection_id: str | None = None,
                        allowed_collection_ids: Iterable[str] | None = None) -> int:
        clauses = ["tenant_id = %s", "workspace_id = %s", "status <> 'deleted'"]
        params: list[object] = [tenant_id, workspace_id]
        if collection_id is not None:
            clauses.append("collection_id = %s")
            params.append(collection_id)
        if allowed_collection_ids is not None and "*" not in set(allowed_collection_ids):
            allowed = list(allowed_collection_ids)
            if not allowed:
                return 0
            clauses.append("collection_id = ANY(%s)")
            params.append(allowed)
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"SELECT COUNT(*) AS count FROM rick_documents WHERE {' AND '.join(clauses)}", tuple(params))
            row = self._fetchone(cursor)
        try:
            return max(0, int(row.get("count", 0))) if row else 0
        except (TypeError, ValueError):
            raise PostgresKnowledgeError() from None

    @document_mutation
    def set_document_status(
        self,
        document_id: str,
        status: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if status not in DOCUMENT_STATUSES:
            raise PostgresKnowledgeError("invalid_input")
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, f"SELECT status FROM rick_documents WHERE {where} FOR UPDATE", params)
            row = self._fetchone(cursor)
            if row is None:
                raise PostgresKnowledgeError("not_found")
            if row.get("status") == "deleted" and status != "deleted":
                raise PostgresKnowledgeError("conflict")
            if status == 'published':
                self._execute(cursor, """SELECT receipt.cancel_requested FROM rick_publication_receipts AS receipt
                    JOIN rick_documents AS document ON receipt.document_id=document.document_id
                    AND receipt.tenant_id=document.tenant_id AND receipt.workspace_id=document.workspace_id
                    AND receipt.collection_id=document.collection_id
                    AND receipt.document_attempt=document.metadata->>'_ingestion_attempt'
                    WHERE document.document_id=%s AND receipt.outcome='pending' FOR UPDATE OF receipt""", (document_id,))
                if any(r['cancel_requested'] for r in self._fetchall(cursor)):
                    raise PostgresKnowledgeError('conflict')
            self._execute(
                cursor,
                f"""UPDATE rick_documents
                       SET status = %s,
                           published_at = CASE
                               WHEN %s = 'published' THEN COALESCE(published_at, NOW())
                               ELSE published_at
                           END,
                           updated_at = NOW()
                     WHERE {where}""",
                (status, status, *params),
            )

            if status == 'published':
                self._execute(cursor, """WITH decision AS MATERIALIZED (
                    SELECT EXTRACT(EPOCH FROM clock_timestamp())::double precision AS finished_at)
                    UPDATE rick_publication_receipts AS receipt
                    SET outcome='committed', job_snapshot=CASE
                      WHEN receipt.job_snapshot->>'finished_at' IS NOT NULL THEN receipt.job_snapshot
                      WHEN decision.finished_at >= COALESCE(
                        (receipt.job_snapshot->>'started_at')::double precision,
                        (receipt.job_snapshot->>'created_at')::double precision)
                      THEN jsonb_set(receipt.job_snapshot, '{finished_at}', to_jsonb(decision.finished_at))
                      ELSE receipt.job_snapshot END
                    FROM rick_documents AS document, decision
                    WHERE document.document_id=%s AND document.status='published'
                      AND receipt.document_id=document.document_id AND receipt.outcome='pending'
                      AND receipt.tenant_id=document.tenant_id AND receipt.workspace_id=document.workspace_id
                      AND receipt.collection_id=document.collection_id
                      AND receipt.document_attempt=document.metadata->>'_ingestion_attempt'""", (document_id,))

    @document_mutation
    def delete_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, f"SELECT status, tenant_id, workspace_id FROM rick_documents WHERE {where} FOR UPDATE", params)
            document = self._fetchone(cursor)
            if document is None:
                raise PostgresKnowledgeError("not_found")
            chunk_where = "document_id = %s AND tenant_id = %s AND workspace_id = %s"
            chunk_params = (document_id, document["tenant_id"], document["workspace_id"])
            self._execute(cursor, f"SELECT COUNT(*) AS count FROM rick_chunks WHERE {chunk_where}", chunk_params)
            row = self._fetchone(cursor)
            self._execute(cursor, f"DELETE FROM rick_chunks WHERE {chunk_where}", chunk_params)
            self._execute(cursor, f"UPDATE rick_documents SET status = 'deleted', updated_at = NOW() WHERE {where}", params)
            count = int((row or {}).get("count", 0))
        return max(0, count)

    @document_mutation
    def replace_document_chunks(
        self,
        document_id: str,
        chunks: list[Chunk],
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if not isinstance(chunks, list) or len(chunks) > 100_000:
            raise PostgresKnowledgeError("invalid_input")
        chunk_metadata_json: list[str] = []
        for chunk in chunks:
            if not isinstance(chunk.metadata, Mapping):
                raise PostgresKnowledgeError("invalid_input")
            try:
                chunk_metadata_json.append(encode_metadata(chunk.metadata))
            except ValueError:
                raise PostgresKnowledgeError("invalid_input") from None
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, f"SELECT tenant_id, workspace_id, collection_id, status FROM rick_documents WHERE {where} FOR UPDATE", params)
            document = self._fetchone(cursor)
            if document is None:
                raise PostgresKnowledgeError("not_found")
            if document.get("status") == "deleted" and chunks:
                raise PostgresKnowledgeError("conflict")
            self._execute(cursor, "DELETE FROM rick_chunks WHERE document_id = %s AND tenant_id = %s AND workspace_id = %s", (document_id, document["tenant_id"], document["workspace_id"]))
            for index, chunk in enumerate(chunks):
                if chunk.document_id != document_id or chunk.chunk_index != index:
                    raise PostgresKnowledgeError("invalid_input")
                if chunk.tenant_id != document["tenant_id"]:
                    raise PostgresKnowledgeError("invalid_input")
                self._execute(cursor, """
                    INSERT INTO rick_chunks
                        (chunk_id, document_id, tenant_id, workspace_id, collection_id,
                         chunk_index, text, checksum, page_start, page_end, section,
                         embedding_version, index_version, parent_chunk_id, token_count,
                         parser_version, chunker_version, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    chunk.chunk_id, document_id, document["tenant_id"], document["workspace_id"],
                    document["collection_id"], chunk.chunk_index, chunk.text, chunk.checksum,
                    chunk.page_start, chunk.page_end, chunk.section, chunk.embedding_version,
                    chunk.index_version, chunk.parent_chunk_id, chunk.token_count,
                    chunk.parser_version, chunk.chunker_version,
                    chunk_metadata_json[index],
                ))

    def get_chunks(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[Chunk]:
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"SELECT * FROM rick_chunks WHERE {where} ORDER BY chunk_index, chunk_id", params)
            rows = self._fetchall(cursor)
        return [item for row in rows if (item := self._chunk(row)) is not None]


__all__ = ["DbConnection", "PostgresKnowledgeError", "PostgresKnowledgeStore"]

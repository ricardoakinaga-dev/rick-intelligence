"""Small durable SQLite implementation of the canonical knowledge store.

SQLite is a local durability adapter, not the final multi-instance production
database. It exists so lifecycle tests can prove restart recovery against a
real transactional store while the Postgres/object-storage rollout is gated.
"""

from __future__ import annotations

from rick_knowledge.publication import PublicationStore
from rick_knowledge.fencing import OwnershipLostError
from asyncio import CancelledError
import json

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterable, Iterator

from rick_knowledge.json_boundary import decode_metadata, encode_metadata
from rick_knowledge.fencing import catalog_collection_ids, select_catalog_collection, collection_guard_key, collection_mutation, document_mutation, file_gate, file_mutation_guard, require_deleted_snapshot, require_unchanged_tombstone
from rick_knowledge.models import (
    DOCUMENT_STATUSES,
    Chunk,
    Collection,
    Document,
    materialize_lineage,
    utc_timestamp,
)


SCHEMA_VERSION = 3


def _metadata(value: object) -> str:
    return encode_metadata(value)


def _metadata_value(value: object) -> dict | None:
    return decode_metadata(value)


class SQLiteKnowledgeStore(PublicationStore):
    """Transactional file-backed implementation of :class:`KnowledgeStore`."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            location = Path(self.path)
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if location.exists() and location.is_dir():
                raise ValueError("SQLite store path must be a file")
        self._lock = RLock()
        self._effect_lock = RLock()
        self._guard_path, self._file_gate = file_gate(self.path) if self.path != ":memory:" else (None, None)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize()
        with self._transaction():
            self._connection.execute("""CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
                tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL, job_id TEXT NOT NULL,
                record TEXT NOT NULL CHECK(length(CAST(record AS BLOB)) <= 67108864),
                PRIMARY KEY(tenant_id, workspace_id, collection_id, job_id))""")
            self._connection.execute("""CREATE TABLE IF NOT EXISTS publication_receipts (
                tenant_id TEXT NOT NULL CHECK(length(trim(tenant_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                workspace_id TEXT NOT NULL CHECK(length(trim(workspace_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                collection_id TEXT NOT NULL CHECK(length(trim(collection_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                job_id TEXT NOT NULL CHECK(length(trim(job_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                document_id TEXT NOT NULL CHECK(length(trim(document_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                attempt_id TEXT NOT NULL CHECK(length(trim(attempt_id, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                document_attempt TEXT NOT NULL CHECK(length(trim(document_attempt, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) BETWEEN 1 AND 256),
                outcome TEXT NOT NULL CHECK(outcome IN ('pending','committed','failed','cancelled')),
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                ready_count INTEGER NOT NULL DEFAULT 0 CHECK(ready_count BETWEEN 0 AND 100000),
                job_snapshot TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (tenant_id, workspace_id, collection_id, job_id))""")
            columns = {row[1] for row in self._connection.execute('PRAGMA table_info(publication_receipts)')}
            if 'ready_count' not in columns:
                self._connection.execute('ALTER TABLE publication_receipts ADD COLUMN ready_count INTEGER NOT NULL DEFAULT 0')
            if 'job_snapshot' not in columns:
                self._connection.execute("ALTER TABLE publication_receipts ADD COLUMN job_snapshot TEXT NOT NULL DEFAULT '{}'")
            # Triggers also protect pre-existing receipt tables with the old schema.
            invalid = ' OR '.join("length(trim(NEW." + key + ", char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)))=0 OR length(NEW." + key + ")>256" for key in
                ('tenant_id','workspace_id','collection_id','job_id','document_id','attempt_id','document_attempt'))
            for operation in ('INSERT','UPDATE'):
                self._connection.execute(f"CREATE TRIGGER IF NOT EXISTS publication_identity_{operation.lower()} BEFORE {operation} ON publication_receipts WHEN {invalid} BEGIN SELECT RAISE(ABORT, 'invalid publication identity'); END")
            self._connection.execute("""CREATE INDEX IF NOT EXISTS publication_pending_document
                ON publication_receipts(document_id) WHERE outcome='pending'""")

    def ingestion_checkpoint_guard(self, job):
        return self._transaction()

    def _read_ingestion_checkpoint(self, job_id, tenant_id, workspace_id, collection_id):
        with self._read() as connection:
            row = connection.execute("""SELECT record FROM ingestion_checkpoints
                WHERE tenant_id=? AND workspace_id=? AND collection_id=? AND job_id=?""",
                (tenant_id, workspace_id, collection_id, job_id)).fetchone()
            return json.loads(row['record']) if row else None

    def _write_ingestion_checkpoint(self, record):
        from rick_knowledge.publication import encode_checkpoint
        encoded = encode_checkpoint(record)
        with self._transaction():
            self._connection.execute("""INSERT INTO ingestion_checkpoints
                (tenant_id, workspace_id, collection_id, job_id, record) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, collection_id, job_id)
                DO UPDATE SET record=excluded.record""",
                (*[record[k] for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id')], encoded))

    def _read_publication(self, job_id, tenant_id, workspace_id, collection_id):
        with self._read() as connection:
            row = connection.execute("""SELECT * FROM publication_receipts
                WHERE tenant_id=? AND workspace_id=? AND collection_id=? AND job_id=?""",
                (tenant_id, workspace_id, collection_id, job_id)).fetchone()
            if row is None:
                return None
            record = dict(row)
            record['job_snapshot'] = _metadata_value(record['job_snapshot'])
            if record['job_snapshot'] is None:
                raise ValueError('corrupt publication snapshot')
            return record

    def _write_publication(self, record):
        keys = ('tenant_id', 'workspace_id', 'collection_id', 'job_id', 'document_id',
                'attempt_id', 'document_attempt', 'outcome', 'cancel_requested', 'ready_count', 'job_snapshot')
        with self._transaction():
            self._connection.execute("""INSERT INTO publication_receipts
                (tenant_id, workspace_id, collection_id, job_id, document_id, attempt_id,
                 document_attempt, outcome, cancel_requested, ready_count, job_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, collection_id, job_id) DO UPDATE SET
                document_id=excluded.document_id, attempt_id=excluded.attempt_id,
                document_attempt=excluded.document_attempt, ready_count=excluded.ready_count, job_snapshot=excluded.job_snapshot,
                outcome=CASE WHEN publication_receipts.attempt_id=excluded.attempt_id AND publication_receipts.outcome<>'pending'
                    THEN publication_receipts.outcome WHEN publication_receipts.attempt_id=excluded.attempt_id
                    AND publication_receipts.cancel_requested AND excluded.outcome='failed'
                    THEN 'cancelled' ELSE excluded.outcome END,
                cancel_requested=excluded.cancel_requested OR
                    (publication_receipts.attempt_id=excluded.attempt_id AND publication_receipts.cancel_requested)""",
                tuple(_metadata(record[k]) if k == 'job_snapshot' else record[k] for k in keys))

    def publication_decision_guard(self, record):
        return self._transaction()

    def _mark_publication_cancel(self, job):
        with self._transaction():
            self._connection.execute("""UPDATE publication_receipts SET cancel_requested=1
                WHERE tenant_id=? AND workspace_id=? AND collection_id=? AND job_id=?
                AND attempt_id=? AND outcome='pending'""",
                (job.tenant_id, job.workspace_id, job.collection_id, job.job_id,
                 job.metadata['publication_attempt']))

    def mutation_guard(self, key: str):
        # A database-wide local gate is deliberate: it also coordinates
        # collection creation with document effects through separate handles.
        if self._guard_path is None:
            return self._effect_lock
        return file_mutation_guard(self._guard_path, self._file_gate)

    def collection_guard(self, *, tenant_id: str, workspace_id: str, collection_id: str):
        return self.mutation_guard(collection_guard_key(tenant_id=tenant_id,
            workspace_id=workspace_id, collection_id=collection_id))

    def restore_deleted_document(self, snapshot: Document, chunks: list[Chunk]) -> None:
        with self.mutation_guard("document:" + snapshot.document_id), self._transaction():
            snapshot = require_deleted_snapshot(self.get_document(snapshot.document_id), snapshot)
            self._connection.execute("UPDATE documents SET status=? WHERE document_id=?",
                                     (snapshot.status, snapshot.document_id))
            self.replace_document_chunks(snapshot.document_id, chunks)

    @collection_mutation
    def ensure_collection(self, collection: Collection) -> Collection:
        if collection.status not in {"active", "archived"}:
            raise ValueError("unknown collection status")
        metadata = dict(collection.metadata)
        metadata.update(__rick_status=collection.status, __rick_version=collection.version)
        with self._transaction():
            self._connection.execute(
                """INSERT INTO collections
                   (workspace_id, collection_id, tenant_id, title, description, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, workspace_id, collection_id) DO NOTHING""",
                (collection.workspace_id, collection.collection_id, collection.tenant_id,
                 collection.title, collection.description, _metadata(metadata)),
            )
            row = self._connection.execute(
                "SELECT * FROM collections WHERE tenant_id=? AND workspace_id=? AND collection_id=?",
                (collection.tenant_id, collection.workspace_id, collection.collection_id),
            ).fetchone()
            result = self._collection(row)
            if result is None:
                raise ValueError("invalid collection metadata")
            return result

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, 1, 2, SCHEMA_VERSION):
                raise RuntimeError(f"unsupported knowledge schema version: {current}")
            if current == 0:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS collections (
                        workspace_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, workspace_id, collection_id)
                    );
                    CREATE TABLE IF NOT EXISTS documents (
                        document_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        document_version TEXT NOT NULL,
                        content_checksum TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        display_filename TEXT NOT NULL,
                        title TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        language TEXT,
                        status TEXT NOT NULL,
                        parser_version TEXT NOT NULL,
                        chunker_version TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        embedding_version TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        ingestion_version TEXT NOT NULL DEFAULT '',
                        object_ref TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        published_at TEXT,
                        CHECK (status IN ('draft','processing','published','unpublished','deleted','partial','failed'))
                    );
                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(document_id),
                        tenant_id TEXT NOT NULL,
                        parent_chunk_id TEXT,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        page_start INTEGER,
                        page_end INTEGER,
                        section TEXT,
                        heading TEXT,
                        token_count INTEGER NOT NULL,
                        checksum TEXT NOT NULL,
                        parser_version TEXT NOT NULL,
                        chunker_version TEXT NOT NULL,
                        embedding_version TEXT NOT NULL,
                        index_version TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS documents_scope_idx
                        ON documents (tenant_id, workspace_id, collection_id, status, document_id);
                    CREATE INDEX IF NOT EXISTS documents_lineage_idx
                        ON documents (tenant_id, workspace_id, collection_id, document_id,
                                      document_version, ingestion_version);
                    CREATE INDEX IF NOT EXISTS chunks_document_idx
                        ON chunks (document_id, chunk_index, chunk_id);
                    PRAGMA user_version = 3;
                    """
                )
            elif current == 1:
                # v1 keyed collections by workspace/name only. That allowed a
                # later tenant to overwrite an earlier tenant's catalog row.
                # Rebuild the small table inside the same transaction so old
                # local databases retain their data while gaining the correct
                # tenant-scoped identity.
                self._connection.execute(
                    """
                    CREATE TABLE collections_v2 (
                        workspace_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, workspace_id, collection_id)
                    )
                    """
                )
                self._connection.execute(
                    """
                    INSERT INTO collections_v2
                        (workspace_id, collection_id, tenant_id, title, description, metadata_json)
                    SELECT workspace_id, collection_id, tenant_id, title, description, metadata_json
                    FROM collections
                    """
                )
                self._connection.execute("DROP TABLE collections")
                self._connection.execute("ALTER TABLE collections_v2 RENAME TO collections")
                current = 2

            if current == 2:
                # Expand the document row without rewriting the table, then
                # backfill only deterministic legacy aliases. Unknown
                # publication history remains NULL rather than being guessed.
                self._connection.executescript(
                    """
                    ALTER TABLE documents ADD COLUMN ingestion_version TEXT NOT NULL DEFAULT '';
                    ALTER TABLE documents ADD COLUMN object_ref TEXT NOT NULL DEFAULT '';
                    ALTER TABLE documents ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
                    ALTER TABLE documents ADD COLUMN published_at TEXT;
                    UPDATE documents
                    SET ingestion_version = COALESCE(NULLIF(ingestion_version, ''), document_version),
                        object_ref = COALESCE(NULLIF(object_ref, ''), NULLIF(filename, ''),
                                              NULLIF(display_filename, ''), document_id),
                        created_at = CASE WHEN created_at = '' THEN CURRENT_TIMESTAMP ELSE created_at END;
                    CREATE INDEX IF NOT EXISTS documents_lineage_idx
                        ON documents (tenant_id, workspace_id, collection_id, document_id,
                                      document_version, ingestion_version);
                    PRAGMA user_version = 3;
                    """
                )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            if self._connection.in_transaction:
                # Explicit maintenance composes status, row and chunks in the
                # outer transaction. The outer scope owns commit/rollback.
                yield
                return
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteKnowledgeStore":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    @staticmethod
    def _collection(row: sqlite3.Row) -> Collection | None:
        metadata = _metadata_value(row["metadata_json"])
        if metadata is None:
            return None
        status = metadata.pop("__rick_status", "active")
        version = metadata.pop("__rick_version", 1)
        return Collection(
            workspace_id=row["workspace_id"], collection_id=row["collection_id"],
            tenant_id=row["tenant_id"], title=row["title"], description=row["description"],
            status=status if status in {"active", "archived"} else "active",
            version=version if isinstance(version, int) and not isinstance(version, bool) else 1,
            metadata=metadata,
        )

    @staticmethod
    def _document(row: sqlite3.Row) -> Document | None:
        metadata = _metadata_value(row["metadata_json"])
        if metadata is None:
            return None
        return Document(
            document_id=row["document_id"], workspace_id=row["workspace_id"],
            collection_id=row["collection_id"], tenant_id=row["tenant_id"],
            document_version=row["document_version"], content_checksum=row["content_checksum"],
            filename=row["filename"], display_filename=row["display_filename"],
            title=row["title"], source_type=row["source_type"], mime_type=row["mime_type"],
            language=row["language"], status=row["status"],
            parser_version=row["parser_version"], chunker_version=row["chunker_version"],
            embedding_model=row["embedding_model"], embedding_version=row["embedding_version"],
            metadata=metadata,
            ingestion_version=row["ingestion_version"] or row["document_version"],
            object_ref=row["object_ref"] or row["filename"] or row["display_filename"] or row["document_id"],
            created_at=row["created_at"],
            published_at=row["published_at"],
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> Chunk | None:
        metadata = _metadata_value(row["metadata_json"])
        if metadata is None:
            return None
        return Chunk(
            chunk_id=row["chunk_id"], document_id=row["document_id"], tenant_id=row["tenant_id"],
            parent_chunk_id=row["parent_chunk_id"], chunk_index=row["chunk_index"], text=row["text"],
            page_start=row["page_start"], page_end=row["page_end"], section=row["section"],
            heading=row["heading"], token_count=row["token_count"], checksum=row["checksum"],
            parser_version=row["parser_version"], chunker_version=row["chunker_version"],
            embedding_version=row["embedding_version"], index_version=row["index_version"],
            metadata=metadata,
        )

    @collection_mutation
    def upsert_collection(self, collection: Collection) -> None:
        if collection.status not in {"active", "archived"}:
            raise ValueError("unknown collection status")
        metadata = {
            **(collection.metadata if isinstance(collection.metadata, dict) else {}),
            "__rick_status": collection.status,
            "__rick_version": collection.version,
        }
        with self._transaction():
            self._connection.execute(
                """INSERT INTO collections
                (workspace_id, collection_id, tenant_id, title, description, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, collection_id) DO UPDATE SET
                  tenant_id=excluded.tenant_id, title=excluded.title,
                  description=excluded.description, metadata_json=excluded.metadata_json""",
                (collection.workspace_id, collection.collection_id, collection.tenant_id,
                 collection.title, collection.description, _metadata(metadata)),
            )

    def get_collection(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        tenant_id: str,
    ) -> Collection | None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        keys = catalog_collection_ids(collection_id)
        query = "SELECT * FROM collections WHERE workspace_id = ? AND collection_id IN (" + ",".join("?" for _ in keys) + ")"
        params: list[object] = [workspace_id, *keys]
        query += " AND tenant_id = ?"
        params.append(tenant_id.strip())
        with self._read() as connection:
            rows = connection.execute(query, params).fetchall()
        return select_catalog_collection([self._collection(row) for row in rows], collection_id)

    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        query = "SELECT * FROM collections WHERE workspace_id = ? AND tenant_id = ?"
        params: list[object] = [workspace_id, tenant_id.strip()]
        query += " ORDER BY collection_id"
        with self._read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [item for row in rows if (item := self._collection(row)) is not None]

    @document_mutation
    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {document.status}")
        materialize_lineage(document, published=document.status == "published")
        with self._transaction():
            previous = self._connection.execute(
                "SELECT * "
                "FROM documents WHERE document_id = ?",
                (document.document_id,),
            ).fetchone()
            if previous and (
                previous["tenant_id"] != document.tenant_id
                or previous["workspace_id"] != document.workspace_id
                or previous["collection_id"] != document.collection_id
            ):
                raise ValueError("document scope cannot change")
            if previous and previous["status"] == "deleted" and document.status != "deleted":
                raise ValueError("deleted documents cannot transition; ingest a new version")
            if previous and previous["status"] == "deleted":
                require_unchanged_tombstone(self._document(previous), document)
                return
            self._connection.execute(
                """INSERT INTO documents
                (document_id, workspace_id, collection_id, tenant_id, document_version,
                 content_checksum, filename, display_filename, title, source_type, mime_type,
                 language, status, parser_version, chunker_version, embedding_model,
                 embedding_version, metadata_json, ingestion_version, object_ref,
                 created_at, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  workspace_id=excluded.workspace_id, collection_id=excluded.collection_id,
                  tenant_id=excluded.tenant_id, document_version=excluded.document_version,
                  content_checksum=excluded.content_checksum, filename=excluded.filename,
                  display_filename=excluded.display_filename, title=excluded.title,
                  source_type=excluded.source_type, mime_type=excluded.mime_type,
                  language=excluded.language, status=excluded.status,
                  parser_version=excluded.parser_version, chunker_version=excluded.chunker_version,
                  embedding_model=excluded.embedding_model, embedding_version=excluded.embedding_version,
                  metadata_json=excluded.metadata_json, ingestion_version=excluded.ingestion_version,
                  object_ref=excluded.object_ref,
                  published_at=CASE
                    WHEN excluded.status = 'published'
                      THEN COALESCE(excluded.published_at, documents.published_at, CURRENT_TIMESTAMP)
                    ELSE COALESCE(excluded.published_at, documents.published_at)
                  END""",
                (document.document_id, document.workspace_id, document.collection_id, document.tenant_id,
                 document.document_version, document.content_checksum, document.filename,
                 document.display_filename, document.title, document.source_type, document.mime_type,
                 document.language, document.status, document.parser_version, document.chunker_version,
                 document.embedding_model, document.embedding_version, _metadata(document.metadata),
                 document.ingestion_version, document.object_ref, document.created_at,
                 document.published_at),
            )

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None:
        with self._read() as connection:
            clauses = ["document_id = ?"]
            params: list[object] = [document_id]
            if tenant_id is not None:
                clauses.append("tenant_id = ?")
                params.append(tenant_id)
            if workspace_id is not None:
                clauses.append("workspace_id = ?")
                params.append(workspace_id)
            row = connection.execute(
                "SELECT * FROM documents WHERE " + " AND ".join(clauses), tuple(params)
            ).fetchone()
        return self._document(row) if row else None

    def list_documents(
        self, workspace_id: str, collection_id: str | None = None, *, tenant_id: str,
        after_document_id: str | None = None, limit: int | None = None,
        statuses: Iterable[str] | None = None, allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer")
        query = "SELECT * FROM documents WHERE workspace_id = ? AND status != 'deleted'"
        params: list[object] = [workspace_id]
        query += " AND tenant_id = ?"
        params.append(tenant_id.strip())
        if collection_id is not None:
            query += " AND collection_id = ?"
            params.append(collection_id)
        if statuses is not None:
            values = list(statuses)
            if not values:
                return []
            query += " AND status IN (" + ",".join("?" for _ in values) + ")"
            params.extend(values)
        if allowed_collection_ids is not None:
            allowed = list(allowed_collection_ids)
            if "*" not in allowed:
                if not allowed:
                    return []
                query += " AND collection_id IN (" + ",".join("?" for _ in allowed) + ")"
                params.extend(allowed)
        if after_document_id is not None:
            query += " AND document_id > ?"
            params.append(after_document_id)
        query += " ORDER BY document_id"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [item for row in rows if (item := self._document(row)) is not None]

    @document_mutation
    def set_document_status(self, document_id: str, status: str) -> None:
        if status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {status}")
        with self._transaction():
            row = self._connection.execute("SELECT status FROM documents WHERE document_id = ?", (document_id,)).fetchone()
            if row is None:
                raise KeyError(document_id)
            if row["status"] == "deleted" and status != "deleted":
                raise ValueError("deleted documents cannot transition; ingest a new version")
            if status == 'published':
                document = self.get_document(document_id)
                pending = self._connection.execute("SELECT * FROM publication_receipts WHERE document_id=? AND outcome='pending'", (document_id,)).fetchall()
                if any(r['cancel_requested'] and self._publication_matches(dict(r), document) for r in pending):
                    raise OwnershipLostError('publication cancelled before commit')
            published_at = utc_timestamp() if status == "published" else None
            self._connection.execute(
                """UPDATE documents
                   SET status = ?,
                       published_at = CASE
                           WHEN ? = 'published' THEN COALESCE(published_at, ?)
                           ELSE published_at
                       END
                 WHERE document_id = ?""",
                (status, status, published_at, document_id),
            )

            if status == 'published':
                document = self.get_document(document_id)
                rows = self._connection.execute("""SELECT * FROM publication_receipts
                    WHERE document_id=? AND outcome='pending'""", (document_id,)).fetchall()
                for row in rows:
                    record = dict(row)
                    record['job_snapshot'] = _metadata_value(record['job_snapshot'])
                    if self._publication_matches(record, document):
                        self._write_publication(self._committed_publication(record))

    @document_mutation
    def delete_document(self, document_id: str) -> int:
        with self._transaction():
            count = int(self._connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)).fetchone()[0])
            self._connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            self._connection.execute("UPDATE documents SET status = 'deleted' WHERE document_id = ?", (document_id,))
        return count

    @document_mutation
    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        with self._transaction():
            document = self._connection.execute(
                "SELECT tenant_id, status FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if document is None:
                raise KeyError(document_id)
            if document["status"] == "deleted" and chunks:
                raise ValueError("deleted documents cannot receive chunks")
            self._connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            for chunk in chunks:
                if chunk.document_id != document_id:
                    raise ValueError("chunk document_id does not match parent")
                if chunk.tenant_id != document["tenant_id"]:
                    raise ValueError("chunk tenant_id does not match parent")
                self._connection.execute(
                    """INSERT INTO chunks
                    (chunk_id, document_id, tenant_id, parent_chunk_id, chunk_index, text,
                     page_start, page_end, section, heading, token_count, checksum,
                     parser_version, chunker_version, embedding_version, index_version, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chunk.chunk_id, chunk.document_id, chunk.tenant_id, chunk.parent_chunk_id,
                     chunk.chunk_index, chunk.text, chunk.page_start, chunk.page_end, chunk.section,
                     chunk.heading, chunk.token_count, chunk.checksum, chunk.parser_version,
                     chunk.chunker_version, chunk.embedding_version, chunk.index_version,
                     _metadata(chunk.metadata)),
                )

    def get_chunks(self, document_id: str) -> list[Chunk]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index, chunk_id", (document_id,)
            ).fetchall()
        return [item for row in rows if (item := self._chunk(row)) is not None]

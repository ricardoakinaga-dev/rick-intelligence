"""Small durable SQLite implementation of the canonical knowledge store.

SQLite is a local durability adapter, not the final multi-instance production
database. It exists so lifecycle tests can prove restart recovery against a
real transactional store while the Postgres/object-storage rollout is gated.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterable, Iterator

from rick_knowledge.models import DOCUMENT_STATUSES, Chunk, Collection, Document


SCHEMA_VERSION = 2


def _metadata(value: object) -> str:
    if not isinstance(value, dict):
        raise ValueError("metadata must be a mapping")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc


def _metadata_value(value: str) -> dict:
    decoded = json.loads(value or "{}")
    return decoded if isinstance(decoded, dict) else {}


class SQLiteKnowledgeStore:
    """Transactional file-backed implementation of :class:`KnowledgeStore`."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            location = Path(self.path)
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if location.exists() and location.is_dir():
                raise ValueError("SQLite store path must be a file")
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize()

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, 1, SCHEMA_VERSION):
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
                    CREATE INDEX IF NOT EXISTS chunks_document_idx
                        ON chunks (document_id, chunk_index, chunk_id);
                    PRAGMA user_version = 2;
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
                self._connection.execute("PRAGMA user_version = 2")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
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
    def _collection(row: sqlite3.Row) -> Collection:
        metadata = _metadata_value(row["metadata_json"])
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
    def _document(row: sqlite3.Row) -> Document:
        return Document(
            document_id=row["document_id"], workspace_id=row["workspace_id"],
            collection_id=row["collection_id"], tenant_id=row["tenant_id"],
            document_version=row["document_version"], content_checksum=row["content_checksum"],
            filename=row["filename"], display_filename=row["display_filename"],
            title=row["title"], source_type=row["source_type"], mime_type=row["mime_type"],
            language=row["language"], status=row["status"],
            parser_version=row["parser_version"], chunker_version=row["chunker_version"],
            embedding_model=row["embedding_model"], embedding_version=row["embedding_version"],
            metadata=_metadata_value(row["metadata_json"]),
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"], document_id=row["document_id"], tenant_id=row["tenant_id"],
            parent_chunk_id=row["parent_chunk_id"], chunk_index=row["chunk_index"], text=row["text"],
            page_start=row["page_start"], page_end=row["page_end"], section=row["section"],
            heading=row["heading"], token_count=row["token_count"], checksum=row["checksum"],
            parser_version=row["parser_version"], chunker_version=row["chunker_version"],
            embedding_version=row["embedding_version"], index_version=row["index_version"],
            metadata=_metadata_value(row["metadata_json"]),
        )

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
        query = "SELECT * FROM collections WHERE workspace_id = ? AND collection_id = ?"
        params: list[object] = [workspace_id, collection_id]
        query += " AND tenant_id = ?"
        params.append(tenant_id.strip())
        query += " LIMIT 2"
        with self._read() as connection:
            rows = connection.execute(query, params).fetchall()
        return self._collection(rows[0]) if rows else None

    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        query = "SELECT * FROM collections WHERE workspace_id = ? AND tenant_id = ?"
        params: list[object] = [workspace_id, tenant_id.strip()]
        query += " ORDER BY collection_id"
        with self._read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._collection(row) for row in rows]

    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {document.status}")
        with self._transaction():
            previous = self._connection.execute(
                "SELECT status FROM documents WHERE document_id = ?", (document.document_id,)
            ).fetchone()
            if previous and previous["status"] == "deleted" and document.status != "deleted":
                raise ValueError("deleted documents cannot transition; ingest a new version")
            self._connection.execute(
                """INSERT INTO documents
                (document_id, workspace_id, collection_id, tenant_id, document_version,
                 content_checksum, filename, display_filename, title, source_type, mime_type,
                 language, status, parser_version, chunker_version, embedding_model,
                 embedding_version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  workspace_id=excluded.workspace_id, collection_id=excluded.collection_id,
                  tenant_id=excluded.tenant_id, document_version=excluded.document_version,
                  content_checksum=excluded.content_checksum, filename=excluded.filename,
                  display_filename=excluded.display_filename, title=excluded.title,
                  source_type=excluded.source_type, mime_type=excluded.mime_type,
                  language=excluded.language, status=excluded.status,
                  parser_version=excluded.parser_version, chunker_version=excluded.chunker_version,
                  embedding_model=excluded.embedding_model, embedding_version=excluded.embedding_version,
                  metadata_json=excluded.metadata_json""",
                (document.document_id, document.workspace_id, document.collection_id, document.tenant_id,
                 document.document_version, document.content_checksum, document.filename,
                 document.display_filename, document.title, document.source_type, document.mime_type,
                 document.language, document.status, document.parser_version, document.chunker_version,
                 document.embedding_model, document.embedding_version, _metadata(document.metadata)),
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
        return [self._document(row) for row in rows]

    def set_document_status(self, document_id: str, status: str) -> None:
        if status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {status}")
        with self._transaction():
            row = self._connection.execute("SELECT status FROM documents WHERE document_id = ?", (document_id,)).fetchone()
            if row is None:
                raise KeyError(document_id)
            if row["status"] == "deleted" and status != "deleted":
                raise ValueError("deleted documents cannot transition; ingest a new version")
            self._connection.execute("UPDATE documents SET status = ? WHERE document_id = ?", (status, document_id))

    def delete_document(self, document_id: str) -> int:
        with self._transaction():
            count = int(self._connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)).fetchone()[0])
            self._connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            self._connection.execute("UPDATE documents SET status = 'deleted' WHERE document_id = ?", (document_id,))
        return count

    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        with self._transaction():
            if self._connection.execute("SELECT 1 FROM documents WHERE document_id = ?", (document_id,)).fetchone() is None:
                raise KeyError(document_id)
            self._connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            for chunk in chunks:
                if chunk.document_id != document_id:
                    raise ValueError("chunk document_id does not match parent")
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
        return [self._chunk(row) for row in rows]

"""DB-API PostgreSQL knowledge adapter.

The domain package does not import psycopg or open a socket. A connection
factory is injected by the application composition root, which keeps startup
and tests deterministic while still giving production a transactional store.
Every read carries tenant and workspace scope at the SQL boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
import json
import math
from typing import Protocol

from rick_knowledge.models import DOCUMENT_STATUSES, Chunk, Collection, Document


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


def _json_value(value: object, default: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
        return parsed if isinstance(parsed, (dict, list)) else default
    return default


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _bounded_limit(value: int | None, *, default: int = 100, maximum: int = 1_000) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise PostgresKnowledgeError("invalid_input")
    return value


class PostgresKnowledgeStore:
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

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
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
        except PostgresKnowledgeError:
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
    def _collection(row: Mapping[str, object]) -> Collection:
        metadata = _json_value(row.get("metadata"), {})
        return Collection(
            tenant_id=str(row.get("tenant_id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            collection_id=str(row.get("collection_id") or ""),
            title=str(row.get("title") or ""),
            description=str(row.get("description") or ""),
            status=str(row.get("status") or "active"),
            version=int(row.get("version") or 1),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @staticmethod
    def _document(row: Mapping[str, object]) -> Document:
        metadata = _json_value(row.get("metadata"), {})
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
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @staticmethod
    def _chunk(row: Mapping[str, object]) -> Chunk:
        metadata = _json_value(row.get("metadata"), {})
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
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._fetchone(cursor) is not None
        except PostgresKnowledgeError:
            return False

    def upsert_collection(self, collection: Collection) -> None:
        if collection.status not in {"active", "archived"} or collection.version <= 0:
            raise PostgresKnowledgeError("invalid_input")
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
                   json.dumps(dict(collection.metadata or {}), ensure_ascii=False, sort_keys=True)))

    def get_collection(self, workspace_id: str, collection_id: str, *, tenant_id: str) -> Collection | None:
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
        return [self._collection(row) for row in rows]

    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise PostgresKnowledgeError("invalid_input")
        creator = self._creator(document.metadata, self._created_by)
        metadata = dict(document.metadata or {})
        object_key = str(metadata.get("object_key") or document.filename or document.document_id)
        byte_size = metadata.get("byte_size", 0)
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise PostgresKnowledgeError("invalid_input")
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "SELECT tenant_id, workspace_id, status FROM rick_documents WHERE document_id = %s FOR UPDATE", (document.document_id,))
            existing = self._fetchone(cursor)
            if existing and (
                existing.get("tenant_id") != document.tenant_id
                or existing.get("workspace_id") != document.workspace_id
            ):
                # A caller must never be able to move a document primary key
                # across scopes through an upsert.
                raise PostgresKnowledgeError("conflict")
            if existing and existing.get("status") == "deleted" and document.status != "deleted":
                raise PostgresKnowledgeError("conflict")
            self._execute(cursor, """
                INSERT INTO rick_documents
                    (document_id, tenant_id, workspace_id, collection_id, document_version,
                     content_checksum, object_key, byte_size, title, display_filename,
                     mime_type, status, parser_version, chunker_version, embedding_model,
                     embedding_version, created_by, filename, source_type, language, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id, workspace_id = EXCLUDED.workspace_id,
                    collection_id = EXCLUDED.collection_id, document_version = EXCLUDED.document_version,
                    content_checksum = EXCLUDED.content_checksum, object_key = EXCLUDED.object_key,
                    byte_size = EXCLUDED.byte_size, title = EXCLUDED.title,
                    display_filename = EXCLUDED.display_filename, mime_type = EXCLUDED.mime_type,
                    status = EXCLUDED.status, parser_version = EXCLUDED.parser_version,
                    chunker_version = EXCLUDED.chunker_version, embedding_model = EXCLUDED.embedding_model,
                    embedding_version = EXCLUDED.embedding_version, filename = EXCLUDED.filename,
                    source_type = EXCLUDED.source_type, language = EXCLUDED.language,
                    metadata = EXCLUDED.metadata, updated_at = NOW()
            """, (
                document.document_id, document.tenant_id, document.workspace_id, document.collection_id,
                document.document_version, document.content_checksum, object_key, byte_size,
                document.title, document.display_filename or document.filename, document.mime_type,
                document.status, document.parser_version, document.chunker_version,
                document.embedding_model, document.embedding_version, creator, document.filename,
                document.source_type, document.language, json.dumps(metadata, ensure_ascii=False, sort_keys=True),
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
        return [self._document(row) for row in rows]

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
            self._execute(cursor, f"UPDATE rick_documents SET status = %s, updated_at = NOW() WHERE {where}", (status, *params))

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
        where, params = self._document_scope_where(
            document_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, f"SELECT tenant_id, workspace_id, collection_id FROM rick_documents WHERE {where} FOR UPDATE", params)
            document = self._fetchone(cursor)
            if document is None:
                raise PostgresKnowledgeError("not_found")
            self._execute(cursor, "DELETE FROM rick_chunks WHERE document_id = %s AND tenant_id = %s AND workspace_id = %s", (document_id, document["tenant_id"], document["workspace_id"]))
            for index, chunk in enumerate(chunks):
                if chunk.document_id != document_id or chunk.chunk_index != index:
                    raise PostgresKnowledgeError("invalid_input")
                metadata = dict(chunk.metadata or {})
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
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
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
        return [self._chunk(row) for row in rows]


__all__ = ["DbConnection", "PostgresKnowledgeError", "PostgresKnowledgeStore"]

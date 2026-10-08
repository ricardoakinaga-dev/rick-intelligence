"""Publication effect ownership shared by the three knowledge adapters.

Writers hold mutation_guard across the ownership read AND the external effect.
The token lives in document metadata; it is not the reusable queue job ID.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from threading import RLock, local
from weakref import WeakValueDictionary
from functools import wraps
from copy import deepcopy
from dataclasses import fields
from rick_knowledge.models import DOCUMENT_STATUSES, Document, materialize_lineage
from rick_knowledge.identity import COLLECTION_ALIASES
import fcntl
import json

ATTEMPT_METADATA_KEY = "_ingestion_attempt"


class OwnershipLostError(RuntimeError):
    code = "lock_unavailable"


def advisory_key(key: str) -> int:
    return int.from_bytes(sha256(key.encode("utf-8")).digest()[:8], "big", signed=True)


def collection_guard_key(*, tenant_id: str, workspace_id: str, collection_id: str) -> str:
    """A separate, versioned tuple namespace; separators cannot alias scopes."""
    scope = (tenant_id, workspace_id, collection_id)
    if any(not isinstance(value, str) or not value.strip() for value in scope):
        raise ValueError("collection guard requires a complete scope")
    scope = (tenant_id, workspace_id, canonical_catalog_id(collection_id))
    return "collection:v1:" + json.dumps(scope, ensure_ascii=True, separators=(",", ":"))


def canonical_catalog_id(collection_id):
    # Modern API writers validate names separately. Lock/read compatibility
    # must retain arbitrary installed keys, including separators and Unicode.
    return COLLECTION_ALIASES.get(collection_id.strip(), collection_id)


def catalog_collection_ids(collection_id):
    """Logical alias family; persisted historical keys are never renamed."""
    canonical = canonical_catalog_id(collection_id)
    return (canonical, *sorted(key for key, value in COLLECTION_ALIASES.items()
                               if value == canonical and key != canonical))


def select_catalog_collection(collections, collection_id):
    """An archived member denies admission to the entire logical collection.

    Installed rows can contain multiple old alias keys. Their metadata and
    physical scope remain intact; stable selection gives archives precedence.
    """
    keys = catalog_collection_ids(collection_id)
    candidates = [c for c in collections if c is not None and c.collection_id in keys]
    return deepcopy(min(candidates, key=lambda c: (c.status != "archived", keys.index(c.collection_id)))) if candidates else None


def collection_mutation(method):
    """Catalog writes share the final-publication decision's collection guard."""
    @wraps(method)
    def guarded(store, collection, *args, **kwargs):
        with store.collection_guard(tenant_id=collection.tenant_id,
                                    workspace_id=collection.workspace_id,
                                    collection_id=collection.collection_id):
            canonical = canonical_catalog_id(collection.collection_id)
            if len(catalog_collection_ids(canonical)) > 1:
                existing = store.get_collection(collection.workspace_id, canonical, tenant_id=collection.tenant_id)
                if method.__name__ == "ensure_collection" and existing is not None:
                    if existing.status == "archived" or existing.collection_id == canonical:
                        return existing
                    # A new canonical scope may reference an installed active
                    # alias. Retain its reviewed fields in the new FK parent;
                    # never rename historical rows, documents or citations.
                    collection = deepcopy(existing)
                    collection.collection_id = canonical
                else:
                    if existing is not None and existing.status == "archived" and collection.status == "active":
                        raise ValueError("archived collection cannot be reactivated by upsert")
                    collection = deepcopy(collection)
                    collection.collection_id = existing.collection_id if existing is not None else canonical
            return method(store, collection, *args, **kwargs)
    return guarded


def require_owner(document, attempt_id: str) -> None:
    if document is None or document.status == "deleted" or document.metadata.get(ATTEMPT_METADATA_KEY) != attempt_id:
        raise OwnershipLostError("publication ownership lost")


def require_unchanged_tombstone(current, snapshot):
    """Return a detached exact retained document, with legacy defaults resolved.

    Old callers supplied no object/ingestion/publication fields. Derivable
    defaults must match the tombstone; an omitted publication timestamp retains
    its durable value. Neither omission nor explicit restore may change lineage.
    """
    if current is None or current.status != "deleted" or snapshot.status not in DOCUMENT_STATUSES:
        raise ValueError("delete compensation snapshot does not match tombstone")
    candidate = deepcopy(snapshot)
    materialize_lineage(candidate)
    # PostgreSQL's legacy reader derives an absent filename from object_key.
    # Resolving that omission cannot change the retained object identity.
    if not snapshot.filename and current.filename == candidate.object_ref:
        candidate.filename = current.filename
    if snapshot.published_at is None:
        candidate.published_at = current.published_at
    if any(getattr(current, field.name) != getattr(candidate, field.name)
           for field in fields(Document) if field.name != "status"):
        raise ValueError("delete compensation snapshot does not match tombstone")
    restored = deepcopy(current)
    restored.status = candidate.status
    return restored


def require_deleted_snapshot(current, snapshot):
    """Explicit delete compensation is distinct from an idempotent tombstone."""
    if snapshot.status == "deleted":
        raise ValueError("delete compensation snapshot does not match tombstone")
    return require_unchanged_tombstone(current, snapshot)


def document_mutation(method):
    """Make ordinary lifecycle writers participate in the same effect lock."""
    @wraps(method)
    def guarded(store, document_or_id, *args, **kwargs):
        document_id = getattr(document_or_id, "document_id", document_or_id)
        with store.mutation_guard("document:" + document_id):
            return method(store, document_or_id, *args, **kwargs)
    return guarded


class _FileGate:
    def __init__(self):
        self.lock = RLock()
        self.local = local()


_gates = WeakValueDictionary()
_gates_lock = RLock()


def file_gate(path: str):
    canonical = str(Path(path).resolve())
    with _gates_lock:
        gate = _gates.get(canonical)
        if gate is None:
            gate = _FileGate()
            _gates[canonical] = gate
        return canonical, gate


@contextmanager
def file_mutation_guard(path: str, gate):
    """Serialize SQLite effects across instances and local processes.

Reentrant within one thread, including calls through another store instance.
No SQLite schema change or long-lived database write transaction is required.
"""
    with gate.lock:
        if getattr(gate.local, "held", False):
            yield
            return
        with open(path + ".ingestion.lock", "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            gate.local.held = True
            try:
                yield
            finally:
                gate.local.held = False
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

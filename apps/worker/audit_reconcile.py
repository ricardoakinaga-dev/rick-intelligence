"""Reconcile durable audit operations that still need an acknowledgement.

The API writes the security effect and the operation row atomically. External
projection may fail/timeout, leaving the operation in ``effect_applied`` or
``indeterminate``. This reconciler re-projects those rows with the same
idempotency key and closes them as acknowledged or failed. It is safe to run
concurrently: the sink projection is idempotent and state updates are fenced by
the operation row.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Mapping


def operation_event(operation: Mapping[str, object]) -> dict[str, object]:
    event: dict[str, object] = {
        "action": operation.get("action"),
        "request_id": operation.get("request_id"),
        "status": "effect_applied",
    }
    for field in ("tenant_id", "actor_user_id", "workspace_id"):
        value = operation.get(field)
        if isinstance(value, str) and value.strip():
            event[field] = value
    return event


def reconcile_pending(
    store: object,
    sink: object,
    *,
    limit: int = 100,
    older_than_seconds: int = 30,
    max_attempts: int = 5,
) -> dict[str, int]:
    """Project pending operations and return bounded counters.

    A failed projection is retried; after ``max_attempts`` the operation is
    marked failed. No exception escapes for one bad row; the summary records it.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("limit is out of range")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
        raise ValueError("max_attempts is out of range")
    pending = store.pending(limit=limit, older_than_seconds=older_than_seconds)
    summary = {"scanned": len(pending), "acknowledged": 0, "retried": 0, "failed": 0, "errors": 0}
    for operation in pending:
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            summary["errors"] += 1
            continue
        attempts = operation.get("attempts")
        attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
        try:
            emitted = sink.emit(operation_event(operation))
        except Exception:
            emitted = False
        if emitted is True:
            try:
                acknowledged = store.acknowledge(operation_id)
            except Exception:
                acknowledged = False
            if acknowledged:
                summary["acknowledged"] += 1
            else:
                summary["errors"] += 1
            continue
        try:
            if attempts + 1 >= max_attempts:
                store.fail(operation_id, "projection_failed")
                summary["failed"] += 1
            else:
                store.retry(operation_id, "projection_failed")
                summary["retried"] += 1
        except Exception:
            summary["errors"] += 1
    return summary


def _load_factory(reference: str):
    if not isinstance(reference, str) or ":" not in reference:
        raise ValueError("connection factory must be module:callable")
    module_name, attribute = reference.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError("connection factory is not callable")
    return factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-factory", required=True, help="module:callable returning a DB-API connection")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--older-than", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--apply", action="store_true", help="apply changes; default is a dry-run inventory")
    args = parser.parse_args(argv)
    try:
        factory = _load_factory(args.connection_factory)
        from services.audit_operations_store import PostgresAuditOperationStore
        from services.postgres_audit import PostgresAuditSink

        store = PostgresAuditOperationStore(factory)
        sink = PostgresAuditSink(factory)
        if not args.apply:
            pending = store.pending(limit=args.limit, older_than_seconds=args.older_than)
            print(json.dumps({"dry_run": True, "scanned": len(pending)}, sort_keys=True))
            return 0
        summary = reconcile_pending(
            store, sink, limit=args.limit,
            older_than_seconds=args.older_than, max_attempts=args.max_attempts,
        )
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["errors"] == 0 else 1
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

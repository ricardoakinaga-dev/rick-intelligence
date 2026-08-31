"""
Cleanup operational uploads that are older than each tenant's configured TTL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.admin_service import list_tenants
from services.operational_retention_service import cleanup_operational_uploads


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup operational uploads by tenant TTL.")
    parser.add_argument("workspace_id", nargs="?", default=None, help="Workspace to clean. Defaults to all configured workspaces.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspaces = [args.workspace_id] if args.workspace_id else [tenant["workspace_id"] for tenant in list_tenants()]

    total_deleted = 0
    for workspace_id in workspaces:
        result = cleanup_operational_uploads(workspace_id=workspace_id)
        total_deleted += result.deleted_documents
        print(
            f"{workspace_id}: deleted_docs={result.deleted_documents} "
            f"deleted_chunks={result.deleted_chunks} remaining_docs={result.remaining_operational_documents}"
        )
    return total_deleted


if __name__ == "__main__":
    raise SystemExit(main())

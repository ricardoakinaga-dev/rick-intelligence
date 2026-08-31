#!/usr/bin/env python3
"""
Emit a bash script that repairs the local Qdrant collection from the canonical disk corpus.

The script is designed to be piped into:

    python3 src/scripts/generate_qdrant_repair_script.py | docker exec -i qdrant_rag bash -s

It uses deterministic offline embeddings so the collection can be rebuilt without an
OpenAI API key.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.embedding_service import _offline_embedding
from services.vector_service import _create_bm25_sparse
from scripts.corpus_utils import load_dataset, raw_document_path


def _point_id(chunk_id: str) -> int:
    return int.from_bytes(hashlib.sha256(chunk_id.encode("utf-8")).digest()[:8], "big") & ((1 << 63) - 1)


def main() -> int:
    dataset = load_dataset("default")
    doc_id = dataset["questions"][0]["document_id"]
    chunks_path = raw_document_path("default", doc_id).with_name(f"{doc_id}_chunks.json")
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    points = []
    for chunk in chunks:
        text = chunk["text"]
        sparse = _create_bm25_sparse(text)
        points.append(
            {
                "id": _point_id(chunk["chunk_id"]),
                "vector": {
                    "dense": _offline_embedding(text),
                    "sparse": {
                        "indices": list(sparse.indices),
                        "values": list(sparse.values),
                    },
                },
                "payload": {
                    "chunk_id": chunk["chunk_id"],
                    "document_id": chunk["document_id"],
                    "workspace_id": chunk["workspace_id"],
                    "text": text[:2000],
                    "page_hint": chunk.get("page_hint"),
                    "chunk_index": chunk["chunk_index"],
                    "strategy": chunk.get("strategy", "recursive"),
                },
            }
        )

    collection_body = json.dumps(
        {
            "vectors": {
                "dense": {
                    "size": 1536,
                    "distance": "Cosine",
                }
            },
            "sparse_vectors": {
                "sparse": {
                    "index": {"on_disk": False}
                }
            },
        },
        ensure_ascii=False,
    )
    upsert_body = json.dumps({"points": points}, ensure_ascii=False)

    print(
        f"""#!/usr/bin/env bash
set -euo pipefail

request() {{
  local method="$1"
  local path="$2"
  local body="$3"
  local len=${{#body}}
  exec 3<>/dev/tcp/127.0.0.1/6333
  printf '%s %s HTTP/1.1\\r\\nHost: localhost\\r\\nContent-Type: application/json\\r\\nContent-Length: %s\\r\\nConnection: close\\r\\n\\r\\n%s' "$method" "$path" "$len" "$body" >&3
  cat <&3
  exec 3>&-
  exec 3<&-
}}

request DELETE /collections/rag_phase0 ''

create_body='{collection_body}'
request PUT /collections/rag_phase0 "$create_body"

upsert_body='{upsert_body}'
request PUT /collections/rag_phase0/points?wait=true "$upsert_body"

request GET /collections/rag_phase0 ''
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

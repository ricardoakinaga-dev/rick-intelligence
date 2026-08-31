"""
Helpers shared by operational scripts that work against the canonical corpus.
"""
import json
from pathlib import Path

from core.config import DATA_DIR, DOCUMENTS_DIR
from models.schemas import NormalizedDocument


def dataset_path(workspace_id: str = "default") -> Path:
    return DATA_DIR / workspace_id / "dataset.json"


def load_dataset(workspace_id: str = "default") -> dict:
    path = dataset_path(workspace_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def canonical_document_ids(workspace_id: str = "default") -> set[str]:
    dataset = load_dataset(workspace_id)
    return {
        q["document_id"]
        for q in dataset.get("questions", [])
        if q.get("document_id")
    }


def raw_document_path(workspace_id: str, document_id: str) -> Path:
    return DOCUMENTS_DIR / workspace_id / f"{document_id}_raw.json"


def load_normalized_document(workspace_id: str, document_id: str) -> NormalizedDocument:
    path = raw_document_path(workspace_id, document_id)
    with open(path, "r", encoding="utf-8") as f:
        return NormalizedDocument(**json.load(f))

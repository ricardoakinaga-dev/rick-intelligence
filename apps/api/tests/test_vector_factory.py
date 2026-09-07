from __future__ import annotations

from app import create_app
from conftest import make_settings


def test_configured_local_vector_read_model_survives_factory_restart(tmp_path):
    path = tmp_path / "vectors.sqlite3"
    settings = make_settings(
        knowledge_sqlite_path=str(tmp_path / "knowledge.sqlite3"),
        vector_sqlite_path=str(path),
    )

    first = create_app(settings)
    first_vectors = first.state.providers.vector_store
    assert first_vectors.count_for_document("doc-stub-1", "rag_phase0") == 1
    first_vectors.close()

    second = create_app(settings)
    second_vectors = second.state.providers.vector_store
    points = second_vectors.all_points()
    assert len(points) == 1
    assert points[0]["payload"]["document_id"] == "doc-stub-1"
    second_vectors.close()

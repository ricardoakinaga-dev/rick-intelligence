"""Current and historical image declarations reject drift."""

from scripts.phase11.check_toolchain import check_images, check_toolchain


def test_repository_toolchain_images_match() -> None:
    assert check_toolchain() == []


def test_image_checker_rejects_drift_and_missing_service() -> None:
    expected = {"qdrant": "qdrant/qdrant:v1.12.5", "redis": "redis:7.4-alpine"}
    errors = check_images("fixture.yml", "  image: qdrant/qdrant:v1.7.4\n", expected)

    assert "fixture.yml: qdrant image qdrant/qdrant:v1.7.4 differs from qdrant/qdrant:v1.12.5" in errors
    assert "fixture.yml: redis image is missing" in errors

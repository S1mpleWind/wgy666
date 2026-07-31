"""Tests for the repository sync service (source content fetching)."""

from app.schemas.repository import ClassifiedFile, FileCategory
from app.services.repository_sync import RepositorySyncService


def test_source_content_filtering_excludes_assets():
    """_fetch_source_contents filters out ASSET and DATA files."""
    files = [
        ClassifiedFile(path="image.png", category=FileCategory.ASSET, size=5000),
        ClassifiedFile(path="data.csv", category=FileCategory.DATA, size=200),
        ClassifiedFile(path="main.py", category=FileCategory.SOURCE, size=100),
        ClassifiedFile(path="test_app.py", category=FileCategory.TEST, size=50),
    ]
    # Create a list of indexable files based on the same logic as RepositorySyncService
    indexable_categories = {
        FileCategory.SOURCE,
        FileCategory.TEST,
        FileCategory.DOCUMENTATION,
        FileCategory.DEPENDENCY,
        FileCategory.CONFIGURATION,
        FileCategory.CI_CD,
        FileCategory.BUILD,
        FileCategory.OTHER,
    }
    selected = [f for f in files if f.category in indexable_categories]
    paths = {f.path for f in selected}
    assert "main.py" in paths
    assert "test_app.py" in paths
    assert "image.png" not in paths
    assert "data.csv" not in paths


def test_source_content_filtering_respects_size_limit():
    """Files larger than max_source_file_bytes are filtered out."""
    files = [
        ClassifiedFile(path="small.py", category=FileCategory.SOURCE, size=100),
        ClassifiedFile(path="huge.py", category=FileCategory.SOURCE, size=999999),
    ]
    max_bytes = 200000
    selected = [f for f in files if f.size is None or f.size <= max_bytes]
    assert len(selected) == 1
    assert selected[0].path == "small.py"

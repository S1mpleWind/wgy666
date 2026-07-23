"""Security checks for reading files from temporary Git clones."""

import os

import pytest

from app.services.git_clone import GitCloneService


def test_walk_and_read_skip_symbolic_links(tmp_path):
    external = tmp_path.parent / "outside-secret.txt"
    external.write_text("server-only-secret", encoding="utf-8")
    link = tmp_path / "leak.txt"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("Symbolic links are not supported on this filesystem")

    service = GitCloneService("https://github.com/example/repo.git")
    service._workdir = str(tmp_path)

    assert service.walk_files() == []
    assert service.read_file("leak.txt", 1024) == (None, False)


def test_read_file_rejects_parent_directory_escape(tmp_path):
    external = tmp_path.parent / "outside.txt"
    external.write_text("outside", encoding="utf-8")
    service = GitCloneService("https://github.com/example/repo.git")
    service._workdir = str(tmp_path)

    relative_escape = os.path.join("..", external.name)
    assert service.read_file(relative_escape, 1024) == (None, False)


def test_walk_keeps_regular_files(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    service = GitCloneService("https://github.com/example/repo.git")
    service._workdir = str(tmp_path)

    assert service.walk_files() == [
        {"type": "blob", "path": "main.py", "size": source.stat().st_size}
    ]
    assert service.read_file("main.py", 1024) == ("print('ok')\n", False)

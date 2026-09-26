import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import content
from app.main import app

REPO_CONTENT = Path(__file__).resolve().parent.parent / "content"


@pytest.fixture
def client() -> Iterator[TestClient]:
    content.clear_caches()
    with TestClient(app) as c:
        yield c
    content.clear_caches()


@pytest.fixture
def content_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of content/ that the app reads instead of the real one."""
    target = tmp_path / "content"
    shutil.copytree(REPO_CONTENT, target)
    monkeypatch.setattr(content, "CONTENT_DIR", target)
    content.clear_caches()
    yield target
    content.clear_caches()

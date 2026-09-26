from pathlib import Path

import pytest

from app import context


@pytest.fixture(autouse=True)
def _fresh() -> None:
    context.clear_caches()


def test_public_content_is_included_without_todos() -> None:
    public = context.load_public()
    assert "AI feasibility check" in public
    assert "€2,950 fixed" in public
    assert "Springer Nature" in public
    assert "TODO" not in public


def test_without_private_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVATE_DIR", str(tmp_path / "does-not-exist"))
    ctx = context.assistant_context()
    assert ctx.private == ""
    assert ctx.private_files == ()
    assert "\n\n<private_notes>\n" not in context.system_prompt()
    assert "<public_site_content>" in context.system_prompt()


def test_with_private_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "b-projects.md").write_text("Built a recommender for a retailer.")
    (tmp_path / "a-notes.txt").write_text("Comfortable with Airflow.")
    (tmp_path / "README.md").write_text("folder docs, not context")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    (tmp_path / "empty.md").write_text("   ")
    monkeypatch.setenv("PRIVATE_DIR", str(tmp_path))

    ctx = context.assistant_context()
    assert ctx.private_files == ("a-notes.txt", "b-projects.md")
    assert ctx.private.index("Airflow") < ctx.private.index("recommender")
    assert "folder docs" not in ctx.private

    prompt = context.system_prompt()
    assert "\n\n<private_notes>\n" in prompt
    assert "Built a recommender for a retailer." in prompt


def test_unreadable_private_file_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xff")
    (tmp_path / "good.md").write_text("Fine.")
    monkeypatch.setenv("PRIVATE_DIR", str(tmp_path))
    assert context.assistant_context().private_files == ("good.md",)


def test_system_prompt_starts_with_editable_instructions() -> None:
    prompt = context.system_prompt()
    assert prompt.startswith(context.PROMPT_PATH.read_text(encoding="utf-8").strip()[:200])
    assert "<contact_email>freelancing@kroshtan.com</contact_email>" in prompt

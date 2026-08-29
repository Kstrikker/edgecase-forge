from pathlib import Path

from edgecase_forge.baseline.repository import collect_repository_context


def test_repository_context_excludes_secrets(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('safe')", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")
    context = collect_repository_context(tmp_path)
    assert "print('safe')" in context
    assert "secret" not in context


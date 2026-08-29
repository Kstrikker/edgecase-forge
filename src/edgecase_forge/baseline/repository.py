from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = {".py", ".toml", ".md", ".yaml", ".yml", ".json", ".ini", ".cfg"}
IGNORED_NAMES = {
    ".env",
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "solution",
    "oracle",
}
MAX_FILE_BYTES = 80_000
MAX_CONTEXT_CHARS = 180_000


def collect_repository_context(repo: Path) -> str:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"Repository does not exist: {repo}")

    sections: list[str] = []
    total = 0
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        relative = path.relative_to(repo)
        if any(part in IGNORED_NAMES or part.startswith(".env") for part in relative.parts):
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        section = f"\n--- FILE: {relative.as_posix()} ---\n{content}"
        if total + len(section) > MAX_CONTEXT_CHARS:
            break
        sections.append(section)
        total += len(section)
    return "".join(sections)


from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_app.py"
MUTATIONS = ROOT / "mutations" / "mutations.json"
OUTPUT = ROOT / "generated"

NEUTRAL_README = """# FlashCart API

Small FastAPI checkout service used for API testing evaluation.

Run with `uvicorn main:app`. The service exposes product, order, cancellation,
and payment-webhook endpoints. Use bearer tokens `buyer-a`, `buyer-b`, or
`admin` for the benchmark identities.
"""

PYPROJECT = """[project]
name = "flashcart-api"
version = "1.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.115,<1", "uvicorn>=0.30,<1"]
"""


def build_all() -> dict[str, str]:
    source = SOURCE.read_text(encoding="utf-8")
    mutation_map = json.loads(MUTATIONS.read_text(encoding="utf-8"))
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    hashes = {"C00": _write_case("C00", source)}
    for case_id, edits in mutation_map.items():
        mutated = source
        for edit in edits:
            needle = edit["find"]
            count = mutated.count(needle)
            if count != 1:
                raise ValueError(f"{case_id}: expected one mutation target, found {count}")
            mutated = mutated.replace(needle, edit["replace"], 1)
        hashes[case_id] = _write_case(case_id, mutated)

    (OUTPUT / "hashes.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return hashes


def export_agent_repo(case_id: str, destination: Path) -> Path:
    """Create a neutral repository containing one case and no evaluator hook."""
    case_dir = OUTPUT / case_id
    if not case_dir.exists():
        build_all()
    if destination.exists():
        raise FileExistsError(f"Export destination already exists: {destination}")
    destination.mkdir(parents=True)

    source = (case_dir / "main.py").read_text(encoding="utf-8")
    private_hook = "\ndef evaluator_snapshot() -> dict:\n"
    if private_hook not in source:
        raise ValueError("Evaluator hook boundary was not found")
    agent_source = source.split(private_hook, 1)[0].rstrip() + "\n"
    (destination / "main.py").write_text(agent_source, encoding="utf-8")
    shutil.copy2(case_dir / "README.md", destination / "README.md")
    shutil.copy2(case_dir / "pyproject.toml", destination / "pyproject.toml")
    return destination


def _write_case(case_id: str, source: str) -> str:
    case_dir = OUTPUT / case_id
    case_dir.mkdir()
    (case_dir / "main.py").write_text(source, encoding="utf-8")
    (case_dir / "README.md").write_text(NEUTRAL_README, encoding="utf-8")
    (case_dir / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return digest


if __name__ == "__main__":
    built = build_all()
    print(f"Built {len(built)} FlashCart variants")

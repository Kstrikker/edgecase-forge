from __future__ import annotations

from pathlib import Path

from edgecase_forge.baseline.repository import MAX_CONTEXT_CHARS, collect_repository_context
from edgecase_forge.baseline.scanner import BaselineScanner, _write_json
from edgecase_forge.llm.base import LLMProvider

from .mapper import build_repository_map, repository_map_sha256
from .prompt import CONTRACT_PROMPT_VERSION, CONTRACT_SYSTEM_PROMPT, prompt_sha256
from .schema import ContractAnalysis


class ContractScanner(BaselineScanner):
    """One-call scanner enriched by a deterministic repository contract map."""

    agent_name = "contract_mapper"
    agent_version = CONTRACT_PROMPT_VERSION
    system_prompt = CONTRACT_SYSTEM_PROMPT
    response_model = ContractAnalysis

    def __init__(self, provider: LLMProvider) -> None:
        super().__init__(provider)

    def _prepare_repository(self, repo: Path) -> tuple[str, dict]:
        repository_map = build_repository_map(repo)
        rendered_map = repository_map.render()
        priority_paths = tuple(sorted({route.source for route in repository_map.routes}))
        source_budget = max(1, MAX_CONTEXT_CHARS - len(rendered_map) - 40)
        source = collect_repository_context(
            repo,
            priority_paths=priority_paths,
            max_context_chars=source_budget,
        )
        context = f"{rendered_map}\n\n=== REPOSITORY SOURCE ==={source}"
        return context, {"repository_map": repository_map}

    def _prompt_sha256(self) -> str:
        return prompt_sha256()

    def _report_extension(self, analysis: ContractAnalysis, artifacts: dict) -> dict:
        repository_map = artifacts["repository_map"]
        return {
            "invariants": [item.model_dump() for item in analysis.invariants],
            "repository_map": "repository-map.json",
            "repository_map_sha256": repository_map_sha256(repository_map),
        }

    def _context_trajectory(self, artifacts: dict) -> dict:
        repository_map = artifacts["repository_map"]
        return {
            "repository_map_sha256": repository_map_sha256(repository_map),
            "repository_files_analyzed": len(repository_map.analyzed_files),
            "repository_routes_discovered": len(repository_map.routes),
        }

    def _write_context_artifacts(self, run_dir: Path, artifacts: dict) -> None:
        _write_json(run_dir / "repository-map.json", artifacts["repository_map"].to_dict())

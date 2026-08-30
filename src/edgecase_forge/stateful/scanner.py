from __future__ import annotations

from pathlib import Path

from edgecase_forge.baseline.scanner import _write_json
from edgecase_forge.contract.scanner import ContractScanner
from edgecase_forge.contract.schema import ContractAnalysis
from edgecase_forge.llm.base import LLMProvider

from .plan import build_attack_plan
from .prompt import STATEFUL_PROMPT_VERSION, STATEFUL_SYSTEM_PROMPT, prompt_sha256
from .validation import stateful_analysis_model


class StatefulScanner(ContractScanner):
    """Contract mapper with deterministic multi-request oracle enforcement."""

    agent_name = "stateful_attacker"
    agent_version = STATEFUL_PROMPT_VERSION
    system_prompt = STATEFUL_SYSTEM_PROMPT

    def __init__(self, provider: LLMProvider) -> None:
        super().__init__(provider)

    def _prepare_repository(self, repo: Path) -> tuple[str, dict]:
        context, artifacts = super()._prepare_repository(repo)
        attack_plan = build_attack_plan(artifacts["repository_map"])
        artifacts["attack_plan"] = attack_plan
        self.response_model = stateful_analysis_model(attack_plan)
        return f"{attack_plan.render()}\n\n{context}", artifacts

    def _prompt_sha256(self) -> str:
        return prompt_sha256()

    def _report_extension(self, analysis: ContractAnalysis, artifacts: dict) -> dict:
        extension = super()._report_extension(analysis, artifacts)
        extension.update(
            {
                "attack_plan": "attack-plan.json",
                "attack_target_signal": artifacts["attack_plan"].target_signal,
            }
        )
        return extension

    def _context_trajectory(self, artifacts: dict) -> dict:
        extension = super()._context_trajectory(artifacts)
        extension["attack_target_signal"] = artifacts["attack_plan"].target_signal
        return extension

    def _write_context_artifacts(self, run_dir: Path, artifacts: dict) -> None:
        super()._write_context_artifacts(run_dir, artifacts)
        _write_json(run_dir / "attack-plan.json", artifacts["attack_plan"].to_dict())

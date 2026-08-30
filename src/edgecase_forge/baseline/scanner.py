from __future__ import annotations

import json
import hashlib
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from edgecase_forge.llm.base import LLMProvider, Message
from edgecase_forge.llm.schemas import BaselineAnalysis

from .executor import ExecutionResult, execution_payload, run_generated_pytest
from .prompt import BASELINE_PROMPT_VERSION, BASELINE_SYSTEM_PROMPT, prompt_sha256
from .repository import collect_repository_context


class BaselineScanner:
    agent_name = "baseline"
    agent_version = BASELINE_PROMPT_VERSION
    system_prompt = BASELINE_SYSTEM_PROMPT
    response_model = BaselineAnalysis

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    @property
    def experiment_config(self) -> dict:
        return {
            "agent": self.agent_name,
            "agent_version": self.agent_version,
            "prompt_sha256": self._prompt_sha256(),
            "implementation": f"{type(self).__module__}.{type(self).__qualname__}",
        }

    def scan(
        self,
        *,
        repo: Path,
        output_root: Path,
        case_id: str = "local-case",
        execute: bool = False,
    ) -> Path:
        started = time.monotonic()
        run_id = _new_run_id()
        run_dir = output_root / run_id
        tests_dir = run_dir / "generated_tests"
        tests_dir.mkdir(parents=True, exist_ok=False)

        context, context_artifacts = self._prepare_repository(repo)
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=f"Repository contents:\n{context}"),
        ]
        analysis_raw, llm_result = self.provider.generate_json(
            messages, self.response_model
        )
        analysis = self.response_model.model_validate(analysis_raw)

        generated_path: Path | None = None
        execution = ExecutionResult(False, None, "", "")
        if analysis.generated_test_code.strip():
            generated_path = tests_dir / "test_generated_baseline.py"
            generated_path.write_text(analysis.generated_test_code, encoding="utf-8")
            if execute:
                execution = run_generated_pytest(
                    repo=repo.resolve(),
                    test_file=generated_path.resolve(),
                    junit_path=run_dir / "execution-junit.xml",
                )

        reproduced = execution.executed and execution.exit_code not in {None, 0}
        findings = []
        for finding in analysis.findings:
            item = finding.model_dump()
            if generated_path is not None:
                item["test_file"] = "generated_tests/test_generated_baseline.py"
            item["reproduced"] = reproduced
            findings.append(item)

        report = {
            "run_id": run_id,
            "case_id": case_id,
            "status": "completed",
            "summary": analysis.summary,
            "findings": findings,
            "tests_generated": int(generated_path is not None),
            "tests_executed": int(execution.executed),
            "runtime_seconds": round(time.monotonic() - started, 4),
            "input_tokens": llm_result.usage.input_tokens,
            "output_tokens": llm_result.usage.output_tokens,
            "model_latency_seconds": round(llm_result.latency_seconds, 4),
            "semantic_attempts": llm_result.semantic_attempts,
            "transport_attempts": llm_result.transport_attempts,
            "repair_used": llm_result.repair_used,
            "request_ids": list(llm_result.accounting.request_ids),
            "finish_reasons": list(llm_result.accounting.finish_reasons),
            "execution": execution_payload(execution),
        }
        report.update(self._report_extension(analysis, context_artifacts))
        metadata = {
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "agent": self.agent_name,
            "agent_version": self.agent_version,
            "prompt_sha256": self._prompt_sha256(),
            "provider": llm_result.provider,
            "model": llm_result.model,
            "temperature": 0.0,
            "repository": str(repo.resolve()),
            "case_id": case_id,
        }
        trajectory = [
            {
                "event": "model_request",
                "agent": self.agent_name,
                "prompt_version": self.agent_version,
                "prompt_sha256": self._prompt_sha256(),
                "repository_context_chars": len(context),
                **self._context_trajectory(context_artifacts),
            },
            {
                "event": "model_response",
                "provider": llm_result.provider,
                "model": llm_result.model,
                "request_id": llm_result.request_id,
                "latency_seconds": llm_result.latency_seconds,
                "usage": asdict(llm_result.usage),
                "semantic_attempts": llm_result.semantic_attempts,
                "transport_attempts": llm_result.transport_attempts,
                "repair_used": llm_result.repair_used,
                "finish_reasons": list(llm_result.accounting.finish_reasons),
                "validated_output": analysis.model_dump(),
            },
            {"event": "pytest_execution", **execution_payload(execution)},
        ]

        _write_json(run_dir / "report.json", report)
        _write_json(run_dir / "run-metadata.json", metadata)
        self._write_context_artifacts(run_dir, context_artifacts)
        with (run_dir / "trajectory.jsonl").open("w", encoding="utf-8") as handle:
            for event in trajectory:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        (run_dir / "execution.log").write_text(
            execution.stdout + ("\nSTDERR\n" + execution.stderr if execution.stderr else ""),
            encoding="utf-8",
        )
        return run_dir

    def _prepare_repository(self, repo: Path) -> tuple[str, dict]:
        return collect_repository_context(repo), {}

    def _prompt_sha256(self) -> str:
        if self.agent_name == "baseline":
            return prompt_sha256()
        return hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()

    def _report_extension(self, analysis: BaselineAnalysis, artifacts: dict) -> dict:
        del analysis, artifacts
        return {}

    def _context_trajectory(self, artifacts: dict) -> dict:
        del artifacts
        return {}

    def _write_context_artifacts(self, run_dir: Path, artifacts: dict) -> None:
        del run_dir, artifacts


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

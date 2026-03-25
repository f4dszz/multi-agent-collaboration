from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.app.domain.models import Decision, FindingStatus, RunState, TimelineEvent
from backend.app.domain.state_machine import WorkflowRun
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.cli_adapters import CommandResult, ProviderRegistry
from backend.app.services.repository import WorkflowRepository
from backend.app.services.review_parser import parse_review_output


PROJECT_SLUG = "local-agent-workflow-orchestrator"
PROJECT_NAME = "Local Agent Workflow Orchestrator"
PROJECT_DESCRIPTION = "Local-first orchestration workspace for Codex CLI and Claude Code CLI."


class RuntimeWorkflowService:
    def __init__(self, runtime_root: Path | str) -> None:
        self.runtime_root = Path(runtime_root)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.snapshot_root = self.runtime_root / "runs"
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self.repository = WorkflowRepository(self.runtime_root / "orchestrator.db")
        self.repository.initialize()
        self.repository.create_project(PROJECT_SLUG, PROJECT_NAME, PROJECT_DESCRIPTION)
        self.artifact_store = ArtifactStore(self.runtime_root / "artifacts")
        self.providers = ProviderRegistry()

    def get_provider_statuses(self) -> list[dict[str, object]]:
        return [asdict(status) for status in self.providers.statuses()]

    def get_last_run(self) -> dict[str, object] | None:
        snapshot = self.runtime_root / "last_run.json"
        if not snapshot.exists():
            return None
        return json.loads(snapshot.read_text(encoding="utf-8"))

    def run_plan_cycle(
        self,
        *,
        task: str,
        workspace: str,
        executor_provider: str,
        reviewer_provider: str,
        verifier_provider: str | None = None,
        auto_revision: bool = True,
    ) -> dict[str, object]:
        workspace_path = str(Path(workspace).resolve())
        run = WorkflowRun(project_slug=PROJECT_SLUG, run_id=self._new_run_id())
        self.repository.create_run(run.run_id, run.project_slug, run.workflow_name, run.state.value)
        persisted_events = self._persist_timeline_delta(run, 0)
        results: list[dict[str, object]] = []

        executor = self.providers.get(executor_provider)
        reviewer = self.providers.get(reviewer_provider)
        verifier = self.providers.get(verifier_provider) if verifier_provider else None

        plan_result = executor.execute(
            self._plan_prompt(task),
            workspace=workspace_path,
            system_prompt=self._executor_system_prompt(),
            additional_dirs=[str(self.runtime_root)],
        )
        results.append(self._serialize_result(plan_result, "executor"))
        if not plan_result.success:
            self._block_run(run, f"{executor_provider} failed while drafting the plan")
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self._persist_timeline_delta(run, persisted_events)
            snapshot = self._snapshot(run, task, workspace_path, results)
            self._write_snapshot(snapshot)
            return snapshot

        plan_artifact = self.artifact_store.write_text_artifact(
            PROJECT_SLUG,
            run.run_id,
            "plan",
            1,
            plan_result.output_text or plan_result.stdout or plan_result.stderr,
        )
        run.submit_plan(plan_artifact)
        self.repository.add_artifact(run.run_id, plan_artifact.artifact_id, plan_artifact.kind, plan_artifact.version, plan_artifact.path, plan_artifact.content_type)
        persisted_events = self._persist_timeline_delta(run, persisted_events)
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)

        review_result = reviewer.review_text(
            self._review_prompt(task, plan_artifact.path),
            workspace=workspace_path,
            system_prompt=self._reviewer_system_prompt(),
            additional_dirs=[str(self.runtime_root)],
        )
        results.append(self._serialize_result(review_result, "reviewer"))
        if not review_result.success:
            self._block_run(run, f"{reviewer_provider} failed while reviewing the plan")
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            persisted_events = self._persist_timeline_delta(run, persisted_events)
            snapshot = self._snapshot(run, task, workspace_path, results)
            self._write_snapshot(snapshot)
            return snapshot

        review_artifact = self.artifact_store.write_text_artifact(
            PROJECT_SLUG,
            run.run_id,
            "review",
            1,
            review_result.output_text or review_result.stdout or review_result.stderr,
        )
        self.repository.add_artifact(run.run_id, review_artifact.artifact_id, review_artifact.kind, review_artifact.version, review_artifact.path, review_artifact.content_type)
        review_record = parse_review_output(Path(review_artifact.path).read_text(encoding="utf-8"))
        for finding in review_record.findings:
            self.repository.add_finding(
                run.run_id,
                finding.key,
                finding.title,
                finding.detail,
                finding.severity.value,
                finding.status.value,
            )
        run.record_plan_review(review_record)
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        persisted_events = self._persist_timeline_delta(run, persisted_events)

        if verifier and (run.requires_verifier or bool(verifier_provider)):
            verifier_result = verifier.review_text(
                self._verifier_prompt(plan_artifact.path, review_artifact.path),
                workspace=workspace_path,
                system_prompt=self._verifier_system_prompt(),
                additional_dirs=[str(self.runtime_root)],
            )
            results.append(self._serialize_result(verifier_result, "verifier"))
            verification_artifact = self.artifact_store.write_text_artifact(
                PROJECT_SLUG,
                run.run_id,
                "verification",
                1,
                verifier_result.output_text or verifier_result.stdout or verifier_result.stderr,
            )
            self.repository.add_artifact(
                run.run_id,
                verification_artifact.artifact_id,
                verification_artifact.kind,
                verification_artifact.version,
                verification_artifact.path,
                verification_artifact.content_type,
            )

        if auto_revision and review_record.decision is Decision.REVISE:
            revision_result = executor.execute(
                self._revision_prompt(task, plan_artifact.path, review_artifact.path),
                workspace=workspace_path,
                system_prompt=self._executor_system_prompt(),
                additional_dirs=[str(self.runtime_root)],
            )
            results.append(self._serialize_result(revision_result, "executor-revision"))
            if revision_result.success:
                revised_plan = self.artifact_store.write_text_artifact(
                    PROJECT_SLUG,
                    run.run_id,
                    "plan",
                    2,
                    revision_result.output_text or revision_result.stdout or revision_result.stderr,
                )
                self.repository.add_artifact(
                    run.run_id,
                    revised_plan.artifact_id,
                    revised_plan.kind,
                    revised_plan.version,
                    revised_plan.path,
                    revised_plan.content_type,
                )
                resolved_keys = [finding.key for finding in review_record.findings]
                run.submit_plan_revision(resolved_keys, revised_plan)
                for finding_key in resolved_keys:
                    self.repository.update_finding_status(run.run_id, finding_key, FindingStatus.ADDRESSED.value)
                self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
                persisted_events = self._persist_timeline_delta(run, persisted_events)
            else:
                self._block_run(run, f"{executor_provider} failed while revising the plan")
                self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
                persisted_events = self._persist_timeline_delta(run, persisted_events)

        snapshot = self._snapshot(run, task, workspace_path, results)
        self._write_snapshot(snapshot)
        return snapshot

    def run_repo_review(
        self,
        *,
        provider_name: str,
        workspace: str,
        prompt: str,
        base_branch: str | None = None,
    ) -> dict[str, object]:
        provider = self.providers.get(provider_name)
        result = provider.review_repo(prompt, workspace=str(Path(workspace).resolve()), base_branch=base_branch)
        return self._serialize_result(result, "repo-review")

    def _snapshot(
        self,
        run: WorkflowRun,
        task: str,
        workspace: str,
        task_results: list[dict[str, object]],
    ) -> dict[str, object]:
        artifacts = []
        for row in self.repository.list_artifacts(run.run_id):
            path = Path(row["path"])
            artifacts.append(
                {
                    "artifact_id": row["artifact_id"],
                    "kind": row["kind"],
                    "version": row["version"],
                    "path": row["path"],
                    "content_type": row["content_type"],
                    "content": path.read_text(encoding="utf-8") if path.exists() else "",
                }
            )
        findings = [
            {
                "key": row["finding_key"],
                "title": row["title"],
                "detail": row["detail"],
                "severity": row["severity"],
                "status": row["status"],
            }
            for row in self.repository.list_findings(run.run_id)
        ]
        timeline = [
            {
                "state": row["state"],
                "message": row["message"],
            }
            for row in self.repository.list_timeline_events(run.run_id)
        ]
        return {
            "run_id": run.run_id,
            "task": task,
            "workspace": workspace,
            "state": run.state.value,
            "requires_verifier": run.requires_verifier,
            "artifacts": artifacts,
            "findings": findings,
            "timeline": timeline,
            "task_results": task_results,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _write_snapshot(self, snapshot: dict[str, object]) -> None:
        run_id = str(snapshot["run_id"])
        run_file = self.snapshot_root / f"{run_id}.json"
        run_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.runtime_root / "last_run.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_timeline_delta(self, run: WorkflowRun, from_index: int) -> int:
        for event in run.timeline[from_index:]:
            self.repository.add_timeline_event(run.run_id, event.state.value, event.message)
        return len(run.timeline)

    def _block_run(self, run: WorkflowRun, message: str) -> None:
        run.state = RunState.BLOCKED
        run.timeline.append(TimelineEvent(RunState.BLOCKED, message))

    def _serialize_result(self, result: CommandResult, role: str) -> dict[str, object]:
        return {
            "role": role,
            "provider": result.provider,
            "operation": result.operation,
            "success": result.success,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "command": list(result.command),
            "cwd": result.cwd,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output_text": result.output_text,
            "notes": result.notes,
        }

    def _new_run_id(self) -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]

    def _executor_system_prompt(self) -> str:
        return (
            "You are the Executor role in a local agent workflow orchestrator.\n"
            "Be concrete and implementation-oriented.\n"
            "Do not flatter the reviewer.\n"
            "Return markdown that is easy to audit."
        )

    def _reviewer_system_prompt(self) -> str:
        return (
            "You are the Reviewer role in a strict local agent workflow.\n"
            "You must be critical, objective, and non-accommodating.\n"
            "Return exactly this structure:\n"
            "Decision: approve|revise|reject\n"
            "Risk-Tags: comma,separated,tags or none\n"
            "Blockers:\n"
            "- B1 | short title | detailed explanation\n"
            "Concerns:\n"
            "- C1 | short title | detailed explanation\n"
            "Suggestions:\n"
            "- S1 | short title | detailed explanation\n"
            "Summary:\n"
            "- brief summary\n"
            "If a section has no items, keep the heading and write `- none`."
        )

    def _verifier_system_prompt(self) -> str:
        return (
            "You are the Verifier/Judge role.\n"
            "Your job is to arbitrate or validate, not to praise.\n"
            "Return a short memo with sections Verdict, Recommended-Action, Reasons."
        )

    def _plan_prompt(self, task: str) -> str:
        return (
            "Create a first implementation plan for the following project task.\n"
            "Return markdown with sections: Objective, Scope, Implementation Steps, Risks, Acceptance Criteria, Open Questions.\n\n"
            f"Task:\n{task}"
        )

    def _review_prompt(self, task: str, plan_path: str) -> str:
        return (
            "Review the executor's plan strictly.\n"
            f"Project task:\n{task}\n\n"
            f"Read the draft plan from this file: {plan_path}\n"
            "Check for drift, missing constraints, weak acceptance criteria, unrealistic sequencing, and hidden risks."
        )

    def _revision_prompt(self, task: str, plan_path: str, review_path: str) -> str:
        return (
            "Revise the plan after review.\n"
            f"Project task:\n{task}\n\n"
            f"Read the original plan from: {plan_path}\n"
            f"Read the review from: {review_path}\n"
            "Return markdown with sections: Response to Findings, Revised Plan, Remaining Risks."
        )

    def _verifier_prompt(self, plan_path: str, review_path: str) -> str:
        return (
            f"Read the executor plan from: {plan_path}\n"
            f"Read the reviewer output from: {review_path}\n"
            "Assess whether the reviewer is directionally correct and whether the plan should continue revision."
        )

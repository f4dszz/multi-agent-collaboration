from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.app.domain.models import ArtifactRef, Decision, Finding, FindingSeverity, FindingStatus, RunState, TimelineEvent
from backend.app.domain.state_machine import InvalidTransitionError, WorkflowRun
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.cli_adapters import CommandResult, ProviderRegistry
from backend.app.services.plan_parser import extract_implementation_steps
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

    def list_runs(self) -> list[dict[str, object]]:
        runs = []
        for row in self.repository.list_runs():
            runs.append(
                {
                    "run_id": row["run_id"],
                    "project_slug": row["project_slug"],
                    "workflow_name": row["workflow_name"],
                    "state": row["state"],
                    "requires_verifier": bool(row["requires_verifier"]),
                    "task": row["task"] or "",
                    "workspace": row["workspace"] or "",
                    "current_step_index": row["current_step_index"] or 0,
                    "approval_mode": row["approval_mode"] or "once",
                    "updated_at": row["updated_at"] or "",
                }
            )
        return runs

    def get_run(self, run_id: str) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        snapshot = self._snapshot(run, context)
        self._write_snapshot(snapshot)
        return snapshot

    def create_run(
        self,
        *,
        task: str,
        workspace: str,
        executor_provider: str,
        reviewer_provider: str,
        verifier_provider: str | None = None,
        max_plan_rounds: int = 2,
    ) -> dict[str, object]:
        workspace_path = str(Path(workspace).resolve())
        now = self._timestamp()
        run = WorkflowRun(project_slug=PROJECT_SLUG, run_id=self._new_run_id())
        self.repository.create_run(run.run_id, run.project_slug, run.workflow_name, run.state.value)
        self.repository.create_run_context(
            run.run_id,
            task=task,
            workspace=workspace_path,
            executor_provider=executor_provider,
            reviewer_provider=reviewer_provider,
            verifier_provider=verifier_provider or "",
            max_plan_rounds=max(0, max_plan_rounds),
            approval_mode="once",
            created_at=now,
        )
        self._persist_timeline_delta(run, 0)
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self.repository.update_run_context(run.run_id, updated_at=now)
        return self._run_plan_discussion(run.run_id)

    def continue_run(self, run_id: str) -> dict[str, object]:
        run, _context = self._hydrate_run(run_id)
        if run.state in {RunState.DRAFTING_PLAN, RunState.PLAN_REVIEW, RunState.PLAN_REVISION}:
            return self._run_plan_discussion(run_id)
        if run.state is RunState.IMPLEMENTING:
            return self._advance_execution(run_id)
        raise ValueError(f"Run {run_id} cannot continue from state {run.state.value}")

    def decide_plan(
        self,
        run_id: str,
        *,
        approved: bool,
        comment: str,
        checkpoint_step_indices: list[int],
    ) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        if run.state is not RunState.AWAITING_PLAN_APPROVAL:
            raise ValueError(f"Run {run_id} is not waiting for plan approval")

        persisted_events = len(run.timeline)
        self.repository.add_approval(run_id, "plan_gate", approved, comment)

        if not approved:
            run.state = RunState.PLAN_REVISION
            run.timeline.append(TimelineEvent(RunState.PLAN_REVISION, "Human requested plan changes"))
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self._persist_timeline_delta(run, persisted_events)
            self.repository.update_run_context(run.run_id, updated_at=self._timestamp())
            snapshot = self._snapshot(run, context)
            self._write_snapshot(snapshot)
            return snapshot

        latest_plan = self._latest_artifact(run.run_id, "plan")
        if latest_plan is None:
            raise ValueError(f"Run {run_id} has no plan artifact to approve")

        parsed_steps = extract_implementation_steps(Path(latest_plan.path).read_text(encoding="utf-8"))
        steps_to_store = []
        selected = {int(value) for value in checkpoint_step_indices}
        for step in parsed_steps:
            steps_to_store.append(
                {
                    "step_index": int(step["step_index"]),
                    "title": str(step["title"]),
                    "detail": str(step["detail"]),
                    "requires_approval": int(step["step_index"]) in selected,
                    "status": "pending",
                }
            )

        self.repository.replace_execution_steps(run.run_id, steps_to_store)
        approval_mode = "selected_checkpoints" if selected else "once"
        run.approve_plan()
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self._persist_timeline_delta(run, persisted_events)
        self.repository.update_run_context(
            run.run_id,
            current_step_index=1 if steps_to_store else 0,
            approval_mode=approval_mode,
            updated_at=self._timestamp(),
        )
        return self._advance_execution(run.run_id)

    def decide_checkpoint(
        self,
        run_id: str,
        *,
        step_index: int,
        approved: bool,
        comment: str,
    ) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        if run.state is not RunState.AWAITING_CHECKPOINT_APPROVAL:
            raise ValueError(f"Run {run_id} is not waiting for checkpoint approval")

        persisted_events = len(run.timeline)
        self.repository.add_approval(run_id, f"checkpoint:{step_index}", approved, comment)

        if approved:
            self.repository.update_execution_step(run.run_id, step_index, status="completed", notes=comment)
            run.state = RunState.IMPLEMENTING
            run.timeline.append(TimelineEvent(RunState.IMPLEMENTING, f"Human approved checkpoint after step {step_index}"))
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self._persist_timeline_delta(run, persisted_events)
            self.repository.update_run_context(run.run_id, updated_at=self._timestamp())
            return self._advance_execution(run.run_id)

        self.repository.update_execution_step(run.run_id, step_index, status="pending", notes=comment)
        run.state = RunState.IMPLEMENTING
        run.timeline.append(TimelineEvent(RunState.IMPLEMENTING, f"Human requested rework for step {step_index}"))
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self._persist_timeline_delta(run, persisted_events)
        self.repository.update_run_context(run.run_id, current_step_index=step_index, updated_at=self._timestamp())
        snapshot = self._snapshot(run, context)
        self._write_snapshot(snapshot)
        return snapshot

    def finalize_run(self, run_id: str, *, approved: bool, comment: str) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        if run.state is not RunState.AWAITING_FINAL_APPROVAL:
            raise ValueError(f"Run {run_id} is not waiting for final approval")

        persisted_events = len(run.timeline)
        self.repository.add_approval(run_id, "final_gate", approved, comment)
        if approved:
            run.finalize(True)
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self._persist_timeline_delta(run, persisted_events)
            self.repository.update_run_context(run.run_id, updated_at=self._timestamp())
            snapshot = self._snapshot(run, context)
            self._write_snapshot(snapshot)
            return snapshot

        steps = self._list_execution_steps(run.run_id)
        if steps:
            last_step = steps[-1]
            self.repository.update_execution_step(
                run.run_id,
                int(last_step["step_index"]),
                status="pending",
                notes=comment,
            )
            self.repository.update_run_context(
                run.run_id,
                current_step_index=int(last_step["step_index"]),
                updated_at=self._timestamp(),
            )
        run.finalize(False)
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self._persist_timeline_delta(run, persisted_events)
        snapshot = self._snapshot(run, context)
        self._write_snapshot(snapshot)
        return snapshot

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
        return self.create_run(
            task=task,
            workspace=workspace,
            executor_provider=executor_provider,
            reviewer_provider=reviewer_provider,
            verifier_provider=verifier_provider,
            max_plan_rounds=2 if auto_revision else 0,
        )

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

    def _run_plan_discussion(self, run_id: str) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        persisted_events = len(run.timeline)
        executor = self.providers.get(str(context["executor_provider"]))
        reviewer = self.providers.get(str(context["reviewer_provider"]))
        verifier_name = str(context["verifier_provider"]).strip()
        verifier = self.providers.get(verifier_name) if verifier_name else None
        workspace = str(context["workspace"])
        task = str(context["task"])

        while True:
            if run.state is RunState.DRAFTING_PLAN:
                plan_result = executor.execute(
                    self._plan_prompt(task),
                    workspace=workspace,
                    system_prompt=self._executor_system_prompt(),
                    additional_dirs=[str(self.runtime_root)],
                )
                self._record_command_result(run.run_id, plan_result, "executor")
                if not plan_result.success:
                    self._block_run(run, f"{context['executor_provider']} failed while drafting the plan")
                    break
                plan_artifact = self.artifact_store.write_text_artifact(
                    PROJECT_SLUG,
                    run.run_id,
                    "plan",
                    self._next_artifact_version(run.run_id, "plan"),
                    plan_result.output_text or plan_result.stdout or plan_result.stderr,
                )
                run.submit_plan(plan_artifact)
                self.repository.add_artifact(
                    run.run_id,
                    plan_artifact.artifact_id,
                    plan_artifact.kind,
                    plan_artifact.version,
                    plan_artifact.path,
                    plan_artifact.content_type,
                )
                self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
                persisted_events = self._persist_timeline_delta(run, persisted_events)

            if run.state is RunState.PLAN_REVISION:
                if run.plan_revision_rounds > int(context["max_plan_rounds"]):
                    run.timeline.append(
                        TimelineEvent(RunState.PLAN_REVISION, "Plan discussion paused after max auto-revision rounds")
                    )
                    break
                latest_plan = self._latest_artifact(run.run_id, "plan")
                latest_review = self._latest_artifact(run.run_id, "review")
                if latest_plan is None or latest_review is None:
                    self._block_run(run, "Missing plan or review artifact for plan revision")
                    break
                revision_result = executor.execute(
                    self._revision_prompt(task, latest_plan.path, latest_review.path),
                    workspace=workspace,
                    system_prompt=self._executor_system_prompt(),
                    additional_dirs=[str(self.runtime_root)],
                )
                self._record_command_result(run.run_id, revision_result, "executor-revision")
                if not revision_result.success:
                    self._block_run(run, f"{context['executor_provider']} failed while revising the plan")
                    break
                revised_plan = self.artifact_store.write_text_artifact(
                    PROJECT_SLUG,
                    run.run_id,
                    "plan",
                    self._next_artifact_version(run.run_id, "plan"),
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
                resolved_keys = [finding.key for finding in run.findings.values()]
                run.submit_plan_revision(resolved_keys, revised_plan)
                for finding_key in resolved_keys:
                    self.repository.update_finding_status(run.run_id, finding_key, FindingStatus.ADDRESSED.value)
                self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
                persisted_events = self._persist_timeline_delta(run, persisted_events)

            if run.state is not RunState.PLAN_REVIEW:
                break

            latest_plan = self._latest_artifact(run.run_id, "plan")
            if latest_plan is None:
                self._block_run(run, "Missing plan artifact for review")
                break

            review_result = reviewer.review_text(
                self._review_prompt(task, latest_plan.path),
                workspace=workspace,
                system_prompt=self._reviewer_system_prompt(),
                additional_dirs=[str(self.runtime_root)],
            )
            self._record_command_result(run.run_id, review_result, "reviewer")
            if not review_result.success:
                self._block_run(run, f"{context['reviewer_provider']} failed while reviewing the plan")
                break
            review_artifact = self.artifact_store.write_text_artifact(
                PROJECT_SLUG,
                run.run_id,
                "review",
                self._next_artifact_version(run.run_id, "review"),
                review_result.output_text or review_result.stdout or review_result.stderr,
            )
            self.repository.add_artifact(
                run.run_id,
                review_artifact.artifact_id,
                review_artifact.kind,
                review_artifact.version,
                review_artifact.path,
                review_artifact.content_type,
            )
            review_record = parse_review_output(Path(review_artifact.path).read_text(encoding="utf-8"))
            self._persist_findings(run.run_id, review_record.findings)

            try:
                run.record_plan_review(review_record)
            except InvalidTransitionError as exc:
                self._block_run(run, str(exc))
                break

            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self.repository.update_run_context(
                run.run_id,
                plan_revision_rounds=run.plan_revision_rounds,
                updated_at=self._timestamp(),
            )
            persisted_events = self._persist_timeline_delta(run, persisted_events)

            if verifier and (run.requires_verifier or bool(verifier_name)):
                verifier_result = verifier.review_text(
                    self._verifier_prompt(latest_plan.path, review_artifact.path),
                    workspace=workspace,
                    system_prompt=self._verifier_system_prompt(),
                    additional_dirs=[str(self.runtime_root)],
                )
                self._record_command_result(run.run_id, verifier_result, "verifier")
                verification_artifact = self.artifact_store.write_text_artifact(
                    PROJECT_SLUG,
                    run.run_id,
                    "verification",
                    self._next_artifact_version(run.run_id, "verification"),
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

            if run.state is RunState.AWAITING_PLAN_APPROVAL:
                break

        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self.repository.update_run_context(
            run.run_id,
            plan_revision_rounds=run.plan_revision_rounds,
            updated_at=self._timestamp(),
        )
        persisted_events = self._persist_timeline_delta(run, persisted_events)
        snapshot = self._snapshot(run, context)
        self._write_snapshot(snapshot)
        return snapshot

    def _advance_execution(self, run_id: str) -> dict[str, object]:
        run, context = self._hydrate_run(run_id)
        if run.state is not RunState.IMPLEMENTING:
            raise ValueError(f"Run {run_id} is not implementing")

        persisted_events = len(run.timeline)
        executor = self.providers.get(str(context["executor_provider"]))
        reviewer = self.providers.get(str(context["reviewer_provider"]))
        workspace = str(context["workspace"])
        task = str(context["task"])
        latest_plan = self._latest_artifact(run.run_id, "plan")
        if latest_plan is None:
            self._block_run(run, "Cannot execute without an approved plan")
            self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
            self._persist_timeline_delta(run, persisted_events)
            snapshot = self._snapshot(run, context)
            self._write_snapshot(snapshot)
            return snapshot

        while True:
            steps = self._list_execution_steps(run.run_id)
            next_step = self._next_pending_step(steps, int(context["current_step_index"] or 1))
            if next_step is None:
                run.state = RunState.AWAITING_FINAL_APPROVAL
                run.timeline.append(
                    TimelineEvent(RunState.AWAITING_FINAL_APPROVAL, "Execution finished. Awaiting final approval")
                )
                break

            step_index = int(next_step["step_index"])
            step_title = str(next_step["title"])
            step_detail = str(next_step["detail"])
            run.timeline.append(TimelineEvent(RunState.IMPLEMENTING, f"Executor started step {step_index}: {step_title}"))
            persisted_events = self._persist_timeline_delta(run, persisted_events)

            implementation_result = executor.execute(
                self._implementation_prompt(task, latest_plan.path, step_index, step_title, step_detail, steps),
                workspace=workspace,
                system_prompt=self._executor_system_prompt(),
                additional_dirs=[str(self.runtime_root)],
            )
            self._record_command_result(run.run_id, implementation_result, "executor-step")
            if not implementation_result.success:
                self._block_run(run, f"{context['executor_provider']} failed on step {step_index}")
                break
            implementation_artifact = self.artifact_store.write_text_artifact(
                PROJECT_SLUG,
                run.run_id,
                "implementation",
                self._next_artifact_version(run.run_id, "implementation"),
                implementation_result.output_text or implementation_result.stdout or implementation_result.stderr,
            )
            self.repository.add_artifact(
                run.run_id,
                implementation_artifact.artifact_id,
                implementation_artifact.kind,
                implementation_artifact.version,
                implementation_artifact.path,
                implementation_artifact.content_type,
            )

            review_result = reviewer.review_text(
                self._implementation_review_prompt(
                    task,
                    latest_plan.path,
                    implementation_artifact.path,
                    step_index,
                    step_title,
                ),
                workspace=workspace,
                system_prompt=self._reviewer_system_prompt(),
                additional_dirs=[str(self.runtime_root)],
            )
            self._record_command_result(run.run_id, review_result, "reviewer-step")
            if not review_result.success:
                self._block_run(run, f"{context['reviewer_provider']} failed while reviewing step {step_index}")
                break

            review_artifact = self.artifact_store.write_text_artifact(
                PROJECT_SLUG,
                run.run_id,
                "review",
                self._next_artifact_version(run.run_id, "review"),
                review_result.output_text or review_result.stdout or review_result.stderr,
            )
            self.repository.add_artifact(
                run.run_id,
                review_artifact.artifact_id,
                review_artifact.kind,
                review_artifact.version,
                review_artifact.path,
                review_artifact.content_type,
            )

            review_record = parse_review_output(Path(review_artifact.path).read_text(encoding="utf-8"))
            prefixed_findings = []
            for finding in review_record.findings:
                prefixed_findings.append(
                    Finding(
                        key=f"S{step_index}-{finding.key}",
                        title=finding.title,
                        detail=finding.detail,
                        severity=finding.severity,
                        status=finding.status,
                        source_role=finding.source_role,
                    )
                )
            self._persist_findings(run.run_id, prefixed_findings)

            if review_record.decision is not Decision.APPROVE:
                self.repository.update_execution_step(
                    run.run_id,
                    step_index,
                    status="blocked",
                    implementation_artifact_id=implementation_artifact.artifact_id,
                    review_artifact_id=review_artifact.artifact_id,
                    notes="Reviewer requested changes on this step.",
                )
                self.repository.update_run_context(
                    run.run_id,
                    current_step_index=step_index,
                    implementation_revision_rounds=int(context["implementation_revision_rounds"]) + 1,
                    updated_at=self._timestamp(),
                )
                self._block_run(run, f"Reviewer requested changes on step {step_index}")
                break

            self.repository.update_execution_step(
                run.run_id,
                step_index,
                status="awaiting_approval" if bool(next_step["requires_approval"]) else "completed",
                implementation_artifact_id=implementation_artifact.artifact_id,
                review_artifact_id=review_artifact.artifact_id,
            )
            self.repository.update_run_context(
                run.run_id,
                current_step_index=step_index + 1,
                updated_at=self._timestamp(),
            )

            if bool(next_step["requires_approval"]):
                run.state = RunState.AWAITING_CHECKPOINT_APPROVAL
                run.timeline.append(
                    TimelineEvent(
                        RunState.AWAITING_CHECKPOINT_APPROVAL,
                        f"Step {step_index} completed. Awaiting human approval before continuing.",
                    )
                )
                break

            run.timeline.append(TimelineEvent(RunState.IMPLEMENTING, f"Step {step_index} completed"))
            persisted_events = self._persist_timeline_delta(run, persisted_events)
            context = self.repository.get_run_context(run.run_id)
            if context is None:
                raise ValueError(f"Missing context for run {run.run_id}")

        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        self.repository.update_run_context(run.run_id, updated_at=self._timestamp())
        self._persist_timeline_delta(run, persisted_events)
        snapshot = self._snapshot(run, context)
        self._write_snapshot(snapshot)
        return snapshot

    def _snapshot(self, run: WorkflowRun, context: dict[str, object]) -> dict[str, object]:
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
        approvals = [
            {
                "approval_id": row["approval_id"],
                "stage": row["stage"],
                "approved": bool(row["approved"]),
                "comment": row["comment"],
            }
            for row in self.repository.list_approvals(run.run_id)
        ]

        steps = []
        stored_steps = self._list_execution_steps(run.run_id)
        if stored_steps:
            for row in stored_steps:
                steps.append(
                    {
                        "step_index": row["step_index"],
                        "title": row["title"],
                        "detail": row["detail"],
                        "requires_approval": bool(row["requires_approval"]),
                        "status": row["status"],
                        "implementation_artifact_id": row["implementation_artifact_id"],
                        "review_artifact_id": row["review_artifact_id"],
                        "notes": row["notes"],
                    }
                )
        else:
            latest_plan = self._latest_artifact(run.run_id, "plan")
            if latest_plan is not None:
                for step in extract_implementation_steps(Path(latest_plan.path).read_text(encoding="utf-8")):
                    steps.append(
                        {
                            "step_index": step["step_index"],
                            "title": step["title"],
                            "detail": step["detail"],
                            "requires_approval": False,
                            "status": "pending",
                            "implementation_artifact_id": "",
                            "review_artifact_id": "",
                            "notes": "",
                        }
                    )

        command_results = []
        for row in self.repository.list_command_results(run.run_id):
            command_results.append(
                {
                    "role": row["role"],
                    "provider": row["provider"],
                    "operation": row["operation"],
                    "success": bool(row["success"]),
                    "exit_code": row["exit_code"],
                    "duration_ms": row["duration_ms"],
                    "command": json.loads(row["command"]),
                    "cwd": row["cwd"],
                    "stdout": row["stdout"],
                    "stderr": row["stderr"],
                    "output_text": row["output_text"],
                    "notes": json.loads(row["notes"]) if row["notes"] else [],
                    "created_at": row["created_at"],
                }
            )

        current_step = next((step for step in steps if step["status"] in {"pending", "awaiting_approval"}), None)
        return {
            "run_id": run.run_id,
            "project_slug": run.project_slug,
            "workflow_name": run.workflow_name,
            "task": str(context["task"]),
            "workspace": str(context["workspace"]),
            "state": run.state.value,
            "requires_verifier": run.requires_verifier,
            "approval_mode": str(context["approval_mode"]),
            "current_step_index": int(context["current_step_index"]),
            "current_step": current_step,
            "steps": steps,
            "approvals": approvals,
            "artifacts": artifacts,
            "findings": findings,
            "timeline": timeline,
            "task_results": command_results,
            "can_continue": run.state in {RunState.PLAN_REVISION, RunState.IMPLEMENTING},
            "can_approve_plan": run.state is RunState.AWAITING_PLAN_APPROVAL,
            "can_approve_checkpoint": run.state is RunState.AWAITING_CHECKPOINT_APPROVAL,
            "can_finalize": run.state is RunState.AWAITING_FINAL_APPROVAL,
            "generated_at": self._timestamp(),
        }

    def _write_snapshot(self, snapshot: dict[str, object]) -> None:
        run_id = str(snapshot["run_id"])
        run_file = self.snapshot_root / f"{run_id}.json"
        run_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.runtime_root / "last_run.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _hydrate_run(self, run_id: str) -> tuple[WorkflowRun, dict[str, object]]:
        row = self.repository.get_run(run_id)
        if row is None:
            raise ValueError(f"Unknown run: {run_id}")
        context_row = self.repository.get_run_context(run_id)
        if context_row is None:
            raise ValueError(f"Missing context for run: {run_id}")

        run = WorkflowRun(
            project_slug=row["project_slug"],
            run_id=row["run_id"],
            workflow_name=row["workflow_name"],
            state=RunState(row["state"]),
            requires_verifier=bool(row["requires_verifier"]),
            plan_revision_rounds=int(context_row["plan_revision_rounds"]),
            implementation_revision_rounds=int(context_row["implementation_revision_rounds"]),
        )
        run.timeline = [
            TimelineEvent(RunState(event["state"]), event["message"])
            for event in self.repository.list_timeline_events(run_id)
        ]
        run.artifacts = [
            ArtifactRef(
                artifact_id=artifact["artifact_id"],
                kind=artifact["kind"],
                path=artifact["path"],
                version=artifact["version"],
                content_type=artifact["content_type"],
            )
            for artifact in self.repository.list_artifacts(run_id)
        ]
        run.findings = {
            row["finding_key"]: Finding(
                key=row["finding_key"],
                title=row["title"],
                detail=row["detail"],
                severity=FindingSeverity(row["severity"]),
                status=FindingStatus(row["status"]),
            )
            for row in self.repository.list_findings(run_id)
        }
        context = {key: context_row[key] for key in context_row.keys()}
        return run, context

    def _latest_artifact(self, run_id: str, kind: str) -> ArtifactRef | None:
        candidates = [
            ArtifactRef(
                artifact_id=row["artifact_id"],
                kind=row["kind"],
                path=row["path"],
                version=row["version"],
                content_type=row["content_type"],
            )
            for row in self.repository.list_artifacts(run_id)
            if row["kind"] == kind
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.version)

    def _next_artifact_version(self, run_id: str, kind: str) -> int:
        versions = [row["version"] for row in self.repository.list_artifacts(run_id) if row["kind"] == kind]
        return max(versions, default=0) + 1

    def _persist_timeline_delta(self, run: WorkflowRun, from_index: int) -> int:
        for event in run.timeline[from_index:]:
            self.repository.add_timeline_event(run.run_id, event.state.value, event.message)
        return len(run.timeline)

    def _persist_findings(self, run_id: str, findings: list[Finding]) -> None:
        for finding in findings:
            self.repository.add_finding(
                run_id,
                finding.key,
                finding.title,
                finding.detail,
                finding.severity.value,
                finding.status.value,
            )

    def _record_command_result(self, run_id: str, result: CommandResult, role: str) -> None:
        self.repository.add_command_result(
            run_id,
            role=role,
            provider=result.provider,
            operation=result.operation,
            success=result.success,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            command=json.dumps(list(result.command), ensure_ascii=False),
            cwd=result.cwd,
            stdout=result.stdout,
            stderr=result.stderr,
            output_text=result.output_text,
            notes=json.dumps(result.notes, ensure_ascii=False),
            created_at=self._timestamp(),
        )

    def _list_execution_steps(self, run_id: str) -> list[dict[str, object]]:
        return [{key: row[key] for key in row.keys()} for row in self.repository.list_execution_steps(run_id)]

    def _next_pending_step(self, steps: list[dict[str, object]], current_step_index: int) -> dict[str, object] | None:
        ordered = sorted(steps, key=lambda item: int(item["step_index"]))
        floor = max(1, current_step_index)
        for step in ordered:
            if int(step["step_index"]) < floor:
                continue
            if step["status"] in {"pending", "blocked"}:
                return step
        for step in ordered:
            if step["status"] in {"pending", "blocked"}:
                return step
        return None

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
            "created_at": self._timestamp(),
        }

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

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
            "Return markdown with sections: Response to Findings, Objective, Scope, Implementation Steps, Risks, Acceptance Criteria, Open Questions."
        )

    def _verifier_prompt(self, plan_path: str, review_path: str) -> str:
        return (
            f"Read the executor plan from: {plan_path}\n"
            f"Read the reviewer output from: {review_path}\n"
            "Assess whether the reviewer is directionally correct and whether the plan should continue revision."
        )

    def _implementation_prompt(
        self,
        task: str,
        plan_path: str,
        step_index: int,
        step_title: str,
        step_detail: str,
        steps: list[dict[str, object]],
    ) -> str:
        completed_steps = [
            f"{step['step_index']}. {step['title']}"
            for step in steps
            if step["status"] in {"completed", "awaiting_approval"}
        ]
        completed_text = "\n".join(completed_steps) if completed_steps else "- none"
        return (
            "Implement exactly one approved plan step.\n"
            f"Project task:\n{task}\n\n"
            f"Read the approved plan from: {plan_path}\n"
            f"Current step: {step_index}. {step_title}\n"
            f"Step detail:\n{step_detail}\n\n"
            "Previously completed steps:\n"
            f"{completed_text}\n\n"
            "Make the necessary workspace changes and return markdown with sections:\n"
            "Step Objective\nWork Completed\nFiles Touched\nValidation\nOpen Risks\nNext Handoff"
        )

    def _implementation_review_prompt(
        self,
        task: str,
        plan_path: str,
        implementation_path: str,
        step_index: int,
        step_title: str,
    ) -> str:
        return (
            "Review the latest implementation step strictly.\n"
            f"Project task:\n{task}\n\n"
            f"Approved plan: {plan_path}\n"
            f"Implementation report: {implementation_path}\n"
            f"Current step: {step_index}. {step_title}\n"
            "Inspect the workspace as needed. Check correctness, drift, missing validation, and whether the step is actually complete."
        )

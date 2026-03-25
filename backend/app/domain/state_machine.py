from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import (
    ArtifactRef,
    Decision,
    Finding,
    FindingSeverity,
    FindingStatus,
    ReviewRecord,
    RunState,
    TimelineEvent,
    WorkflowPolicy,
)


class InvalidTransitionError(ValueError):
    """Raised when a run attempts an invalid state transition."""


@dataclass(slots=True)
class WorkflowRun:
    project_slug: str
    run_id: str
    workflow_name: str = "default_local_workflow"
    policy: WorkflowPolicy = field(default_factory=WorkflowPolicy)
    state: RunState = RunState.DRAFTING_PLAN
    requires_verifier: bool = False
    plan_revision_rounds: int = 0
    implementation_revision_rounds: int = 0
    findings: dict[str, Finding] = field(default_factory=dict)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timeline:
            self.timeline.append(TimelineEvent(self.state, "Run created"))

    def submit_plan(self, artifact: ArtifactRef) -> None:
        self._ensure_state(RunState.DRAFTING_PLAN, RunState.PLAN_REVISION)
        self.artifacts.append(artifact)
        self._transition(RunState.PLAN_REVIEW, f"Executor submitted plan v{artifact.version}")

    def record_plan_review(self, review: ReviewRecord) -> None:
        self._ensure_state(RunState.PLAN_REVIEW)
        self._store_findings(review.findings)
        if review.decision is Decision.APPROVE:
            self._ensure_no_open_blockers()
            self.requires_verifier = self.requires_verifier or self.policy.should_trigger_verifier(
                self.plan_revision_rounds,
                review.risk_tags,
            )
            next_state = (
                RunState.AWAITING_PLAN_APPROVAL if self.policy.human_gate_enabled else RunState.IMPLEMENTING
            )
            self._transition(next_state, "Plan approved by reviewer")
            return
        if review.decision is Decision.REVISE:
            self.plan_revision_rounds += 1
            self.requires_verifier = self.requires_verifier or self.policy.should_trigger_verifier(
                self.plan_revision_rounds,
                review.risk_tags,
            )
            self._transition(RunState.PLAN_REVISION, "Plan requires revision")
            return
        self._transition(RunState.BLOCKED, "Plan rejected by reviewer")

    def submit_plan_revision(self, resolved_finding_keys: Iterable[str], artifact: ArtifactRef) -> None:
        self._ensure_state(RunState.PLAN_REVISION)
        self._mark_findings_addressed(resolved_finding_keys)
        self.artifacts.append(artifact)
        self._transition(RunState.PLAN_REVIEW, f"Executor submitted revised plan v{artifact.version}")

    def approve_plan(self) -> None:
        self._ensure_state(RunState.AWAITING_PLAN_APPROVAL)
        self._transition(RunState.IMPLEMENTING, "Human approved plan")

    def submit_implementation(self, artifact: ArtifactRef) -> None:
        self._ensure_state(RunState.IMPLEMENTING)
        self.artifacts.append(artifact)
        self._transition(
            RunState.IMPLEMENTATION_REVIEW,
            f"Executor submitted implementation report v{artifact.version}",
        )

    def record_implementation_review(self, review: ReviewRecord) -> None:
        self._ensure_state(RunState.IMPLEMENTATION_REVIEW)
        self._store_findings(review.findings)
        if review.decision is Decision.APPROVE:
            self._ensure_no_open_blockers()
            self.requires_verifier = True
            self._transition(RunState.VERIFYING, "Implementation approved by reviewer")
            return
        if review.decision is Decision.REVISE:
            self.implementation_revision_rounds += 1
            self.requires_verifier = self.requires_verifier or self.policy.should_trigger_verifier(
                self.implementation_revision_rounds,
                review.risk_tags,
            )
            self._transition(RunState.IMPLEMENTING, "Implementation requires revision")
            return
        self._transition(RunState.BLOCKED, "Implementation rejected by reviewer")

    def record_verification(self, passed: bool, artifact: ArtifactRef) -> None:
        self._ensure_state(RunState.VERIFYING)
        self.artifacts.append(artifact)
        if passed:
            next_state = (
                RunState.AWAITING_FINAL_APPROVAL if self.policy.final_human_gate_enabled else RunState.COMPLETED
            )
            self._transition(next_state, "Verifier accepted implementation")
            return
        self._transition(RunState.IMPLEMENTING, "Verifier requested rework")

    def finalize(self, approved: bool) -> None:
        self._ensure_state(RunState.AWAITING_FINAL_APPROVAL)
        next_state = RunState.COMPLETED if approved else RunState.IMPLEMENTING
        message = "Human approved final delivery" if approved else "Human requested further changes"
        self._transition(next_state, message)

    def open_blockers(self) -> list[Finding]:
        return [
            finding
            for finding in self.findings.values()
            if finding.severity is FindingSeverity.BLOCKER and finding.status is FindingStatus.OPEN
        ]

    def _ensure_state(self, *allowed_states: RunState) -> None:
        if self.state not in allowed_states:
            expected = ", ".join(state.value for state in allowed_states)
            raise InvalidTransitionError(f"Expected state in {{{expected}}}, got {self.state.value}")

    def _transition(self, new_state: RunState, message: str) -> None:
        self.state = new_state
        self.timeline.append(TimelineEvent(new_state, message))

    def _store_findings(self, findings: Iterable[Finding]) -> None:
        for finding in findings:
            self.findings[finding.key] = finding

    def _ensure_no_open_blockers(self) -> None:
        blockers = self.open_blockers()
        if blockers:
            joined = ", ".join(finding.key for finding in blockers)
            raise InvalidTransitionError(f"Open blockers prevent approval: {joined}")

    def _mark_findings_addressed(self, finding_keys: Iterable[str]) -> None:
        for key in finding_keys:
            finding = self.findings.get(key)
            if finding:
                finding.status = FindingStatus.ADDRESSED

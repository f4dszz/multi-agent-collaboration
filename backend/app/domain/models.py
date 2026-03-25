from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    HUMAN = "human"


class RunState(StrEnum):
    DRAFTING_PLAN = "drafting_plan"
    PLAN_REVIEW = "plan_review"
    PLAN_REVISION = "plan_revision"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    IMPLEMENTING = "implementing"
    IMPLEMENTATION_REVIEW = "implementation_review"
    VERIFYING = "verifying"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class Decision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    CONCERN = "concern"
    SUGGESTION = "suggestion"


class FindingStatus(StrEnum):
    OPEN = "open"
    ADDRESSED = "addressed"
    ACCEPTED_RISK = "accepted_risk"
    CLOSED = "closed"


@dataclass(slots=True)
class Finding:
    key: str
    title: str
    detail: str
    severity: FindingSeverity
    status: FindingStatus = FindingStatus.OPEN
    source_role: Role = Role.REVIEWER


@dataclass(slots=True, frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    path: str
    version: int
    content_type: str


@dataclass(slots=True, frozen=True)
class TimelineEvent:
    state: RunState
    message: str


@dataclass(slots=True)
class WorkflowPolicy:
    human_gate_enabled: bool = True
    verifier_revision_threshold: int = 2
    high_risk_tags: tuple[str, ...] = ("database", "security", "concurrency", "architecture")
    final_human_gate_enabled: bool = True

    def should_trigger_verifier(self, revision_rounds: int, risk_tags: set[str] | None = None) -> bool:
        if revision_rounds >= self.verifier_revision_threshold:
            return True
        if not risk_tags:
            return False
        return bool(set(risk_tags).intersection(self.high_risk_tags))


@dataclass(slots=True)
class ReviewRecord:
    decision: Decision
    findings: list[Finding] = field(default_factory=list)
    risk_tags: set[str] = field(default_factory=set)

from __future__ import annotations

import unittest

from backend.app.domain.models import (
    ArtifactRef,
    Decision,
    Finding,
    FindingSeverity,
    FindingStatus,
    ReviewRecord,
    RunState,
)
from backend.app.domain.state_machine import InvalidTransitionError, WorkflowRun


def artifact(artifact_id: str, kind: str, version: int) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        path=f"artifacts/demo/run-001/{kind}/{kind}_v{version}.md",
        version=version,
        content_type="text/markdown",
    )


class WorkflowRunTests(unittest.TestCase):
    def test_happy_path_reaches_completed(self) -> None:
        run = WorkflowRun(project_slug="demo-project", run_id="run-001")

        run.submit_plan(artifact("plan-1", "plan", 1))
        run.record_plan_review(ReviewRecord(decision=Decision.APPROVE))
        run.approve_plan()
        run.submit_implementation(artifact("impl-1", "implementation", 1))
        run.record_implementation_review(ReviewRecord(decision=Decision.APPROVE))
        run.record_verification(True, artifact("verify-1", "verification", 1))
        run.finalize(True)

        self.assertEqual(RunState.COMPLETED, run.state)

    def test_plan_revision_marks_findings_addressed(self) -> None:
        run = WorkflowRun(project_slug="demo-project", run_id="run-001")
        blocker = Finding(
            key="F-001",
            title="Missing rollback plan",
            detail="A rollback strategy is required before implementation.",
            severity=FindingSeverity.BLOCKER,
        )

        run.submit_plan(artifact("plan-1", "plan", 1))
        run.record_plan_review(ReviewRecord(decision=Decision.REVISE, findings=[blocker]))
        run.submit_plan_revision(["F-001"], artifact("plan-2", "plan", 2))

        self.assertEqual(RunState.PLAN_REVIEW, run.state)
        self.assertEqual(FindingStatus.ADDRESSED, run.findings["F-001"].status)

    def test_high_risk_tags_trigger_verifier(self) -> None:
        run = WorkflowRun(project_slug="demo-project", run_id="run-001")

        run.submit_plan(artifact("plan-1", "plan", 1))
        run.record_plan_review(
            ReviewRecord(
                decision=Decision.REVISE,
                risk_tags={"security"},
            )
        )

        self.assertTrue(run.requires_verifier)
        self.assertEqual(RunState.PLAN_REVISION, run.state)

    def test_invalid_transition_raises(self) -> None:
        run = WorkflowRun(project_slug="demo-project", run_id="run-001")

        with self.assertRaises(InvalidTransitionError):
            run.finalize(True)


if __name__ == "__main__":
    unittest.main()

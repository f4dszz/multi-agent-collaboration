from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from backend.app.services.cli_adapters import CommandResult
from backend.app.services.runtime_service import RuntimeWorkflowService


TEST_ROOT = Path.cwd() / ".tmp-tests" / "runtime-service"


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def execute(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        if "Implement exactly one approved plan step." in prompt:
            output = (
                "## Step Objective\n"
                "Do one approved step.\n\n"
                "## Work Completed\n"
                "- Read-only inspection done.\n\n"
                "## Files Touched\n"
                "- none\n\n"
                "## Validation\n"
                "- Verified output.\n\n"
                "## Open Risks\n"
                "- none\n\n"
                "## Next Handoff\n"
                "- Continue to next step.\n"
            )
        elif "Revise the plan after review." in prompt:
            output = (
                "## Response to Findings\n"
                "- Addressed.\n\n"
                "## Objective\n"
                "Ship the checkpoint workflow.\n\n"
                "## Scope\n"
                "- Keep the implementation small.\n\n"
                "## Implementation Steps\n"
                "1. Prepare the plan.\n"
                "2. Execute the approved step.\n\n"
                "## Risks\n"
                "- none\n\n"
                "## Acceptance Criteria\n"
                "- Plan can be approved.\n\n"
                "## Open Questions\n"
                "- none\n"
            )
        else:
            output = (
                "## Objective\n"
                "Ship the checkpoint workflow.\n\n"
                "## Scope\n"
                "- Keep the implementation small.\n\n"
                "## Implementation Steps\n"
                "1. Prepare the plan.\n"
                "2. Execute the approved step.\n\n"
                "## Risks\n"
                "- none\n\n"
                "## Acceptance Criteria\n"
                "- Plan can be approved.\n\n"
                "## Open Questions\n"
                "- none\n"
            )
        return CommandResult(
            provider=self.name,
            operation="execute",
            command=("fake", self.name),
            cwd=workspace,
            exit_code=0,
            stdout=output,
            stderr="",
            duration_ms=1,
            success=True,
            output_text=output,
            notes=[],
        )

    def review_text(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        output = (
            "Decision: approve\n"
            "Risk-Tags: none\n"
            "Blockers:\n"
            "- none\n"
            "Concerns:\n"
            "- none\n"
            "Suggestions:\n"
            "- none\n"
            "Summary:\n"
            "- Ready.\n"
        )
        return CommandResult(
            provider=self.name,
            operation="text_review",
            command=("fake", self.name),
            cwd=workspace,
            exit_code=0,
            stdout=output,
            stderr="",
            duration_ms=1,
            success=True,
            output_text=output,
            notes=[],
        )

    def review_repo(
        self,
        prompt: str,
        *,
        workspace: str,
        base_branch: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        return CommandResult(
            provider=self.name,
            operation="repo_review",
            command=("fake", self.name),
            cwd=workspace,
            exit_code=0,
            stdout="review ok",
            stderr="",
            duration_ms=1,
            success=True,
            output_text="review ok",
            notes=[],
        )


class RuntimeWorkflowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def test_plan_approval_and_checkpoint_flow(self) -> None:
        service = RuntimeWorkflowService(TEST_ROOT / "runtime")
        service.providers.providers = {
            "codex": FakeProvider("codex"),
            "claude": FakeProvider("claude"),
        }

        created = service.create_run(
            task="Build the workflow",
            workspace=str(TEST_ROOT),
            executor_provider="codex",
            reviewer_provider="claude",
            max_plan_rounds=0,
        )
        self.assertEqual("awaiting_plan_approval", created["state"])
        self.assertEqual(2, len(created["steps"]))

        after_plan = service.decide_plan(
            created["run_id"],
            approved=True,
            comment="Pause after the first step.",
            checkpoint_step_indices=[1],
        )
        self.assertEqual("awaiting_checkpoint_approval", after_plan["state"])

        after_checkpoint = service.decide_checkpoint(
            created["run_id"],
            step_index=1,
            approved=True,
            comment="Continue.",
        )
        self.assertEqual("awaiting_final_approval", after_checkpoint["state"])

        completed = service.finalize_run(created["run_id"], approved=True, comment="Ship it.")
        self.assertEqual("completed", completed["state"])
        self.assertTrue(any(approval["stage"] == "plan_gate" for approval in completed["approvals"]))
        self.assertTrue(any(approval["stage"] == "checkpoint:1" for approval in completed["approvals"]))
        self.assertTrue(any(approval["stage"] == "final_gate" for approval in completed["approvals"]))


if __name__ == "__main__":
    unittest.main()

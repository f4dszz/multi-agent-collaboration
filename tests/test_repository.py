from __future__ import annotations

import shutil
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from backend.app.services.repository import WorkflowRepository


TEST_ROOT = Path.cwd() / ".tmp-tests" / "repository"


class WorkflowRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def test_initialize_creates_core_tables(self) -> None:
        db_path = TEST_ROOT / "workflow.db"
        repository = WorkflowRepository(db_path)
        repository.initialize()

        with closing(sqlite3.connect(db_path)) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()

        table_names = {row[0] for row in rows}
        self.assertTrue(
            {
                "projects",
                "workflow_runs",
                "run_contexts",
                "artifacts",
                "findings",
                "approvals",
                "timeline_events",
                "execution_steps",
                "command_results",
            }.issubset(table_names)
        )

    def test_create_project_and_run(self) -> None:
        db_path = TEST_ROOT / "workflow.db"
        repository = WorkflowRepository(db_path)
        repository.initialize()
        repository.create_project("demo-project", "Demo Project", "A local orchestrator demo")
        repository.create_run("run-001", "demo-project", "default_local_workflow", "drafting_plan")

        row = repository.get_run("run-001")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual("demo-project", row["project_slug"])
        self.assertEqual("default_local_workflow", row["workflow_name"])
        self.assertEqual("drafting_plan", row["state"])

    def test_run_context_steps_and_approvals_round_trip(self) -> None:
        db_path = TEST_ROOT / "workflow.db"
        repository = WorkflowRepository(db_path)
        repository.initialize()
        repository.create_project("demo-project", "Demo Project", "A local orchestrator demo")
        repository.create_run("run-001", "demo-project", "default_local_workflow", "drafting_plan")
        repository.create_run_context(
            "run-001",
            task="Build the workflow",
            workspace="D:/demo",
            executor_provider="codex",
            reviewer_provider="claude",
            verifier_provider="",
            max_plan_rounds=2,
            approval_mode="once",
            created_at="2026-03-26T10:00:00",
        )
        repository.replace_execution_steps(
            "run-001",
            [
                {
                    "step_index": 1,
                    "title": "Prepare plan",
                    "detail": "Create a reviewable plan.",
                    "requires_approval": True,
                    "status": "pending",
                }
            ],
        )
        repository.add_approval("run-001", "plan_gate", True, "Looks good")

        context = repository.get_run_context("run-001")
        steps = repository.list_execution_steps("run-001")
        approvals = repository.list_approvals("run-001")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual("Build the workflow", context["task"])
        self.assertEqual(1, len(steps))
        self.assertEqual("Prepare plan", steps[0]["title"])
        self.assertEqual(1, len(approvals))
        self.assertEqual("plan_gate", approvals[0]["stage"])


if __name__ == "__main__":
    unittest.main()

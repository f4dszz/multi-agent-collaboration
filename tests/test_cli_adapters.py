from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.services.cli_adapters import CLAUDE_CLI_JS, ClaudeCliAdapter, CodexCliAdapter


TEST_ROOT = Path.cwd() / ".tmp-tests" / "cli-adapters"


class CliAdapterCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def test_codex_execute_uses_exec_mode_and_output_file(self) -> None:
        adapter = CodexCliAdapter("codex.cmd")
        captured: dict[str, object] = {}
        workspace = TEST_ROOT / "codex"
        workspace.mkdir(parents=True, exist_ok=True)

        def fake_run_process(command, **kwargs):  # type: ignore[no-untyped-def]
            captured["command"] = command
            Path(kwargs["output_file"]).write_text("done", encoding="utf-8")
            from backend.app.services.cli_adapters import CommandResult

            return CommandResult(
                provider="codex",
                operation="execute",
                command=command,
                cwd=kwargs["cwd"],
                exit_code=0,
                stdout="",
                stderr="",
                duration_ms=1,
                success=True,
                output_text="done",
                notes=[],
            )

        with patch.object(adapter, "_run_process", side_effect=fake_run_process):
            adapter.execute(
                "draft a plan",
                workspace=str(workspace),
                system_prompt="executor contract",
                additional_dirs=[str(TEST_ROOT / "shared")],
            )

        command = list(captured["command"])
        self.assertIn("exec", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--full-auto", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--add-dir", command)
        self.assertIn("-", command)
        output_file = Path(command[command.index("-o") + 1])
        self.assertEqual(TEST_ROOT / "shared" / "cli-temp", output_file.parent)

    def test_claude_execute_uses_system_prompt_file_and_stdin(self) -> None:
        adapter = ClaudeCliAdapter("node cli.js")
        captured: dict[str, object] = {}
        workspace = TEST_ROOT / "claude"
        workspace.mkdir(parents=True, exist_ok=True)

        def fake_run_process(command, **kwargs):  # type: ignore[no-untyped-def]
            captured["command"] = command
            captured["prompt"] = kwargs["prompt"]
            from backend.app.services.cli_adapters import CommandResult

            return CommandResult(
                provider="claude",
                operation="execute",
                command=command,
                cwd=kwargs["cwd"],
                exit_code=0,
                stdout="hello",
                stderr="",
                duration_ms=1,
                success=True,
                output_text="hello",
                notes=[],
            )

        with patch("backend.app.services.cli_adapters.shutil.which", return_value="node"):
            with patch.object(Path, "exists", return_value=True):
                with patch.object(adapter, "_run_process", side_effect=fake_run_process):
                    adapter.execute(
                        "review this",
                        workspace=str(workspace),
                        system_prompt="reviewer contract",
                        additional_dirs=[str(TEST_ROOT / "shared")],
                    )

        command = list(captured["command"])
        self.assertEqual("node", command[0])
        self.assertEqual(str(CLAUDE_CLI_JS), command[1])
        self.assertIn("-p", command)
        self.assertIn("--system-prompt-file", command)
        self.assertIn("--permission-mode", command)
        self.assertEqual("review this", captured["prompt"])
        system_prompt_file = Path(command[command.index("--system-prompt-file") + 1])
        self.assertEqual(TEST_ROOT / "shared" / "cli-temp", system_prompt_file.parent)


if __name__ == "__main__":
    unittest.main()

"""Provider registry and SessionManager dispatch tests."""

from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.providers.base import ProviderResult, ProviderStatus
from app.providers.codex import CodexProvider
from app.providers.registry import ProviderRegistry
from app.session_mgr import SessionManager


class FakeProvider:
    id = "fake"
    label = "Fake"
    description = "Fake provider for tests"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id=self.id,
            label=self.label,
            description=self.description,
            available=True,
        )

    def send(self, session, message, timeout, on_chunk, run_stream, on_cli_session_update):
        self.calls.append({
            "session_id": session.session_id,
            "message": message,
            "timeout": timeout,
        })
        if on_chunk:
            on_chunk("text", "streamed")
        return ProviderResult(
            provider=self.id,
            session_id=session.session_id,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            success=True,
            output_text="ok",
        )


class ProviderRegistryTests(unittest.TestCase):
    def test_registry_lists_statuses(self) -> None:
        registry = ProviderRegistry([FakeProvider()])

        statuses = registry.statuses()

        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].id, "fake")
        self.assertTrue(statuses[0].available)

    def test_registry_rejects_unknown_provider(self) -> None:
        registry = ProviderRegistry([FakeProvider()])

        with self.assertRaisesRegex(ValueError, "Unknown provider: missing"):
            registry.get("missing")


class SessionManagerProviderDispatchTests(unittest.TestCase):
    def test_send_message_uses_registered_provider(self) -> None:
        provider = FakeProvider()
        manager = SessionManager(ProviderRegistry([provider]))
        session = manager.create_session("executor", "fake", "D:/tmp")
        chunks: list[tuple[str, str]] = []

        result = manager.send_message(
            session.session_id,
            "hello",
            timeout=123,
            on_chunk=lambda event_type, content: chunks.append((event_type, content)),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.provider, "fake")
        self.assertEqual(result.output_text, "ok")
        self.assertEqual(provider.calls[0]["message"], "hello")
        self.assertEqual(provider.calls[0]["timeout"], 123)
        self.assertEqual(chunks, [("text", "streamed")])
        self.assertEqual(session.round_count, 1)


class CodexProviderCommandTests(unittest.TestCase):
    def test_adds_room_dir_as_writable_dir_when_different_from_workspace(self) -> None:
        provider = CodexProvider()

        class Session:
            session_id = "sess1"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread1"
            workspace = "D:/workspace"
            room_dir = "D:/runtime/room1"
            round_count = 0

        captured: dict[str, object] = {}

        def fake_run_stream(command, cwd, stdin_text, timeout, session_id, line_parser):
            captured["command"] = command
            return (0, [], "", 1)

        with (
            unittest.mock.patch("shutil.which", return_value="codex"),
            unittest.mock.patch("pathlib.Path.mkdir"),
            unittest.mock.patch("tempfile.NamedTemporaryFile") as mock_tmp,
            unittest.mock.patch("pathlib.Path.exists", return_value=False),
            unittest.mock.patch("pathlib.Path.unlink"),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "D:/workspace/cli-temp/out.txt"
            result = provider.send(Session(), "hello", 10, None, fake_run_stream, None)

        self.assertTrue(result.success)
        command = captured["command"]
        self.assertIn("--add-dir", command)
        idx = command.index("--add-dir")
        self.assertEqual(command[idx + 1], "D:/runtime/room1")

    def test_does_not_add_room_dir_when_same_as_workspace(self) -> None:
        provider = CodexProvider()

        class Session:
            session_id = "sess2"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread2"
            workspace = "D:/workspace"
            room_dir = "D:/workspace"
            round_count = 0

        captured: dict[str, object] = {}

        def fake_run_stream(command, cwd, stdin_text, timeout, session_id, line_parser):
            captured["command"] = command
            return (0, [], "", 1)

        with (
            unittest.mock.patch("shutil.which", return_value="codex"),
            unittest.mock.patch("pathlib.Path.mkdir"),
            unittest.mock.patch("tempfile.NamedTemporaryFile") as mock_tmp,
            unittest.mock.patch("pathlib.Path.exists", return_value=False),
            unittest.mock.patch("pathlib.Path.unlink"),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "D:/workspace/cli-temp/out.txt"
            result = provider.send(Session(), "hello", 10, None, fake_run_stream, None)

        self.assertTrue(result.success)
        self.assertNotIn("--add-dir", captured["command"])


if __name__ == "__main__":
    unittest.main()

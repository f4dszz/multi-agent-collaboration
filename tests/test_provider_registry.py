"""Provider registry and SessionManager dispatch tests."""

from __future__ import annotations

import json
import os
import queue
import socketserver
import shutil
import sys
import threading
import uuid
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.permissions import PermissionResolution
from app.permissions import new_permission_request
from app.providers.base import ProviderEvent, ProviderPermissionRequest, ProviderResult, ProviderStatus
from app.providers.codex import CodexProvider
from app.providers.codex_app_server import CodexAppServerClient, CodexAppServerProvider
from app.providers.registry import ProviderRegistry
from app.session_mgr import SessionManager
from app.store import Store
from app.router import Router


def _sse(events: list[dict]) -> str:
    lines: list[str] = []
    for event in events:
        event_type = event.get("type", "message")
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _response_created(resp_id: str) -> dict:
    return {"type": "response.created", "response": {"id": resp_id}}


def _response_completed(resp_id: str) -> dict:
    return {
        "type": "response.completed",
        "response": {
            "id": resp_id,
            "usage": {
                "input_tokens": 0,
                "input_tokens_details": None,
                "output_tokens": 0,
                "output_tokens_details": None,
                "total_tokens": 0,
            },
        },
    }


def _function_call_event(call_id: str, name: str, arguments_json: str) -> dict:
    return {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments_json,
        },
    }


def _assistant_message_event(msg_id: str, text: str) -> dict:
    return {
        "type": "response.output_item.done",
        "item": {
            "type": "message",
            "role": "assistant",
            "id": msg_id,
            "content": [{"type": "output_text", "text": text}],
        },
    }


class _MockResponsesServer:
    def __init__(self, sequence: list[str]) -> None:
        self.sequence = sequence
        self.request_bodies: list[str] = []
        self._index = 0
        self._lock = threading.Lock()
        self._server = None
        self.url = ""

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                with outer._lock:
                    outer.request_bodies.append(body)
                    payload = outer.sequence[outer._index] if outer._index < len(outer.sequence) else _sse([
                        _response_created("resp-fallback"),
                        _assistant_message_event("msg-fallback", "done"),
                        _response_completed("resp-fallback"),
                    ])
                    outer._index += 1
                if self.path != "/v1/responses":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"not found")
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                self.wfile.write(payload.encode("utf-8"))

            def log_message(self, format: str, *args) -> None:
                return

        class ThreadedTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True

        self._server = ThreadedTcpServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address
        self.url = f"http://{host}:{port}"
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class FakeProvider:
    id = "fake"
    label = "Fake"
    description = "Fake provider for tests"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.resolutions: list[dict] = []

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id=self.id,
            label=self.label,
            description=self.description,
            available=True,
        )

    def send(
        self,
        session,
        message,
        timeout,
        on_chunk,
        on_event,
        run_stream,
        on_cli_session_update,
    ):
        self.calls.append({
            "session_id": session.session_id,
            "message": message,
            "timeout": timeout,
        })
        if on_event:
            on_event(ProviderEvent(type="message_delta", turn_id="fake-turn"))
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
            turn_id="fake-turn",
        )

    def resolve_permission(self, session, request_id, resolution):
        self.resolutions.append({
            "session_id": session.session_id,
            "request_id": request_id,
            "decision": resolution.decision,
            "payload": resolution.payload,
        })
        return {"ok": True}


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

    def test_resolve_permission_uses_registered_provider(self) -> None:
        provider = FakeProvider()
        manager = SessionManager(ProviderRegistry([provider]))
        session = manager.create_session("executor", "fake", "D:/tmp", room_id="room1")
        active = manager.get_active_turn(session.session_id)
        self.assertIsNone(active)

        active = manager._active_turns.setdefault(
            session.session_id,
            __import__("app.turn_runtime", fromlist=["ActiveTurn"]).ActiveTurn(
                turn_id="turn-1",
                room_id="room1",
                session_id=session.session_id,
                provider="fake",
                role="executor",
                resolver=lambda resolution: provider.resolve_permission(session, resolution.request_id, resolution),
            ),
        )
        active.add_permission(
            new_permission_request(
                request_id="perm-1",
                room_id="room1",
                session_id=session.session_id,
                provider="fake",
                turn_id="turn-1",
                kind="tool",
                title="Run command",
                description="",
                payload={},
            )
        )
        result = manager.resolve_permission(session.session_id, "perm-1", "allow", {"x": 1})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(provider.resolutions[0]["request_id"], "perm-1")
        self.assertEqual(provider.resolutions[0]["decision"], "allow")

    def test_permission_event_is_added_to_active_turn_before_callback(self) -> None:
        class PermissionProvider(FakeProvider):
            def send(
                self,
                session,
                message,
                timeout,
                on_chunk,
                on_event,
                run_stream,
                on_cli_session_update,
            ):
                if on_event:
                    on_event(
                        ProviderEvent(
                            type="permission_requested",
                            turn_id="turn-1",
                            permission_request=ProviderPermissionRequest(
                                request_id="perm-live",
                                kind="tool",
                                title="Run command",
                                description="",
                                payload={},
                            ),
                        )
                    )
                return ProviderResult(
                    provider=self.id,
                    session_id=session.session_id,
                    exit_code=0,
                    stdout="ok",
                    stderr="",
                    duration_ms=1,
                    success=True,
                    output_text="ok",
                    turn_id="turn-1",
                )

        provider = PermissionProvider()
        manager = SessionManager(ProviderRegistry([provider]))
        session = manager.create_session("executor", "fake", "D:/tmp", room_id="room1")
        seen: list[list[str]] = []

        manager.send_message(
            session.session_id,
            "hello",
            on_event=lambda event: seen.append(
                manager.get_active_turn(session.session_id).pending_permission_ids()
            ),
        )

        self.assertEqual(seen, [["perm-live"]])


class CodexAppServerProviderTests(unittest.TestCase):
    def test_windows_cmd_launch_uses_cmd_exe_wrapper(self) -> None:
        with unittest.mock.patch("subprocess.Popen") as mock_popen:
            proc = mock_popen.return_value
            proc.stdin = unittest.mock.Mock()
            proc.stdout = iter(())
            proc.stderr = iter(())

            client = CodexAppServerClient(
                "C:/Users/wondertek/AppData/Roaming/npm/codex.cmd",
                {},
                "D:/workspace",
            )
            client.close()

        command = mock_popen.call_args.args[0]
        self.assertEqual(command[:3], ["cmd.exe", "/c", "C:/Users/wondertek/AppData/Roaming/npm/codex.cmd"])

    def test_builds_workspace_write_sandbox_with_room_dir(self) -> None:
        provider = CodexAppServerProvider()

        class Session:
            session_id = "sess-app"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread-app"
            workspace = "D:/workspace"
            room_dir = "D:/runtime/room1"
            round_count = 0

        policy = provider._sandbox_policy(Session())

        self.assertEqual(policy["type"], "workspaceWrite")
        self.assertIn("D:/workspace", policy["writableRoots"])
        self.assertIn("D:/runtime/room1", policy["writableRoots"])

    def test_resolve_permission_maps_command_allow(self) -> None:
        provider = CodexAppServerProvider()

        class Session:
            session_id = "sess-app"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread-app"
            workspace = "D:/workspace"
            room_dir = "D:/runtime/room1"
            round_count = 0

        provider._clients[Session.session_id] = object()
        provider._turns[Session.session_id] = {
            "permission_meta": {
                "permission-item-1": {
                    "method": "item/commandExecution/requestApproval",
                    "response_queue": __import__("queue").Queue(maxsize=1),
                }
            }
        }

        result = provider.resolve_permission(
            Session(),
            "permission-item-1",
            PermissionResolution(request_id="permission-item-1", decision="allow"),
        )

        self.assertEqual(result["decision"], "accept")
        queued = provider._turns[Session.session_id]["permission_meta"]["permission-item-1"]["response_queue"].get_nowait()
        self.assertEqual(queued["decision"], "accept")

    def test_resolve_permission_maps_question_answers(self) -> None:
        provider = CodexAppServerProvider()

        class Session:
            session_id = "sess-app"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread-app"
            workspace = "D:/workspace"
            room_dir = "D:/runtime/room1"
            round_count = 0

        provider._clients[Session.session_id] = object()
        provider._turns[Session.session_id] = {
            "permission_meta": {
                "permission-question-1": {
                    "method": "item/tool/requestUserInput",
                    "response_queue": __import__("queue").Queue(maxsize=1),
                }
            }
        }

        answers = {"confirm_path": {"answers": ["Yes"]}}
        result = provider.resolve_permission(
            Session(),
            "permission-question-1",
            PermissionResolution(
                request_id="permission-question-1",
                decision="answer",
                payload={"answers": answers},
            ),
        )

        self.assertEqual(result["answers"], answers)

    def test_resolve_permission_maps_legacy_question_method(self) -> None:
        provider = CodexAppServerProvider()

        class Session:
            session_id = "sess-app"
            role = "executor"
            provider = "codex"
            cli_session_id = "thread-app"
            workspace = "D:/workspace"
            room_dir = "D:/runtime/room1"
            round_count = 0

        provider._clients[Session.session_id] = object()
        provider._turns[Session.session_id] = {
            "permission_meta": {
                "permission-question-legacy": {
                    "method": "tool/requestUserInput",
                    "response_queue": __import__("queue").Queue(maxsize=1),
                }
            }
        }

        answers = {"confirm_path": {"answers": ["Yes"]}}
        result = provider.resolve_permission(
            Session(),
            "permission-question-legacy",
            PermissionResolution(
                request_id="permission-question-legacy",
                decision="answer",
                payload={"answers": answers},
            ),
        )

        self.assertEqual(result["answers"], answers)

    def test_real_codex_app_server_question_permission_roundtrip_with_mock_responses(self) -> None:
        if not (Path("C:/Users/wondertek/AppData/Roaming/npm/codex.cmd").exists() or shutil.which("codex")):
            self.skipTest("codex executable not installed")

        question_sse = _sse([
            _response_created("resp-1"),
            _function_call_event(
                "call1",
                "request_user_input",
                json.dumps(
                    {
                        "questions": [
                            {
                                "id": "confirm_path",
                                "header": "Confirm",
                                "question": "Proceed with the plan?",
                                "options": [
                                    {
                                        "label": "Yes (Recommended)",
                                        "description": "Continue the current plan.",
                                    },
                                    {
                                        "label": "No",
                                        "description": "Stop and revisit the approach.",
                                    },
                                ],
                            }
                        ]
                    }
                ),
            ),
            _response_completed("resp-1"),
        ])
        final_sse = _sse([
            _response_created("resp-2"),
            _assistant_message_event("msg-1", "done"),
            _response_completed("resp-2"),
        ])
        mock_server = _MockResponsesServer([question_sse, final_sse])
        mock_server.start()

        temp_root = Path(
            f"D:/workSpace/platform/codex_project/backend/runtime/test-codex-app-server-{uuid.uuid4().hex[:8]}"
        )
        cwd_dir = temp_root / "cwd"
        room_dir = temp_root / "room"
        codex_home = temp_root / "codex-home"
        temp_root.mkdir(parents=True, exist_ok=True)
        cwd_dir.mkdir(parents=True, exist_ok=True)
        room_dir.mkdir(parents=True, exist_ok=True)
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "config.toml").write_text(
            "\n".join(
                [
                    'model = "mock-model"',
                    'approval_policy = "untrusted"',
                    'sandbox_mode = "read-only"',
                    "",
                    'model_provider = "mock_provider"',
                    "",
                    "[model_providers.mock_provider]",
                    'name = "Mock provider for test"',
                    f'base_url = "{mock_server.url}/v1"',
                    'wire_api = "responses"',
                    "request_max_retries = 0",
                    "stream_max_retries = 0",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        provider = CodexAppServerProvider()
        session = SessionManager(ProviderRegistry([provider])).create_session(
            "executor",
            "codex",
            str(cwd_dir),
            room_id="room-e2e",
            room_dir=str(room_dir),
        )

        permission_queue: queue.Queue[ProviderEvent] = queue.Queue()
        result_queue: queue.Queue[object] = queue.Queue()

        def run_send() -> None:
            try:
                result = provider.send(
                    session=session,
                    message="ask something",
                    timeout=20,
                    on_chunk=None,
                    on_event=lambda event: permission_queue.put(event),
                    run_stream=lambda *args, **kwargs: (_ for _ in ()).throw(
                        AssertionError("run_stream should not be used by app-server provider")
                    ),
                    on_cli_session_update=None,
                )
                result_queue.put(result)
            except Exception as exc:
                result_queue.put(exc)

        env_updates = {
            "CODEX_PROJECT_CODEX_HOME": str(codex_home),
            "CODEX_PROJECT_MODEL": "mock-model",
            "CODEX_PROJECT_MODE": "auto",
            "CODEX_PROJECT_COLLAB_MODE": "plan",
        }
        old_env = {key: os.environ.get(key) for key in env_updates}
        for key, value in env_updates.items():
            os.environ[key] = value

        worker = threading.Thread(target=run_send, daemon=True)
        worker.start()
        try:
            permission_event = None
            for _ in range(20):
                try:
                    event = permission_queue.get(timeout=1)
                except queue.Empty:
                    if not worker.is_alive():
                        break
                    continue
                if event.type == "permission_requested":
                    permission_event = event
                    break
            self.assertIsNotNone(permission_event, "expected permission_requested event")
            assert permission_event is not None
            self.assertEqual(permission_event.type, "permission_requested")
            request = permission_event.permission_request
            self.assertIsNotNone(request)
            assert request is not None
            self.assertEqual(request.kind, "question")
            self.assertEqual(request.payload["questions"][0]["id"], "confirm_path")

            response = provider.resolve_permission(
                session,
                request.request_id,
                PermissionResolution(
                    request_id=request.request_id,
                    decision="answer",
                    payload={"answers": {"confirm_path": {"answers": ["Yes (Recommended)"]}}},
                ),
            )
            self.assertEqual(response["answers"]["confirm_path"]["answers"], ["Yes (Recommended)"])

            worker.join(timeout=20)
            self.assertFalse(worker.is_alive(), "provider send thread did not finish")
            outcome = result_queue.get(timeout=5)
            if isinstance(outcome, Exception):
                raise outcome
            self.assertTrue(outcome.success)
            self.assertEqual(outcome.output_text.strip(), "done")
            self.assertEqual(len(outcome.permission_requests), 1)
            self.assertTrue(
                any('"type":"function_call_output"' in body and '"call_id":"call1"' in body for body in mock_server.request_bodies)
            )
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            provider.shutdown()
            mock_server.close()
            shutil.rmtree(temp_root, ignore_errors=True)


class RouterPermissionTests(unittest.TestCase):
    def test_room_snapshot_includes_permission_requests(self) -> None:
        runtime_root = Path(
            f"D:/workSpace/platform/codex_project/backend/runtime/test-permissions-{uuid.uuid4().hex[:8]}"
        )
        db_path = runtime_root / "orchestrator.db"
        runtime_root.mkdir(parents=True, exist_ok=True)
        store = Store(db_path)
        store.initialize()
        try:
            provider = FakeProvider()
            manager = SessionManager(ProviderRegistry([provider]))
            router = Router(store, manager, runtime_root)
            room_id = f"room-perm-{uuid.uuid4().hex[:8]}"
            snapshot = router.create_room(
                room_id,
                "D:/workSpace/platform/codex_project",
                "task",
                executor_provider="fake",
                reviewer_provider="fake",
            )
            session_id = snapshot["sessions"][0]["session_id"]
            store.add_permission_request(
                new_permission_request(
                    request_id="perm-123",
                    room_id=room_id,
                    session_id=session_id,
                    provider="fake",
                    turn_id="turn-123",
                    kind="tool",
                    title="Run command",
                    description="",
                    payload={},
                )
            )

            refreshed = router._room_snapshot(room_id)

            self.assertEqual(len(refreshed["permission_requests"]), 1)
            self.assertEqual(refreshed["permission_requests"][0]["request_id"], "perm-123")
        finally:
            store.close()

    def test_router_resolve_permission_updates_store_and_runtime(self) -> None:
        runtime_root = Path(
            f"D:/workSpace/platform/codex_project/backend/runtime/test-router-permissions-{uuid.uuid4().hex[:8]}"
        )
        db_path = runtime_root / "orchestrator.db"
        runtime_root.mkdir(parents=True, exist_ok=True)
        store = Store(db_path)
        store.initialize()
        try:
            provider = FakeProvider()
            manager = SessionManager(ProviderRegistry([provider]))
            router = Router(store, manager, runtime_root)
            room_id = f"room-router-perm-{uuid.uuid4().hex[:8]}"
            snapshot = router.create_room(
                room_id,
                "D:/workSpace/platform/codex_project",
                "task",
                executor_provider="fake",
                reviewer_provider="fake",
            )
            session_row = snapshot["sessions"][0]
            session = manager.get_session(session_row["session_id"])
            self.assertIsNotNone(session)
            assert session is not None
            active = manager._active_turns.setdefault(
                session.session_id,
                __import__("app.turn_runtime", fromlist=["ActiveTurn"]).ActiveTurn(
                    turn_id="turn-router",
                    room_id=room_id,
                    session_id=session.session_id,
                    provider="fake",
                    role=session.role,
                    resolver=lambda resolution: provider.resolve_permission(
                        session,
                        resolution.request_id,
                        resolution,
                    ),
                ),
            )
            permission = new_permission_request(
                request_id="perm-router",
                room_id=room_id,
                session_id=session.session_id,
                provider="fake",
                turn_id="turn-router",
                kind="tool",
                title="Run command",
                description="",
                payload={},
            )
            active.add_permission(permission)
            store.add_permission_request(permission)

            refreshed = router.resolve_permission(
                room_id=room_id,
                request_id="perm-router",
                decision="allow",
                payload={"choice": "yes"},
            )

            stored = store.get_permission_request("perm-router")
            self.assertEqual(stored["status"], "approved")
            self.assertEqual(provider.resolutions[0]["request_id"], "perm-router")
            self.assertEqual(provider.resolutions[0]["payload"], {"choice": "yes"})
            self.assertEqual(refreshed["permission_requests"][0]["status"], "approved")
        finally:
            store.close()
            shutil.rmtree(runtime_root, ignore_errors=True)


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
            result = provider.send(Session(), "hello", 10, None, None, fake_run_stream, None)

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
            result = provider.send(Session(), "hello", 10, None, None, fake_run_stream, None)

        self.assertTrue(result.success)
        self.assertNotIn("--add-dir", captured["command"])


if __name__ == "__main__":
    unittest.main()

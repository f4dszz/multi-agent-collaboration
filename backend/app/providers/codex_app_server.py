"""Codex provider backed by the Codex app-server JSON-RPC protocol."""

from __future__ import annotations

import json
import os
import sys
from queue import Queue
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..permissions import PermissionResolution
from .base import (
    CliSessionUpdate,
    OnChunk,
    ProviderEvent,
    ProviderEventHandler,
    ProviderPermissionRequest,
    ProviderResult,
    ProviderSession,
    ProviderStatus,
)


CODEX_HOME_DIRNAME = "codex-home"
CODEX_PROJECT_CODEX_HOME_ENV = "CODEX_PROJECT_CODEX_HOME"
CODEX_PROJECT_MODEL_ENV = "CODEX_PROJECT_MODEL"
CODEX_PROJECT_APPROVAL_POLICY_ENV = "CODEX_PROJECT_APPROVAL_POLICY"
CODEX_PROJECT_SANDBOX_ENV = "CODEX_PROJECT_SANDBOX"
CODEX_PROJECT_MODE_ENV = "CODEX_PROJECT_MODE"
CODEX_PROJECT_COLLAB_MODE_ENV = "CODEX_PROJECT_COLLAB_MODE"
CODEX_PROJECT_REASONING_EFFORT_ENV = "CODEX_PROJECT_REASONING_EFFORT"

_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "read-only": {
        "approvalPolicy": "on-request",
        "sandbox": "read-only",
        "networkAccess": False,
    },
    "auto": {
        "approvalPolicy": "on-request",
        "sandbox": "workspace-write",
        "networkAccess": False,
    },
    "full-access": {
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
        "networkAccess": True,
    },
}


@dataclass(slots=True)
class _PendingRpcRequest:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: str | None = None


class CodexAppServerClient:
    """Small JSONL transport for Codex app-server."""

    def __init__(self, executable: str, env: dict[str, str], cwd: str) -> None:
        command = [executable, "app-server"]
        if sys.platform == "win32" and executable.lower().endswith(".cmd"):
            command = ["cmd.exe", "/c", executable, "app-server"]
        self._proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if not self._proc.stdin or not self._proc.stdout or not self._proc.stderr:
            raise RuntimeError("Failed to start Codex app-server stdio transport")
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._stderr = self._proc.stderr
        self._lock = threading.Lock()
        self._pending: dict[int, _PendingRpcRequest] = {}
        self._request_handlers: dict[str, Any] = {}
        self._notification_handler: Any = None
        self._next_id = 1
        self._stderr_lines: list[str] = []
        self._closed = False
        self._reader = threading.Thread(target=self._read_stdout_loop, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr_loop, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-project",
                    "version": "0.1",
                },
                "capabilities": {
                    "experimentalApi": True,
                },
            },
            timeout=10,
        )

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler

    def set_request_handler(self, method: str, handler) -> None:
        self._request_handlers[method] = handler

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: int = 60) -> Any:
        if self._closed:
            raise RuntimeError("Codex app-server client is closed")
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            pending = _PendingRpcRequest()
            self._pending[request_id] = pending
            self._stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._stdin.flush()
        if not pending.event.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise RuntimeError(f"Codex app-server request timed out for {method}")
        if pending.error:
            raise RuntimeError(pending.error)
        return pending.result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._closed:
            return
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        with self._lock:
            self._stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._stdin.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    @property
    def stderr_text(self) -> str:
        return "".join(self._stderr_lines)

    def _read_stderr_loop(self) -> None:
        try:
            for line in self._stderr:
                self._stderr_lines.append(line)
        except Exception:
            pass

    def _read_stdout_loop(self) -> None:
        try:
            for raw_line in self._stdout:
                line = raw_line.strip()
                if not line:
                    continue
                self._handle_line(line)
        finally:
            with self._lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for waiter in pending:
                waiter.error = waiter.error or "Codex app-server transport closed"
                waiter.event.set()

    def _handle_line(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
            request_id = msg.get("id")
            if not isinstance(request_id, int):
                return
            with self._lock:
                pending = self._pending.pop(request_id, None)
            if not pending:
                return
            if msg.get("error"):
                pending.error = msg["error"].get("message", "Unknown error")
            else:
                pending.result = msg.get("result")
            pending.event.set()
            return

        if isinstance(msg, dict) and "method" in msg and "id" in msg:
            method = msg.get("method")
            handler = self._request_handlers.get(method)
            if not handler:
                self._write_response(msg.get("id"), error="Unhandled request")
                return
            try:
                handler(msg.get("params") or {}, msg.get("id"), self._write_response)
            except Exception as exc:
                self._write_response(msg.get("id"), error=str(exc))
            return

        if isinstance(msg, dict) and "method" in msg:
            if self._notification_handler:
                self._notification_handler(msg.get("method"), msg.get("params") or {})

    def _write_response(self, request_id: int, result: Any = None, error: str | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error:
            payload["error"] = {"code": -32000, "message": error}
        else:
            payload["result"] = result if result is not None else {}
        with self._lock:
            self._stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._stdin.flush()


class CodexAppServerProvider:
    """Codex provider using app-server instead of exec JSON stream."""

    id = "codex"
    label = "Codex"
    description = "OpenAI Codex CLI via app-server JSON-RPC"

    def __init__(self) -> None:
        self._clients: dict[str, CodexAppServerClient] = {}
        self._client_lock = threading.Lock()
        self._session_threads: set[str] = set()
        self._turns: dict[str, dict[str, Any]] = {}
        self._turns_lock = threading.Lock()

    def status(self) -> ProviderStatus:
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                description=self.description,
                available=False,
                error="codex executable not found",
            )
        return ProviderStatus(
            id=self.id,
            label=self.label,
            description=self.description,
            available=True,
        )

    def send(
        self,
        session: ProviderSession,
        message: str,
        timeout: int,
        on_chunk: OnChunk | None,
        on_event: ProviderEventHandler | None,
        run_stream,
        on_cli_session_update: CliSessionUpdate | None,
    ) -> ProviderResult:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.error or "Codex CLI not available")

        client = self._get_or_create_client(session)
        turn_id = f"{session.session_id}:round:{session.round_count + 1}"
        state = {
            "turn_id": turn_id,
            "provider_turn_id": None,
            "completed": threading.Event(),
            "failed": False,
            "error": "",
            "chunks": [],
            "permission_requests": [],
            "turn_status": "",
            "permission_meta": {},
        }
        with self._turns_lock:
            self._turns[session.session_id] = state

        def handle_notification(method: str, params: dict[str, Any]) -> None:
            if method == "turn/started":
                turn = params.get("turn", {})
                provider_turn_id = turn.get("id")
                if isinstance(provider_turn_id, str) and provider_turn_id:
                    state["provider_turn_id"] = provider_turn_id
                return

            if method == "item/agentMessage/delta":
                delta = params.get("delta", "")
                if delta:
                    state["chunks"].append(delta)
                    if on_chunk:
                        on_chunk("text", delta)
                    if on_event:
                        on_event(ProviderEvent(type="message_delta", turn_id=turn_id, content=delta))
                return

            if method in ("item/completed", "codex/event/item_completed"):
                item = self._extract_completed_item(method, params)
                message_text = self._extract_agent_message_text(item)
                if message_text:
                    state["chunks"].append(message_text)
                    if on_chunk:
                        on_chunk("text", message_text)
                    if on_event:
                        on_event(ProviderEvent(type="message_delta", turn_id=turn_id, content=message_text))
                return

            if method == "item/reasoning/textDelta":
                delta = params.get("delta", "")
                if delta and on_event:
                    on_event(ProviderEvent(type="reasoning", turn_id=turn_id, content=delta))
                return

            if method == "turn/completed":
                turn = params.get("turn", {})
                real_turn_id = turn.get("id")
                if isinstance(real_turn_id, str) and real_turn_id:
                    state["provider_turn_id"] = real_turn_id
                status_value = turn.get("status", "")
                state["turn_status"] = status_value
                if status_value == "failed":
                    state["failed"] = True
                    error_obj = turn.get("error") or {}
                    state["error"] = error_obj.get("message", "Turn failed")
                state["completed"].set()
                return

        client.set_notification_handler(handle_notification)
        self._register_request_handlers(client, session, turn_id, on_event)

        try:
            self._ensure_thread(session, client, on_cli_session_update)
            client.request("turn/start", self._turn_start_params(session, message, client), timeout=max(timeout, 30))
            completed = state["completed"].wait(timeout)
            if not completed:
                raise RuntimeError("Codex app-server turn timed out")
        finally:
            with self._turns_lock:
                self._turns.pop(session.session_id, None)

        output = "".join(state["chunks"]).strip()
        success = not state["failed"]
        return ProviderResult(
            provider=self.id,
            session_id=session.session_id,
            exit_code=0 if success else 1,
            stdout="".join(state["chunks"]),
            stderr=client.stderr_text,
            duration_ms=0,
            success=success,
            output_text=output or ("[No output]" if success else state["error"] or "[No output]"),
            turn_id=str(state["turn_id"]),
            permission_requests=list(state["permission_requests"]),
        )

    def _turn_start_params(
        self,
        session: ProviderSession,
        message: str,
        client: CodexAppServerClient,
    ) -> dict[str, Any]:
        approval_policy, sandbox_name, network_access = self._mode_config()
        params: dict[str, Any] = {
            "threadId": session.cli_session_id,
            "input": [{"type": "text", "text": message}],
            "approvalPolicy": approval_policy,
            "sandboxPolicy": self._sandbox_policy(session, sandbox_name, network_access),
            "cwd": session.workspace,
        }
        model = os.environ.get(CODEX_PROJECT_MODEL_ENV, "").strip()
        if model:
            params["model"] = model
        collaboration_mode = self._resolve_collaboration_mode(client)
        if collaboration_mode:
            params["collaborationMode"] = collaboration_mode
        return params

    def _extract_completed_item(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if method == "codex/event/item_completed":
            msg = params.get("msg")
            if not isinstance(msg, dict):
                return None
            item = msg.get("item")
            return item if isinstance(item, dict) else None
        item = params.get("item")
        return item if isinstance(item, dict) else None

    def _extract_agent_message_text(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        item_type = str(item.get("type", "")).strip()
        if item_type not in ("agentMessage", "assistant_message", "message"):
            return ""
        text = item.get("text")
        if isinstance(text, str):
            return text
        content = item.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for entry in content:
                if not isinstance(entry, dict):
                    continue
                output_text = entry.get("text")
                if isinstance(output_text, str):
                    parts.append(output_text)
            return "".join(parts)
        return ""

    def resolve_permission(
        self,
        session: ProviderSession,
        request_id: str,
        resolution: PermissionResolution,
    ) -> dict:
        client = self._clients.get(session.session_id)
        if not client:
            raise RuntimeError("Codex app-server client is not active")
        request_meta = self._find_permission_meta(session.session_id, request_id)
        if not request_meta:
            raise ValueError(f"Unknown permission request: {request_id}")
        method = request_meta["method"]
        if method == "item/commandExecution/requestApproval":
            response = {
                "decision": "acceptForSession" if resolution.decision == "allow_session" else (
                    "accept" if resolution.decision == "allow" else "decline"
                )
            }
        elif method == "item/fileChange/requestApproval":
            response = {
                "decision": "acceptForSession" if resolution.decision == "allow_session" else (
                    "accept" if resolution.decision == "allow" else "decline"
                )
            }
        elif method in ("item/tool/requestUserInput", "tool/requestUserInput"):
            answers = resolution.payload.get("answers")
            if not isinstance(answers, dict):
                raise ValueError("Question permission requires answers payload")
            response = {"answers": answers}
        else:
            raise NotImplementedError(f"Unsupported Codex permission method: {method}")
        request_meta["response_queue"].put(response)
        return response

    def interrupt_turn(self, session: ProviderSession) -> bool:
        client = self._clients.get(session.session_id)
        if not client:
            return False
        turn_id = None
        with self._turns_lock:
            turn_state = self._turns.get(session.session_id)
            if turn_state:
                turn_id = turn_state.get("provider_turn_id")
        if not turn_id:
            return False
        try:
            client.request(
                "turn/interrupt",
                {
                    "threadId": session.cli_session_id,
                    "turnId": turn_id,
                },
                timeout=10,
            )
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        with self._client_lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()

    def _get_or_create_client(self, session: ProviderSession) -> CodexAppServerClient:
        with self._client_lock:
            existing = self._clients.get(session.session_id)
            if existing:
                return existing
            executable = shutil.which("codex.cmd") or shutil.which("codex")
            if not executable:
                raise RuntimeError("Codex CLI not available")
            env = self._build_env(session)
            client = CodexAppServerClient(executable, env, session.workspace)
            client.initialize()
            client.notify("initialized", {})
            self._clients[session.session_id] = client
            return client

    def _build_env(self, session: ProviderSession) -> dict[str, str]:
        env = dict(os.environ)
        override_home = env.get(CODEX_PROJECT_CODEX_HOME_ENV, "").strip()
        if override_home:
            codex_home = Path(override_home)
            codex_home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(codex_home)
        return env

    def _ensure_thread(
        self,
        session: ProviderSession,
        client: CodexAppServerClient,
        on_cli_session_update: CliSessionUpdate | None,
    ) -> None:
        approval_policy, sandbox, _network_access = self._mode_config()
        model = os.environ.get(CODEX_PROJECT_MODEL_ENV, "").strip()
        if session.session_id in self._session_threads:
            client.request(
                "thread/resume",
                {
                    "threadId": session.cli_session_id,
                    "persistExtendedHistory": False,
                    "cwd": session.workspace,
                    "approvalPolicy": approval_policy,
                    "sandbox": sandbox,
                },
                timeout=20,
            )
            return
        params: dict[str, Any] = {
            "cwd": session.workspace,
            "approvalPolicy": approval_policy,
            "sandbox": sandbox,
            "persistExtendedHistory": False,
        }
        if model:
            params["model"] = model
        response = client.request(
            "thread/start",
            params,
            timeout=20,
        )
        thread = response.get("thread", {})
        thread_id = thread.get("id", "")
        if not thread_id:
            raise RuntimeError("Codex app-server did not return thread id")
        session.cli_session_id = thread_id
        self._session_threads.add(session.session_id)
        if on_cli_session_update:
            on_cli_session_update(session.session_id, thread_id)

    def _mode_config(self) -> tuple[str, str, bool]:
        mode = os.environ.get(CODEX_PROJECT_MODE_ENV, "").strip() or "auto"
        preset = _MODE_PRESETS.get(mode, _MODE_PRESETS["auto"])
        approval_policy = os.environ.get(CODEX_PROJECT_APPROVAL_POLICY_ENV, preset["approvalPolicy"])
        sandbox_name = os.environ.get(CODEX_PROJECT_SANDBOX_ENV, preset["sandbox"])
        network_access = preset.get("networkAccess", False)
        return approval_policy, sandbox_name, bool(network_access)

    def _resolve_collaboration_mode(self, client: CodexAppServerClient) -> dict[str, Any] | None:
        requested = os.environ.get(CODEX_PROJECT_COLLAB_MODE_ENV, "").strip()
        if not requested:
            return None
        selected: dict[str, Any] | None = None
        try:
            response = client.request("collaborationMode/list", {}, timeout=10)
            data = response.get("data", []) if isinstance(response, dict) else []
            if isinstance(data, list):
                requested_lower = requested.lower()
                for entry in data:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("name", "")).strip().lower()
                    mode = str(entry.get("mode", "")).strip().lower()
                    if requested_lower in (name, mode):
                        selected = entry
                        break
        except Exception:
            selected = None

        mode_value = str((selected or {}).get("mode") or requested).strip()
        if not mode_value:
            return None
        settings: dict[str, Any] = {}
        model = os.environ.get(CODEX_PROJECT_MODEL_ENV, "").strip()
        if model:
            settings["model"] = model
        elif selected and isinstance(selected.get("model"), str) and selected.get("model", "").strip():
            settings["model"] = str(selected["model"]).strip()
        effort = os.environ.get(CODEX_PROJECT_REASONING_EFFORT_ENV, "").strip()
        if effort:
            settings["reasoning_effort"] = effort
        elif selected and isinstance(selected.get("reasoning_effort"), str) and selected.get("reasoning_effort", "").strip():
            settings["reasoning_effort"] = str(selected["reasoning_effort"]).strip()
        return {"mode": mode_value, "settings": settings}

    def _sandbox_policy(
        self,
        session: ProviderSession,
        sandbox_name: str = "workspace-write",
        network_access: bool = False,
    ) -> dict[str, Any]:
        if sandbox_name == "read-only":
            return {
                "type": "readOnly",
                "readOnlyAccess": {"type": "fullAccess"},
                "networkAccess": network_access,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            }
        if sandbox_name == "danger-full-access":
            return {
                "type": "dangerFullAccess",
                "networkAccess": network_access,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            }
        writable_roots = [session.workspace]
        room_dir = session.room_dir.strip()
        if room_dir and str(Path(room_dir).resolve()) != str(Path(session.workspace).resolve()):
            writable_roots.append(room_dir)
        return {
            "type": "workspaceWrite",
            "writableRoots": writable_roots,
            "readOnlyAccess": {"type": "fullAccess"},
            "networkAccess": network_access,
            "excludeTmpdirEnvVar": False,
            "excludeSlashTmp": False,
        }

    def _register_request_handlers(
        self,
        client: CodexAppServerClient,
        session: ProviderSession,
        turn_id: str,
        on_event: ProviderEventHandler | None,
    ) -> None:
        def register_permission(method: str, builder):
            def handler(params: dict[str, Any], rpc_id: int | None = None, client_response=None) -> None:
                request = builder(params)
                response_queue: Queue[dict[str, Any]] = Queue(maxsize=1)
                with self._turns_lock:
                    turn_state = self._turns.get(session.session_id)
                    if turn_state is not None:
                        turn_state["permission_requests"].append(request)
                        turn_state["permission_meta"][request.request_id] = {
                            "method": method,
                            "params": params,
                            "rpc_id": rpc_id,
                            "client_response": client_response,
                            "response_queue": response_queue,
                        }
                if on_event:
                    on_event(ProviderEvent(
                        type="permission_requested",
                        turn_id=turn_id,
                        permission_request=request,
                    ))
                try:
                    response = response_queue.get(timeout=3600)
                except Exception as exc:
                    raise RuntimeError(f"Timed out waiting for permission resolution: {request.request_id}") from exc
                if client_response is None or rpc_id is None:
                    raise RuntimeError("Missing Codex app-server response channel")
                client_response(rpc_id, response)

            client.set_request_handler(method, handler)

        register_permission("item/commandExecution/requestApproval", self._build_command_permission)
        register_permission("item/fileChange/requestApproval", self._build_file_permission)
        register_permission("item/tool/requestUserInput", self._build_question_permission)
        register_permission("tool/requestUserInput", self._build_question_permission)

    def _find_permission_meta(self, session_id: str, request_id: str) -> dict[str, Any] | None:
        with self._turns_lock:
            turn_state = self._turns.get(session_id)
            if not turn_state:
                return None
            return turn_state.get("permission_meta", {}).get(request_id)

    def _build_command_permission(self, params: dict[str, Any]) -> ProviderPermissionRequest:
        item_id = params.get("itemId", "")
        request_id = f"permission-{item_id}"
        command = params.get("command") or ""
        return ProviderPermissionRequest(
            request_id=request_id,
            kind="tool",
            title=f"Run command: {command}" if command else "Run command",
            description=params.get("reason") or "",
            payload={
                "method": "item/commandExecution/requestApproval",
                "thread_id": params.get("threadId"),
                "turn_id": params.get("turnId"),
                "item_id": item_id,
                "approval_id": params.get("approvalId"),
                "command": command,
                "cwd": params.get("cwd"),
                "available_decisions": params.get("availableDecisions") or [],
            },
        )

    def _build_file_permission(self, params: dict[str, Any]) -> ProviderPermissionRequest:
        item_id = params.get("itemId", "")
        request_id = f"permission-{item_id}"
        return ProviderPermissionRequest(
            request_id=request_id,
            kind="tool",
            title="Apply file changes",
            description=params.get("reason") or "",
            payload={
                "method": "item/fileChange/requestApproval",
                "thread_id": params.get("threadId"),
                "turn_id": params.get("turnId"),
                "item_id": item_id,
                "grant_root": params.get("grantRoot"),
            },
        )

    def _build_question_permission(self, params: dict[str, Any]) -> ProviderPermissionRequest:
        item_id = params.get("itemId", "")
        request_id = f"permission-{item_id}"
        return ProviderPermissionRequest(
            request_id=request_id,
            kind="question",
            title="Question",
            description="",
            payload={
                "method": "item/tool/requestUserInput",
                "thread_id": params.get("threadId"),
                "turn_id": params.get("turnId"),
                "item_id": item_id,
                "questions": params.get("questions") or [],
            },
        )

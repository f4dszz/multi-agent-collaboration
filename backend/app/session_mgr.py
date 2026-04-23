"""Session Manager - 管理agent的持久CLI session。

轻量设计：
- 一个通用 _run_stream() 管理所有CLI子进程生命周期
- 各provider只负责：拼命令 + 写一个小的 line_parser 解析自己的JSONL行
- Claude Code: --session-id / --resume, stream-json
- Codex CLI: exec / exec resume, --json
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .permissions import PermissionResolution, new_permission_request
from .providers import ProviderRegistry, default_registry
from .providers.base import LineParser, OnChunk, ProviderEvent, ProviderEventHandler, ProviderResult
from .turn_runtime import ActiveTurn

logger = logging.getLogger("session_mgr")


Provider = str


SessionResult = ProviderResult


@dataclass(slots=True)
class Session:
    """一个agent的持久session。"""
    session_id: str
    role: str
    provider: Provider
    cli_session_id: str
    workspace: str
    room_id: str = ""
    room_dir: str = ""  # runtime/rooms/{room_id} — for mailbox access
    alive: bool = True
    round_count: int = 0


class SessionManager:
    """管理所有agent session的生命周期。"""

    def __init__(self, provider_registry: ProviderRegistry | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._active_turns: dict[str, ActiveTurn] = {}
        self._procs_lock = threading.Lock()
        self._on_cli_session_update: Callable[[str, str], None] | None = None
        self.provider_registry = provider_registry or default_registry

    def set_cli_session_update_callback(self, cb: Callable[[str, str], None]) -> None:
        """设置回调：Codex首轮获取thread_id后通知外部持久化。"""
        self._on_cli_session_update = cb

    # --- Session CRUD ---

    def create_session(
        self,
        role: str,
        provider: Provider,
        workspace: str,
        room_id: str = "",
        room_dir: str = "",
    ) -> Session:
        session_id = str(uuid.uuid4())[:8]
        cli_session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id, role=role, provider=provider,
            cli_session_id=cli_session_id, workspace=workspace, room_id=room_id,
            room_dir=room_dir,
        )
        self._sessions[session_id] = session
        return session

    def restore_session(
        self, session_id: str, role: str, provider: str,
        cli_session_id: str, workspace: str, room_id: str = "", room_dir: str = "",
    ) -> Session:
        if session_id in self._sessions:
            existing = self._sessions[session_id]
            if room_id and not existing.room_id:
                existing.room_id = room_id
            # Update room_dir if not set (handles sessions created before this field existed)
            if room_dir and not existing.room_dir:
                existing.room_dir = room_dir
            return existing
        session = Session(
            session_id=session_id, role=role, provider=provider,
            cli_session_id=cli_session_id, workspace=workspace, room_id=room_id,
            room_dir=room_dir,
            round_count=1,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def get_active_turn(self, session_id: str) -> ActiveTurn | None:
        return self._active_turns.get(session_id)

    def mark_dead(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.alive = False

    # --- Message dispatch ---

    def send_message(
        self, session_id: str, message: str,
        timeout: int = 600,
        on_chunk: OnChunk | None = None,
        on_event: ProviderEventHandler | None = None,
    ) -> SessionResult:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        logger.info("Sending message to %s (%s, round %d, %d chars)",
                     session_id, session.provider, session.round_count + 1, len(message))

        turn_id = f"{session.session_id}:round:{session.round_count + 1}"
        active_turn = ActiveTurn(
            turn_id=turn_id,
            room_id=session.room_id,
            session_id=session.session_id,
            provider=session.provider,
            role=session.role,
        )
        active_turn.resolver = lambda resolution: self.provider_registry.get(session.provider).resolve_permission(
            session,
            resolution.request_id,
            resolution,
        )
        self._active_turns[session.session_id] = active_turn

        def handle_event(event: ProviderEvent) -> None:
            active_turn.add_event(event)
            if event.type == "permission_requested" and event.permission_request:
                request = event.permission_request
                active_turn.add_permission(
                    new_permission_request(
                        request_id=request.request_id,
                        room_id=session.room_id,
                        session_id=session.session_id,
                        provider=session.provider,
                        turn_id=event.turn_id,
                        kind=request.kind,
                        title=request.title,
                        description=request.description,
                        payload=request.payload,
                    )
                )
            if on_event:
                on_event(event)

        provider = self.provider_registry.get(session.provider)
        try:
            result = provider.send(
                session=session,
                message=message,
                timeout=timeout,
                on_chunk=on_chunk,
                on_event=handle_event,
                run_stream=self._run_stream,
                on_cli_session_update=self._on_cli_session_update,
            )
        except Exception as exc:
            active_turn.mark_failed(str(exc))
            self._active_turns.pop(session.session_id, None)
            raise

        if result.success:
            active_turn.mark_completed()
        else:
            active_turn.mark_failed(result.output_text)
        self._active_turns.pop(session.session_id, None)

        session.round_count += 1
        if not result.success:
            logger.warning("Session %s marked dead after failed send", session_id)
            session.alive = False
        else:
            logger.debug("Session %s send completed successfully", session_id)
        return result

    def resolve_permission(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        payload: dict | None = None,
    ) -> dict:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        active_turn = self._active_turns.get(session_id)
        if not active_turn:
            raise ValueError(f"No active turn for session: {session_id}")
        resolution = PermissionResolution(
            request_id=request_id,
            decision=decision,  # type: ignore[arg-type]
            payload=payload or {},
        )
        return active_turn.resolve_permission(resolution)

    # --- Process management ---

    def kill_active(self, session_id: str) -> bool:
        """强制终止指定session的活跃子进程。"""
        with self._procs_lock:
            proc = self._active_procs.get(session_id)
        if not proc:
            session = self._sessions.get(session_id)
            if session:
                provider = self.provider_registry.get(session.provider)
                interrupt = getattr(provider, "interrupt_turn", None)
                if callable(interrupt):
                    return bool(interrupt(session))
            return False
        logger.warning("Killing active process for session %s (pid=%s)", session_id, proc.pid)
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass
        with self._procs_lock:
            self._active_procs.pop(session_id, None)
        return True

    def cleanup_all(self) -> None:
        """终止所有活跃子进程（服务关闭时调用）。"""
        with self._procs_lock:
            procs = list(self._active_procs.items())
        if procs:
            logger.info("Cleaning up %d active processes", len(procs))
        for sid, proc in procs:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        with self._procs_lock:
            self._active_procs.clear()
        for provider in self.provider_registry.list():
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass

    # --- 通用流式进程运行器 ---

    def _run_stream(
        self, command: list[str], cwd: str, stdin_text: str,
        timeout: int, session_id: str, line_parser: LineParser,
    ) -> tuple[int, list[str], str, int]:
        """启动CLI子进程，逐行读stdout并用line_parser解析JSONL。
        返回 (returncode, collected_texts, stderr, duration_ms)。
        """
        logger.debug("Running command: %s (cwd=%s)", " ".join(command[:3]) + "...", cwd)
        started = time.perf_counter()
        collected: list[str] = []
        stderr_buf: list[str] = []

        try:
            proc = subprocess.Popen(
                command, cwd=cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            return (-1, [], str(exc), 0)

        if stdin_text:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except Exception:
                pass

        with self._procs_lock:
            self._active_procs[session_id] = proc

        def _drain_stderr():
            for line in proc.stderr:
                stderr_buf.append(line)
        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()

        try:
            for line in proc.stdout:
                if time.perf_counter() - started > timeout:
                    proc.kill()
                    proc.wait(timeout=10)
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    collected.append(line)
                    continue
                text = line_parser(event)
                if text:
                    collected.append(text)
        except Exception:
            pass

        try:
            remaining = max(5, timeout - (time.perf_counter() - started))
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

        t.join(timeout=5)
        duration_ms = int((time.perf_counter() - started) * 1000)

        with self._procs_lock:
            self._active_procs.pop(session_id, None)

        rc = proc.returncode if proc.returncode is not None else -1
        logger.info("Process finished: rc=%d, %d chunks, %dms", rc, len(collected), duration_ms)
        if rc != 0 and stderr_buf:
            logger.debug("Process stderr: %s", "".join(stderr_buf)[:500])
        return (rc, collected, "".join(stderr_buf), duration_ms)

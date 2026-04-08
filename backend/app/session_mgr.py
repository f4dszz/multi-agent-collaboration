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
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

logger = logging.getLogger("session_mgr")


CLAUDE_CLI_JS = Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli.js"

Provider = Literal["claude", "codex"]
OnChunk = Callable[[str, str], None]       # (event_type, content) -> None
LineParser = Callable[[dict], str | None]  # json_event -> extracted text or None


@dataclass(slots=True)
class SessionResult:
    """一次CLI调用的结果。"""
    provider: str
    session_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    success: bool
    output_text: str


@dataclass(slots=True)
class Session:
    """一个agent的持久session。"""
    session_id: str
    role: str
    provider: Provider
    cli_session_id: str
    workspace: str
    alive: bool = True
    round_count: int = 0


class SessionManager:
    """管理所有agent session的生命周期。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._procs_lock = threading.Lock()
        self._on_cli_session_update: Callable[[str, str], None] | None = None
        self._codex_has_thread: set[str] = set()  # 已获取真实thread_id的session

    def set_cli_session_update_callback(self, cb: Callable[[str, str], None]) -> None:
        """设置回调：Codex首轮获取thread_id后通知外部持久化。"""
        self._on_cli_session_update = cb

    # --- Session CRUD ---

    def create_session(self, role: str, provider: Provider, workspace: str) -> Session:
        session_id = str(uuid.uuid4())[:8]
        cli_session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id, role=role, provider=provider,
            cli_session_id=cli_session_id, workspace=workspace,
        )
        self._sessions[session_id] = session
        return session

    def restore_session(
        self, session_id: str, role: str, provider: str,
        cli_session_id: str, workspace: str,
    ) -> Session:
        if session_id in self._sessions:
            return self._sessions[session_id]
        session = Session(
            session_id=session_id, role=role, provider=provider,
            cli_session_id=cli_session_id, workspace=workspace,
            round_count=1,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def mark_dead(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.alive = False

    # --- Message dispatch ---

    def send_message(
        self, session_id: str, message: str,
        timeout: int = 600, on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        logger.info("Sending message to %s (%s, round %d, %d chars)",
                     session_id, session.provider, session.round_count + 1, len(message))

        if session.provider == "claude":
            result = self._send_claude(session, message, timeout, on_chunk)
        elif session.provider == "codex":
            result = self._send_codex(session, message, timeout, on_chunk)
        else:
            raise ValueError(f"Unknown provider: {session.provider}")

        session.round_count += 1
        if not result.success:
            logger.warning("Session %s marked dead after failed send", session_id)
            session.alive = False
        else:
            logger.debug("Session %s send completed successfully", session_id)
        return result

    # --- Process management ---

    def kill_active(self, session_id: str) -> bool:
        """强制终止指定session的活跃子进程。"""
        with self._procs_lock:
            proc = self._active_procs.get(session_id)
        if not proc:
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

    # --- Claude Code ---

    def _send_claude(
        self, session: Session, message: str,
        timeout: int, on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        node = shutil.which("node")
        if not node or not CLAUDE_CLI_JS.exists():
            raise RuntimeError("Claude Code CLI not available")
        if not Path(session.workspace).is_dir():
            raise RuntimeError(f"Workspace does not exist: {session.workspace}")

        command = [node, str(CLAUDE_CLI_JS), "-p"]
        if session.round_count == 0:
            command.extend(["--session-id", session.cli_session_id])
        else:
            command.extend(["--resume", session.cli_session_id])
        command.extend([
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "acceptEdits",
            "--add-dir", session.workspace,
        ])

        final_result: list[str] = []

        def parser(event: dict) -> str | None:
            etype = event.get("type", "")
            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text and on_chunk:
                            on_chunk("text", text)
                        return text
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        inp = block.get("input", {})
                        summary = f"[Tool: {name}]"
                        if isinstance(inp, dict):
                            if "command" in inp:
                                summary = f"[Running: {inp['command'][:80]}]"
                            elif "file_path" in inp:
                                summary = f"[Reading: {inp['file_path']}]"
                        if on_chunk:
                            on_chunk("tool", summary)
            elif etype == "result":
                final_result.append(event.get("result", ""))
            return None

        rc, collected, stderr, duration_ms = self._run_stream(
            command, session.workspace, message, timeout,
            session.session_id, parser,
        )
        output = final_result[0] if final_result else "\n".join(collected)
        return SessionResult(
            provider="claude", session_id=session.session_id,
            exit_code=rc, stdout="\n".join(collected), stderr=stderr,
            duration_ms=duration_ms, success=(rc == 0),
            output_text=output.strip() or "[No output]",
        )

    # --- Codex CLI ---

    def _send_codex(
        self, session: Session, message: str,
        timeout: int, on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            raise RuntimeError("Codex CLI not available")

        temp_dir = Path(session.workspace) / "cli-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".txt", delete=False, encoding="utf-8", dir=temp_dir,
        ) as f:
            output_file = f.name

        if session.session_id in self._codex_has_thread:
            command = [
                executable, "exec", "resume", session.cli_session_id,
                "--skip-git-repo-check", "--full-auto",
                "--json", "-o", output_file, "-",
            ]
        else:
            command = [
                executable, "exec",
                "--skip-git-repo-check", "--full-auto",
                "--sandbox", "workspace-write",
                "--cd", session.workspace,
                "--json", "-o", output_file, "-",
            ]

        def parser(event: dict) -> str | None:
            etype = event.get("type", "")
            if etype == "thread.started":
                tid = event.get("thread_id", "")
                if tid:
                    session.cli_session_id = tid
                    self._codex_has_thread.add(session.session_id)
                    if self._on_cli_session_update:
                        self._on_cli_session_update(session.session_id, tid)
            elif etype == "item.completed":
                item = event.get("item", {})
                itype = item.get("type", "")
                text = item.get("text", "")
                if itype == "agent_message" and text:
                    if on_chunk:
                        on_chunk("text", text)
                    return text
                elif itype == "reasoning" and text:
                    if on_chunk:
                        on_chunk("tool", f"[Thinking] {text[:200]}")
            return None

        rc, collected, stderr, duration_ms = self._run_stream(
            command, session.workspace, message, timeout,
            session.session_id, parser,
        )

        output = "\n".join(collected)
        if not output and Path(output_file).exists():
            try:
                output = Path(output_file).read_text(encoding="utf-8")
            except Exception:
                pass
        Path(output_file).unlink(missing_ok=True)

        timed_out = rc < 0
        return SessionResult(
            provider="codex", session_id=session.session_id,
            exit_code=rc, stdout="\n".join(collected), stderr=stderr,
            duration_ms=duration_ms, success=(rc == 0),
            output_text=output.strip() or ("[Session timed out]" if timed_out else "[No output]"),
        )

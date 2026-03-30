"""Session Manager - 管理agent的持久CLI session。

核心策略：
- Claude Code: 用 --session-id 创建 + --resume 复用，agent保持完整记忆
- 流式输出: 用 --output-format stream-json --verbose 实时读取思考过程
- Codex: 降级为每次 exec + 极简角色前缀（无原生session持久化）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal


CLAUDE_CLI_JS = Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli.js"

Provider = Literal["claude", "codex"]
OnChunk = Callable[[str, str], None]  # (event_type, content) -> None


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

    def send_message(
        self, session_id: str, message: str,
        timeout: int = 600, on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.provider == "claude":
            result = self._send_claude(session, message, timeout, on_chunk)
        elif session.provider == "codex":
            result = self._send_codex(session, message, timeout)
        else:
            raise ValueError(f"Unknown provider: {session.provider}")

        session.round_count += 1
        if not result.success:
            session.alive = False
        return result

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def mark_dead(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.alive = False

    # --- Claude Code (streaming) ---

    def _send_claude(
        self, session: Session, message: str,
        timeout: int, on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        node = shutil.which("node")
        if not node or not CLAUDE_CLI_JS.exists():
            raise RuntimeError("Claude Code CLI not available")

        workspace = Path(session.workspace)
        if not workspace.is_dir():
            raise RuntimeError(f"Workspace does not exist: {session.workspace}")

        command = [node, str(CLAUDE_CLI_JS), "-p"]

        if session.round_count == 0:
            command.extend(["--session-id", session.cli_session_id])
        else:
            command.extend(["--resume", session.cli_session_id])

        command.extend([
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "acceptEdits",
            "--add-dir", session.workspace,
        ])

        return self._run_stream(
            command=command, cwd=session.workspace,
            stdin_text=message, timeout=timeout,
            provider="claude", session_id=session.session_id,
            on_chunk=on_chunk,
        )

    # --- Codex (non-streaming) ---

    def _send_codex(self, session: Session, message: str, timeout: int) -> SessionResult:
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            raise RuntimeError("Codex CLI not available")

        temp_dir = Path(session.workspace) / "cli-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".txt", delete=False, encoding="utf-8", dir=temp_dir,
        ) as f:
            output_file = f.name

        command = [
            executable, "exec",
            "--skip-git-repo-check", "--ephemeral", "--full-auto",
            "--sandbox", "workspace-write",
            "--cd", session.workspace, "-o", output_file, "-",
        ]

        result = self._run_blocking(
            command=command, cwd=session.workspace,
            stdin_text=message, timeout=timeout,
            provider="codex", session_id=session.session_id,
            output_file=output_file,
        )
        Path(output_file).unlink(missing_ok=True)
        return result

    # --- Streaming process runner (Popen) ---

    def _run_stream(
        self, command: list[str], cwd: str, stdin_text: str,
        timeout: int, provider: str, session_id: str,
        on_chunk: OnChunk | None = None,
    ) -> SessionResult:
        started = time.perf_counter()
        final_result = ""
        collected_text: list[str] = []
        stderr_buf: list[str] = []

        try:
            proc = subprocess.Popen(
                command, cwd=cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            return SessionResult(
                provider=provider, session_id=session_id,
                exit_code=-1, stdout="", stderr=str(exc),
                duration_ms=0, success=False,
                output_text=f"[Failed to start CLI: {exc}]",
            )

        # Send input and close stdin
        if stdin_text:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except Exception:
                pass

        # Read stderr in background thread
        def _drain_stderr():
            for line in proc.stderr:
                stderr_buf.append(line)
        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()

        # Read stdout line by line (NDJSON)
        try:
            for line in proc.stdout:
                # Check timeout
                elapsed = time.perf_counter() - started
                if elapsed > timeout:
                    proc.kill()
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    collected_text.append(line)
                    continue

                etype = event.get("type", "")

                if etype == "assistant":
                    # Extract text content from assistant message
                    msg = event.get("message", {})
                    contents = msg.get("content", [])
                    for block in contents:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                collected_text.append(text)
                                if on_chunk:
                                    on_chunk("text", text)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            # Show tool usage as thinking step
                            summary = f"[Tool: {tool_name}]"
                            if isinstance(tool_input, dict):
                                # Show brief summary of what tool is doing
                                if "command" in tool_input:
                                    summary = f"[Running: {tool_input['command'][:80]}]"
                                elif "file_path" in tool_input:
                                    summary = f"[Reading: {tool_input['file_path']}]"
                                elif "pattern" in tool_input:
                                    summary = f"[Searching: {tool_input['pattern']}]"
                            if on_chunk:
                                on_chunk("tool", summary)

                elif etype == "user":
                    # Tool result — show what happened
                    msg = event.get("message", {})
                    contents = msg.get("content", [])
                    for block in contents:
                        if block.get("type") == "tool_result":
                            content_text = block.get("content", "")
                            is_error = block.get("is_error", False)
                            if content_text and on_chunk:
                                prefix = "[Error] " if is_error else ""
                                # Truncate long tool results
                                display = content_text[:300]
                                if len(content_text) > 300:
                                    display += "..."
                                on_chunk("tool_result", f"{prefix}{display}")

                elif etype == "result":
                    final_result = event.get("result", "")
                    # Show permission denials if any
                    denials = event.get("permission_denials", [])
                    if denials and on_chunk:
                        for d in denials:
                            on_chunk("permission", f"[Permission Denied] {d}")

        except Exception:
            pass

        # Wait for process to finish
        try:
            proc.wait(timeout=max(5, timeout - (time.perf_counter() - started)))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        t.join(timeout=2)
        duration_ms = int((time.perf_counter() - started) * 1000)

        output_text = final_result or "\n".join(collected_text)

        return SessionResult(
            provider=provider, session_id=session_id,
            exit_code=proc.returncode or 0,
            stdout="\n".join(collected_text),
            stderr="".join(stderr_buf),
            duration_ms=duration_ms,
            success=(proc.returncode == 0),
            output_text=output_text.strip(),
        )

    # --- Blocking process runner (for Codex) ---

    def _run_blocking(
        self, command: list[str], cwd: str, stdin_text: str,
        timeout: int, provider: str, session_id: str,
        output_file: str | None = None,
    ) -> SessionResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command, cwd=cwd, input=stdin_text,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return SessionResult(
                provider=provider, session_id=session_id,
                exit_code=-1, stdout="", stderr="TIMEOUT",
                duration_ms=duration_ms, success=False,
                output_text="[Session timed out]",
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        output_text = ""
        if output_file and Path(output_file).exists():
            output_text = Path(output_file).read_text(encoding="utf-8")
        elif completed.stdout:
            output_text = completed.stdout

        return SessionResult(
            provider=provider, session_id=session_id,
            exit_code=completed.returncode,
            stdout=completed.stdout, stderr=completed.stderr,
            duration_ms=duration_ms,
            success=completed.returncode == 0,
            output_text=output_text.strip(),
        )

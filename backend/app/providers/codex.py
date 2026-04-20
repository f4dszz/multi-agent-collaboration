"""Codex CLI provider adapter."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .base import (
    CliSessionUpdate,
    OnChunk,
    ProviderResult,
    ProviderSession,
    ProviderStatus,
    StreamRunner,
)


class CodexProvider:
    id = "codex"
    label = "Codex"
    description = "OpenAI Codex CLI via exec --json"

    def __init__(self) -> None:
        self._sessions_with_thread: set[str] = set()

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
        run_stream: StreamRunner,
        on_cli_session_update: CliSessionUpdate | None,
    ) -> ProviderResult:
        executable = shutil.which("codex.cmd") or shutil.which("codex")
        if not executable:
            raise RuntimeError("Codex CLI not available")

        temp_dir = Path(session.workspace) / "cli-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".txt", delete=False, encoding="utf-8", dir=temp_dir,
        ) as f:
            output_file = f.name

        if session.session_id in self._sessions_with_thread:
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
            if session.room_dir and str(Path(session.room_dir).resolve()) != str(Path(session.workspace).resolve()):
                command.extend(["--add-dir", session.room_dir])

        def parser(event: dict) -> str | None:
            etype = event.get("type", "")
            if etype == "thread.started":
                tid = event.get("thread_id", "")
                if tid:
                    session.cli_session_id = tid
                    self._sessions_with_thread.add(session.session_id)
                    if on_cli_session_update:
                        on_cli_session_update(session.session_id, tid)
            elif etype == "item.completed":
                item = event.get("item", {})
                itype = item.get("type", "")
                text = item.get("text", "")
                if itype == "agent_message" and text:
                    if on_chunk:
                        on_chunk("text", text)
                    return text
                if itype == "reasoning" and text:
                    if on_chunk:
                        on_chunk("tool", f"[Thinking] {text[:200]}")
            return None

        rc, collected, stderr, duration_ms = run_stream(
            command,
            session.workspace,
            message,
            timeout,
            session.session_id,
            parser,
        )

        output = "\n".join(collected)
        output_path = Path(output_file)
        if not output and output_path.exists():
            try:
                output = output_path.read_text(encoding="utf-8")
            except Exception:
                pass
        output_path.unlink(missing_ok=True)

        timed_out = rc < 0
        return ProviderResult(
            provider=self.id,
            session_id=session.session_id,
            exit_code=rc,
            stdout="\n".join(collected),
            stderr=stderr,
            duration_ms=duration_ms,
            success=(rc == 0),
            output_text=output.strip() or ("[Session timed out]" if timed_out else "[No output]"),
        )

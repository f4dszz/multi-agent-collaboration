"""Claude Code provider adapter."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..permissions import PermissionResolution
from .base import (
    CliSessionUpdate,
    OnChunk,
    ProviderEvent,
    ProviderEventHandler,
    ProviderResult,
    ProviderSession,
    ProviderStatus,
    StreamRunner,
)


CLAUDE_CLI_JS = Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli.js"


class ClaudeProvider:
    id = "claude"
    label = "Claude"
    description = "Claude Code CLI via stream-json output"

    def status(self) -> ProviderStatus:
        node = shutil.which("node")
        if not node:
            return ProviderStatus(
                id=self.id,
                label=self.label,
                description=self.description,
                available=False,
                error="node executable not found",
            )
        if not CLAUDE_CLI_JS.exists():
            return ProviderStatus(
                id=self.id,
                label=self.label,
                description=self.description,
                available=False,
                error=f"Claude Code CLI not found at {CLAUDE_CLI_JS}",
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
        run_stream: StreamRunner,
        on_cli_session_update: CliSessionUpdate | None,
    ) -> ProviderResult:
        node = shutil.which("node")
        status = self.status()
        if not status.available:
            raise RuntimeError(status.error or "Claude Code CLI not available")
        if not node:
            raise RuntimeError("node executable not found")
        if not Path(session.workspace).is_dir():
            raise RuntimeError(
                f"Workspace目录不存在或不可访问: {session.workspace}\n"
                "请在前端修改workspace路径，或确认目录存在且有读写权限。"
            )

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
        if session.room_dir and str(Path(session.room_dir).resolve()) != str(Path(session.workspace).resolve()):
            command.extend(["--add-dir", session.room_dir])

        turn_id = f"{session.session_id}:round:{session.round_count + 1}"
        final_result: list[str] = []

        def parser(event: dict) -> str | None:
            etype = event.get("type", "")
            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text and on_chunk:
                            on_chunk("text", text)
                        if text and on_event:
                            on_event(ProviderEvent(
                                type="message_delta",
                                turn_id=turn_id,
                                content=text,
                            ))
                        return text
                    if block.get("type") == "tool_use":
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
                        if on_event:
                            on_event(ProviderEvent(
                                type="tool_event",
                                turn_id=turn_id,
                                content=summary,
                                metadata={"tool_name": name, "input": inp if isinstance(inp, dict) else {}},
                            ))
            elif etype == "result":
                final_result.append(event.get("result", ""))
            return None

        rc, collected, stderr, duration_ms = run_stream(
            command,
            session.workspace,
            message,
            timeout,
            session.session_id,
            parser,
        )
        output = final_result[0] if final_result else "\n".join(collected)
        return ProviderResult(
            provider=self.id,
            session_id=session.session_id,
            exit_code=rc,
            stdout="\n".join(collected),
            stderr=stderr,
            duration_ms=duration_ms,
            success=(rc == 0),
            output_text=output.strip() or "[No output]",
            turn_id=turn_id,
        )

    def resolve_permission(
        self,
        session: ProviderSession,
        request_id: str,
        resolution: PermissionResolution,
    ) -> dict:
        raise NotImplementedError("Claude provider permission resolution is not supported yet")

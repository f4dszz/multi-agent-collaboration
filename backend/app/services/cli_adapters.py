from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Operation = Literal["execute", "text_review", "repo_review", "verify"]
CLAUDE_CLI_JS = Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli.js"


@dataclass(slots=True, frozen=True)
class ProviderStatus:
    name: str
    executable: str
    available: bool
    version: str
    capabilities: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(slots=True)
class CommandResult:
    provider: str
    operation: str
    command: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    success: bool
    output_text: str
    notes: list[str] = field(default_factory=list)


class CliAdapterError(RuntimeError):
    """Raised when an external CLI cannot be executed as expected."""


class BaseCliAdapter:
    name = "base"
    capabilities: tuple[str, ...] = ()
    version_flag = "--version"

    def __init__(self, executable: str) -> None:
        self.executable = executable

    @classmethod
    def resolve_default_executable(cls) -> str:
        raise NotImplementedError

    def detect(self) -> ProviderStatus:
        executable = self.resolve_default_executable()
        if not executable:
            return ProviderStatus(
                name=self.name,
                executable="",
                available=False,
                version="not found",
                capabilities=self.capabilities,
                notes=("CLI executable not found on PATH.",),
            )

        try:
            version_output = self._run_process((executable, self.version_flag), cwd=str(Path.cwd()), prompt=None, timeout=10)
            version = self._parse_version(version_output.stdout, version_output.stderr)
            return ProviderStatus(
                name=self.name,
                executable=executable,
                available=True,
                version=version,
                capabilities=self.capabilities,
                notes=self.detection_notes(),
            )
        except Exception as exc:
            return ProviderStatus(
                name=self.name,
                executable=executable,
                available=False,
                version=f"error: {exc}",
                capabilities=self.capabilities,
                notes=self.detection_notes(),
            )

    def detection_notes(self) -> tuple[str, ...]:
        return ()

    def execute(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        raise NotImplementedError

    def review_text(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        return self.execute(
            prompt,
            workspace=workspace,
            system_prompt=system_prompt,
            additional_dirs=additional_dirs,
            model=model,
            timeout=timeout,
        )

    def review_repo(
        self,
        prompt: str,
        *,
        workspace: str,
        base_branch: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        raise CliAdapterError(f"{self.name} does not implement native repository review")

    def _parse_version(self, stdout: str, stderr: str) -> str:
        for line in (stdout or "").splitlines():
            text = line.strip()
            if text:
                return text
        for line in (stderr or "").splitlines():
            text = line.strip()
            if text:
                return text
        return "unknown"

    def _runtime_temp_dir(self, workspace: str, additional_dirs: list[str] | None = None) -> Path:
        candidate_dirs = [Path(path) for path in additional_dirs or [] if path]
        base_dir = candidate_dirs[0] if candidate_dirs else Path(workspace)
        temp_dir = base_dir / "cli-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _run_process(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        prompt: str | None,
        timeout: int,
        output_file: str | None = None,
        provider: str | None = None,
        operation: str | None = None,
        notes: list[str] | None = None,
    ) -> CommandResult:
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        output_text = ""
        if output_file and Path(output_file).exists():
            output_text = Path(output_file).read_text(encoding="utf-8")
        elif completed.stdout:
            output_text = completed.stdout
        return CommandResult(
            provider=provider or self.name,
            operation=operation or "execute",
            command=command,
            cwd=cwd,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
            success=completed.returncode == 0,
            output_text=output_text.strip(),
            notes=notes or [],
        )


class CodexCliAdapter(BaseCliAdapter):
    name = "codex"
    capabilities = ("non_interactive_exec", "native_repo_review", "jsonl_events", "sandbox_modes")
    version_flag = "-V"

    @classmethod
    def resolve_default_executable(cls) -> str:
        return shutil.which("codex.cmd") or str(Path.home() / "AppData/Roaming/npm/codex.cmd")

    def detection_notes(self) -> tuple[str, ...]:
        return (
            "Using codex.cmd to avoid PowerShell execution-policy issues with codex.ps1.",
            "Codex has a native `review` subcommand for repository diffs.",
        )

    def execute(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        extra_dirs = additional_dirs or []
        temp_dir = self._runtime_temp_dir(workspace, extra_dirs)
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8", dir=temp_dir) as file_handle:
            output_file = file_handle.name

        full_prompt = (
            "You are operating in non-interactive Codex CLI mode.\n"
            "Follow the system contract below exactly.\n\n"
            f"{system_prompt}\n\n"
            "User task:\n"
            f"{prompt}\n"
        )
        command = [
            self.executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--full-auto",
            "--sandbox",
            "workspace-write",
            "--cd",
            workspace,
            "-o",
            output_file,
        ]
        for directory in extra_dirs:
            command.extend(["--add-dir", directory])
        if model:
            command.extend(["--model", model])
        command.append("-")
        result = self._run_process(
            tuple(command),
            cwd=workspace,
            prompt=full_prompt,
            timeout=timeout,
            output_file=output_file,
            provider=self.name,
            operation="execute",
            notes=["Codex system instructions are embedded into the prompt because exec mode has no direct system-prompt flag."],
        )
        Path(output_file).unlink(missing_ok=True)
        return result

    def review_text(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        result = self.execute(
            prompt,
            workspace=workspace,
            system_prompt=system_prompt,
            additional_dirs=additional_dirs,
            model=model,
            timeout=timeout,
        )
        result.operation = "text_review"
        return result

    def review_repo(
        self,
        prompt: str,
        *,
        workspace: str,
        base_branch: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        command = [self.executable, "review"]
        if base_branch:
            command.extend(["--base", base_branch])
        else:
            command.append("--uncommitted")
        command.append(prompt)
        return self._run_process(
            tuple(command),
            cwd=workspace,
            prompt=None,
            timeout=timeout,
            provider=self.name,
            operation="repo_review",
            notes=["Codex native repo review is used for git diff review scenarios."],
        )


class ClaudeCliAdapter(BaseCliAdapter):
    name = "claude"
    capabilities = ("print_mode", "system_prompt", "permission_modes", "json_output", "custom_agents")
    version_flag = "-v"

    @classmethod
    def resolve_default_executable(cls) -> str:
        node = shutil.which("node")
        if not node or not CLAUDE_CLI_JS.exists():
            return ""
        return f"{node} {CLAUDE_CLI_JS}"

    def detection_notes(self) -> tuple[str, ...]:
        return (
            "Claude is invoked via `node <cli.js>` to bypass the fragile Windows .cmd wrapper.",
            "System prompt is passed via `--system-prompt-file`, and the user prompt is streamed via stdin for stable multiline input.",
        )

    def detect(self) -> ProviderStatus:
        node = shutil.which("node")
        if not node or not CLAUDE_CLI_JS.exists():
            return ProviderStatus(
                name=self.name,
                executable="",
                available=False,
                version="not found",
                capabilities=self.capabilities,
                notes=("Node executable or Claude CLI script not found.",),
            )

        command = (node, str(CLAUDE_CLI_JS), self.version_flag)
        try:
            version_output = self._run_process(command, cwd=str(Path.cwd()), prompt=None, timeout=10)
            version = self._parse_version(version_output.stdout, version_output.stderr)
            return ProviderStatus(
                name=self.name,
                executable=f"{node} {CLAUDE_CLI_JS}",
                available=True,
                version=version,
                capabilities=self.capabilities,
                notes=self.detection_notes(),
            )
        except Exception as exc:
            return ProviderStatus(
                name=self.name,
                executable=f"{node} {CLAUDE_CLI_JS}",
                available=False,
                version=f"error: {exc}",
                capabilities=self.capabilities,
                notes=self.detection_notes(),
            )

    def execute(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        node = shutil.which("node")
        if not node or not CLAUDE_CLI_JS.exists():
            raise CliAdapterError("Claude CLI script is unavailable on this machine")

        temp_dir = self._runtime_temp_dir(workspace, additional_dirs)
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8", dir=temp_dir) as file_handle:
            file_handle.write(system_prompt)
            system_prompt_file = file_handle.name

        command = [
            node,
            str(CLAUDE_CLI_JS),
            "-p",
            "--output-format",
            "text",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--bare",
            "--system-prompt-file",
            system_prompt_file,
            "--add-dir",
            workspace,
        ]
        for directory in additional_dirs or []:
            command.extend(["--add-dir", directory])
        if model:
            command.extend(["--model", model])
        result = self._run_process(
            tuple(command),
            cwd=workspace,
            prompt=prompt,
            timeout=timeout,
            provider=self.name,
            operation="execute",
            notes=[
                "Claude uses a native `--print` mode for non-interactive calls.",
                "The system prompt is written to a temp file and the user prompt is sent through stdin because this path is stable for long multiline inputs.",
            ],
        )
        Path(system_prompt_file).unlink(missing_ok=True)
        return result

    def review_text(
        self,
        prompt: str,
        *,
        workspace: str,
        system_prompt: str,
        additional_dirs: list[str] | None = None,
        model: str | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        result = self.execute(
            prompt,
            workspace=workspace,
            system_prompt=system_prompt,
            additional_dirs=additional_dirs,
            model=model,
            timeout=timeout,
        )
        result.operation = "text_review"
        return result


class ProviderRegistry:
    def __init__(self) -> None:
        self.providers = {
            "codex": CodexCliAdapter(CodexCliAdapter.resolve_default_executable()),
            "claude": ClaudeCliAdapter(ClaudeCliAdapter.resolve_default_executable()),
        }

    def statuses(self) -> list[ProviderStatus]:
        return [provider.detect() for provider in self.providers.values()]

    def get(self, provider_name: str) -> BaseCliAdapter:
        normalized = provider_name.strip().lower()
        if normalized not in self.providers:
            raise CliAdapterError(f"Unsupported provider: {provider_name}")
        return self.providers[normalized]

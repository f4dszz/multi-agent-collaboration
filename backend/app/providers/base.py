"""Provider adapter contracts.

Providers own CLI-specific details: availability checks, command construction,
event parsing, and final output extraction. SessionManager owns orchestration
and process execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..permissions import PermissionResolution


ProviderEventHandler = Callable[["ProviderEvent"], None]
OnChunk = Callable[[str, str], None]
LineParser = Callable[[dict], str | None]
StreamRunner = Callable[
    [list[str], str, str, int, str, LineParser],
    tuple[int, list[str], str, int],
]
CliSessionUpdate = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """User-facing provider metadata and local availability."""

    id: str
    label: str
    description: str
    available: bool
    error: str | None = None


@dataclass(slots=True)
class ProviderResult:
    """One provider turn result."""

    provider: str
    session_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    success: bool
    output_text: str
    turn_id: str = ""
    permission_requests: list["ProviderPermissionRequest"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProviderPermissionRequest:
    """Provider-agnostic permission request emitted during a turn."""

    request_id: str
    kind: str
    title: str
    description: str
    payload: dict


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """Structured provider runtime event."""

    type: str
    turn_id: str
    content: str = ""
    metadata: dict | None = None
    permission_request: ProviderPermissionRequest | None = None


class ProviderSession(Protocol):
    """Minimal session shape required by provider adapters."""

    session_id: str
    role: str
    provider: str
    cli_session_id: str
    workspace: str
    room_dir: str
    round_count: int


class ProviderAdapter(Protocol):
    """Contract implemented by every CLI provider."""

    id: str
    label: str
    description: str

    def status(self) -> ProviderStatus:
        """Return local availability details."""

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
        """Send one message to a provider session."""

    def resolve_permission(
        self,
        session: ProviderSession,
        request_id: str,
        resolution: PermissionResolution,
    ) -> dict:
        """Resolve one previously emitted permission request."""

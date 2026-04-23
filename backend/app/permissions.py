"""Permission request domain models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


PermissionStatus = Literal["pending", "approved", "denied", "expired"]
PermissionDecision = Literal["allow", "deny", "allow_session", "cancel", "answer"]


@dataclass(slots=True)
class PermissionRequest:
    """Provider-agnostic permission request persisted per room/session/turn."""

    request_id: str
    room_id: str
    session_id: str
    provider: str
    turn_id: str
    status: PermissionStatus
    kind: str
    title: str
    description: str
    payload: dict[str, Any]
    created_at: str
    resolved_at: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "room_id": self.room_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "turn_id": self.turn_id,
            "status": self.status,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "payload_json": json.dumps(self.payload, ensure_ascii=False),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass(frozen=True, slots=True)
class PermissionResolution:
    """User decision for one pending permission request."""

    request_id: str
    decision: PermissionDecision
    payload: dict[str, Any] = field(default_factory=dict)


def new_permission_request(
    request_id: str,
    room_id: str,
    session_id: str,
    provider: str,
    turn_id: str,
    kind: str,
    title: str,
    description: str,
    payload: dict[str, Any],
) -> PermissionRequest:
    """Create a new pending permission request with current timestamp."""

    return PermissionRequest(
        request_id=request_id,
        room_id=room_id,
        session_id=session_id,
        provider=provider,
        turn_id=turn_id,
        status="pending",
        kind=kind,
        title=title,
        description=description,
        payload=payload,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def permission_from_row(row: dict[str, Any]) -> PermissionRequest:
    """Hydrate a permission request from a DB row dict."""

    payload_raw = row.get("payload_json", "{}")
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except json.JSONDecodeError:
        payload = {"raw": payload_raw}

    return PermissionRequest(
        request_id=row["request_id"],
        room_id=row["room_id"],
        session_id=row["session_id"],
        provider=row["provider"],
        turn_id=row["turn_id"],
        status=row["status"],
        kind=row["kind"],
        title=row["title"],
        description=row["description"],
        payload=payload,
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
    )

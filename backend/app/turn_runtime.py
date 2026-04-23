"""Active turn runtime primitives.

Keep runtime state in memory and durable permission state in SQLite.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Callable

from .permissions import PermissionRequest, PermissionResolution
from .providers.base import ProviderEvent


PermissionResolver = Callable[[PermissionResolution], dict]


@dataclass(slots=True)
class ActiveTurn:
    """In-memory runtime state for one active provider turn."""

    turn_id: str
    room_id: str
    session_id: str
    provider: str
    role: str
    events: list[ProviderEvent] = field(default_factory=list)
    permissions: dict[str, PermissionRequest] = field(default_factory=dict)
    completed: bool = False
    failed: bool = False
    error: str = ""
    resolver: PermissionResolver | None = field(default=None, repr=False)
    _resolution_queue: Queue[PermissionResolution] = field(default_factory=Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_event(self, event: ProviderEvent) -> None:
        with self._lock:
            self.events.append(event)

    def add_permission(self, request: PermissionRequest) -> None:
        with self._lock:
            self.permissions[request.request_id] = request

    def has_pending_permissions(self) -> bool:
        with self._lock:
            return any(req.status == "pending" for req in self.permissions.values())

    def resolve_permission(self, resolution: PermissionResolution) -> dict:
        with self._lock:
            existing = self.permissions.get(resolution.request_id)
            if not existing:
                raise ValueError(f"Unknown permission request: {resolution.request_id}")
            if existing.status != "pending":
                raise ValueError(f"Permission request already resolved: {resolution.request_id}")
        if not self.resolver:
            raise RuntimeError("Active turn cannot resolve permissions")
        result = self.resolver(resolution)
        self._resolution_queue.put(resolution)
        return result

    def wait_for_resolution(self, timeout: float | None = None) -> PermissionResolution | None:
        try:
            return self._resolution_queue.get(timeout=timeout)
        except Empty:
            return None

    def mark_completed(self) -> None:
        with self._lock:
            self.completed = True

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self.failed = True
            self.error = error

    def pending_permission_ids(self) -> list[str]:
        with self._lock:
            return [rid for rid, req in self.permissions.items() if req.status == "pending"]

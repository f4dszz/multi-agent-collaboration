"""office_sync.py — Optional Star-Office-UI status synchronization.

Pushes executor/reviewer state to a running Star-Office-UI instance
via its guest-agent API. Fully optional: if the office is unreachable,
all calls fail silently.

Features:
  - Registers executor/reviewer with distinct avatars
  - Pushes rich state + detail on every phase change
  - Heartbeat thread prevents 5-min offline auto-detection
  - Auto re-join if agent gets removed

Usage:
    sync = OfficeSyncBridge("http://localhost:19000", join_key="ocj_codex_team")
    sync.start()                         # registers both agents
    sync.push("executor", "working", "Implementing login module")
    sync.push("reviewer", "reviewing", "Reviewing code quality")
    sync.stop()                          # unregisters agents
"""

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger("office_sync")

# Map our internal states to Star-Office valid states
# Star-Office valid: idle, writing, researching, executing, syncing, error
STATE_MAP = {
    "idle":       "idle",
    "working":    "writing",       # writing = in the work area
    "alert":      "error",
    "success":    "idle",
    "reviewing":  "researching",
    "typing":     "writing",
    "syncing":    "syncing",
    "executing":  "executing",
    "error":      "error",
}

AGENT_DISPLAY = {
    "executor": "Executor ⚡",
    "reviewer": "Reviewer 📋",
}

# Consistent avatar assignment so agents are visually distinct
AGENT_AVATARS = {
    "executor": "guest_role_1",
    "reviewer": "guest_role_4",
}

# Heartbeat interval — Star-Office marks agents offline after 5 min (300s)
HEARTBEAT_INTERVAL = 120  # seconds


class OfficeSyncBridge:
    """Synchronizes agent states with a Star-Office-UI instance."""

    def __init__(self, office_url: str = "http://localhost:19000",
                 join_key: str = "ocj_codex_team",
                 enabled: bool = True):
        self.office_url = office_url.rstrip("/")
        self.join_key = join_key
        self.enabled = enabled
        self._agent_ids: dict[str, str] = {}   # role → agentId
        self._agent_states: dict[str, str] = {}  # role → last pushed state
        self._agent_details: dict[str, str] = {} # role → last pushed detail
        self._lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def _post(self, path: str, data: dict) -> Optional[dict]:
        """POST JSON to Star-Office. Returns parsed response or None on error."""
        if not self.enabled:
            return None
        url = f"{self.office_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            logger.debug("Office sync %s failed: %s", path, exc)
            return None

    def _join_one(self, role: str) -> bool:
        """Register a single agent. Returns True on success."""
        resp = self._post("/join-agent", {
            "name": AGENT_DISPLAY.get(role, role),
            "joinKey": self.join_key,
            "state": "idle",
            "detail": "待命中...",
            "avatar": AGENT_AVATARS.get(role, "guest_role_1"),
        })
        if resp and resp.get("ok"):
            with self._lock:
                self._agent_ids[role] = resp["agentId"]
                self._agent_states[role] = "idle"
                self._agent_details[role] = "待命中..."
            logger.info("Office sync: %s joined as %s", role, resp["agentId"])
            return True
        logger.warning("Office sync: %s failed to join — %s", role,
                        (resp or {}).get("msg", "no response"))
        return False

    def start(self) -> bool:
        """Register executor and reviewer as guest agents. Returns True if at least one joined."""
        if not self.enabled:
            return False
        joined = any(self._join_one(r) for r in ("executor", "reviewer"))
        if joined:
            self._start_heartbeat()
        return joined

    def push(self, role: str, state: str, detail: str = "") -> None:
        """Push a state update for the given agent role. Non-blocking."""
        with self._lock:
            agent_id = self._agent_ids.get(role)
        if not agent_id:
            return
        office_state = STATE_MAP.get(state, "idle")
        # Cache latest state for heartbeat re-sends
        with self._lock:
            self._agent_states[role] = office_state
            self._agent_details[role] = detail
        threading.Thread(
            target=self._do_push,
            args=(role, agent_id, office_state, detail),
            daemon=True,
        ).start()

    def _do_push(self, role: str, agent_id: str, state: str, detail: str) -> None:
        resp = self._post("/agent-push", {
            "agentId": agent_id,
            "joinKey": self.join_key,
            "state": state,
            "detail": detail or state,
            "name": AGENT_DISPLAY.get(role, role),
        })
        if resp and not resp.get("ok"):
            msg = resp.get("msg", "")
            logger.debug("Office push rejected for %s: %s", role, msg)
            # Agent was removed or unauthorized — try to re-register
            if "未注册" in msg or "未找到" in msg:
                logger.info("Office sync: %s removed, attempting re-join", role)
                with self._lock:
                    self._agent_ids.pop(role, None)
                if self._join_one(role):
                    # Retry the push after re-joining
                    with self._lock:
                        new_id = self._agent_ids.get(role)
                    if new_id:
                        self._post("/agent-push", {
                            "agentId": new_id,
                            "joinKey": self.join_key,
                            "state": state,
                            "detail": detail or state,
                            "name": AGENT_DISPLAY.get(role, role),
                        })

    # ── Heartbeat ──────────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        """Start heartbeat thread to prevent 5-min offline auto-detection."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("Office sync: heartbeat started (every %ds)", HEARTBEAT_INTERVAL)

    def _heartbeat_loop(self) -> None:
        """Re-push current state every HEARTBEAT_INTERVAL seconds."""
        while not self._heartbeat_stop.wait(HEARTBEAT_INTERVAL):
            with self._lock:
                snapshot = {
                    r: (aid, self._agent_states.get(r, "idle"),
                        self._agent_details.get(r, ""))
                    for r, aid in self._agent_ids.items()
                }
            for role, (agent_id, state, detail) in snapshot.items():
                self._do_push(role, agent_id, state, detail)
            logger.debug("Office sync: heartbeat sent for %d agents", len(snapshot))

    # ── Lifecycle ──────────────────────────────────────────────

    def stop(self) -> None:
        """Unregister all agents from the office and stop heartbeat."""
        self._heartbeat_stop.set()
        with self._lock:
            ids = dict(self._agent_ids)
            self._agent_ids.clear()
            self._agent_states.clear()
            self._agent_details.clear()
        for role, agent_id in ids.items():
            self._post("/leave-agent", {"agentId": agent_id})
            logger.info("Office sync: %s left (%s)", role, agent_id)

    @property
    def connected(self) -> bool:
        """True if at least one agent is registered."""
        with self._lock:
            return bool(self._agent_ids)

    def status(self) -> dict:
        """Return current sync status for diagnostics."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "office_url": self.office_url,
                "connected_agents": dict(self._agent_ids),
                "agent_states": dict(self._agent_states),
            }

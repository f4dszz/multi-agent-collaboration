"""office_sync.py — Optional Star-Office-UI status synchronization.

Pushes executor/reviewer state to a running Star-Office-UI instance
via its guest-agent API. Fully optional: if the office is unreachable,
all calls fail silently.

Usage:
    sync = OfficeSyncBridge("http://localhost:19000", join_key="ocj_codex_team")
    sync.start()                         # registers both agents
    sync.push("executor", "executing", "Working on task...")
    sync.push("reviewer", "idle", "Waiting...")
    sync.stop()                          # unregisters agents
"""

import json
import logging
import threading
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger("office_sync")

# Map our internal states to Star-Office valid states
STATE_MAP = {
    "idle":     "idle",
    "working":  "executing",
    "alert":    "error",
    "success":  "idle",
    # Extended mappings for fine-grained control
    "reviewing": "researching",
    "typing":    "writing",
    "syncing":   "syncing",
}

AGENT_DISPLAY = {
    "executor": "Executor ⚡",
    "reviewer": "Reviewer 📋",
}


class OfficeSyncBridge:
    """Synchronizes agent states with a Star-Office-UI instance."""

    def __init__(self, office_url: str = "http://localhost:19000",
                 join_key: str = "ocj_codex_team",
                 enabled: bool = True):
        self.office_url = office_url.rstrip("/")
        self.join_key = join_key
        self.enabled = enabled
        self._agent_ids: dict[str, str] = {}  # role → agentId
        self._lock = threading.Lock()

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
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            logger.debug("Office sync %s failed: %s", path, exc)
            return None

    def start(self) -> bool:
        """Register executor and reviewer as guest agents. Returns True if at least one joined."""
        if not self.enabled:
            return False
        joined = False
        for role in ("executor", "reviewer"):
            resp = self._post("/join-agent", {
                "name": AGENT_DISPLAY.get(role, role),
                "joinKey": self.join_key,
                "state": "idle",
                "detail": "Waiting for task...",
            })
            if resp and resp.get("ok"):
                with self._lock:
                    self._agent_ids[role] = resp["agentId"]
                logger.info("Office sync: %s joined as %s", role, resp["agentId"])
                joined = True
            else:
                logger.warning("Office sync: %s failed to join", role)
        return joined

    def push(self, role: str, state: str, detail: str = "") -> None:
        """Push a state update for the given agent role. Non-blocking."""
        with self._lock:
            agent_id = self._agent_ids.get(role)
        if not agent_id:
            return
        office_state = STATE_MAP.get(state, "idle")
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
            "detail": detail or STATE_MAP.get(state, state),
            "name": AGENT_DISPLAY.get(role, role),
        })
        if resp and not resp.get("ok"):
            logger.debug("Office push rejected for %s: %s", role, resp.get("msg"))
            # Agent was removed — try to re-register
            with self._lock:
                self._agent_ids.pop(role, None)

    def stop(self) -> None:
        """Unregister all agents from the office."""
        with self._lock:
            ids = dict(self._agent_ids)
            self._agent_ids.clear()
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
            }

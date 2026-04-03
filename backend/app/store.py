"""Store - 极简SQLite持久化。

只3张核心表：rooms, sessions, messages。
只做索引和查询，不做语义分析。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """SQLite存储层。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """创建数据库和表。"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        return self._conn

    # --- Rooms ---

    def create_room(
        self,
        room_id: str,
        workspace: str,
        executor_role: str = "执行人",
        reviewer_role: str = "监督人",
        task: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self.conn.execute(
                "INSERT INTO rooms (room_id, workspace, executor_role, reviewer_role, task, state, created_at) VALUES (?, ?, ?, ?, ?, 'onboarding', ?)",
                (room_id, workspace, executor_role, reviewer_role, task, _now()),
            )
            self.conn.commit()
        return self.get_room(room_id)

    def get_room(self, room_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
            return dict(row) if row else None

    def list_rooms(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM rooms ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def update_room_state(self, room_id: str, state: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE rooms SET state = ? WHERE room_id = ?", (state, room_id)
            )
            self.conn.commit()

    def delete_room(self, room_id: str) -> None:
        """删除room及其所有关联数据。"""
        with self._lock:
            self.conn.execute("DELETE FROM messages WHERE room_id = ?", (room_id,))
            self.conn.execute("DELETE FROM sessions WHERE room_id = ?", (room_id,))
            self.conn.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
            self.conn.commit()

    # --- Sessions ---

    def add_session(
        self,
        session_id: str,
        room_id: str,
        role: str,
        provider: str,
        cli_session_id: str,
    ) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions (session_id, room_id, role, provider, cli_session_id, alive, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (session_id, room_id, role, provider, cli_session_id, _now()),
            )
            self.conn.commit()

    def get_sessions_for_room(self, room_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM sessions WHERE room_id = ?", (room_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_session_alive(self, session_id: str, alive: bool) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET alive = ? WHERE session_id = ?",
                (1 if alive else 0, session_id),
            )
            self.conn.commit()

    def update_session_cli_id(self, session_id: str, cli_session_id: str) -> None:
        """更新session的CLI session ID（Codex首轮后回填真实thread_id）。"""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET cli_session_id = ? WHERE session_id = ?",
                (cli_session_id, session_id),
            )
            self.conn.commit()

    # --- Messages ---

    def add_message(
        self,
        room_id: str,
        sender: str,
        content: str,
    ) -> int:
        with self._lock:
            cursor = self.conn.execute(
                "INSERT INTO messages (room_id, sender, content, created_at) VALUES (?, ?, ?, ?)",
                (room_id, sender, content, _now()),
            )
            self.conn.commit()
            return cursor.lastrowid

    def get_messages(self, room_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE room_id = ? ORDER BY message_id ASC LIMIT ?",
                (room_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_message(self, room_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM messages WHERE room_id = ? ORDER BY message_id DESC LIMIT 1",
                (room_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_message(self, message_id: int, content: str) -> None:
        """就地更新消息内容（用于流式输出）。"""
        with self._lock:
            self.conn.execute(
                "UPDATE messages SET content = ? WHERE message_id = ?",
                (content, message_id),
            )
            self.conn.commit()


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL,
    executor_role TEXT NOT NULL DEFAULT '执行人',
    reviewer_role TEXT NOT NULL DEFAULT '监督人',
    task TEXT DEFAULT '',
    state TEXT NOT NULL DEFAULT 'onboarding',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    cli_session_id TEXT NOT NULL,
    alive INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, message_id);
CREATE INDEX IF NOT EXISTS idx_sessions_room ON sessions(room_id);
"""

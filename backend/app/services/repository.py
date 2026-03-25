from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    project_slug TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    state TEXT NOT NULL,
    requires_verifier INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(project_slug) REFERENCES projects(slug)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
);

CREATE TABLE IF NOT EXISTS findings (
    finding_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY(finding_key, run_id),
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    approved INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
);
"""


class WorkflowRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA_SQL)
            connection.commit()

    def create_project(self, slug: str, name: str, description: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO projects (slug, name, description) VALUES (?, ?, ?)",
                (slug, name, description),
            )
            connection.commit()

    def create_run(self, run_id: str, project_slug: str, workflow_name: str, state: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs (run_id, project_slug, workflow_name, state, requires_verifier)
                VALUES (?, ?, ?, ?, 0)
                """,
                (run_id, project_slug, workflow_name, state),
            )
            connection.commit()

    def update_run_state(self, run_id: str, state: str, requires_verifier: bool) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE workflow_runs SET state = ?, requires_verifier = ? WHERE run_id = ?",
                (state, int(requires_verifier), run_id),
            )
            connection.commit()

    def add_artifact(
        self,
        run_id: str,
        artifact_id: str,
        kind: str,
        version: int,
        path: str,
        content_type: str,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifacts (artifact_id, run_id, kind, version, path, content_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, run_id, kind, version, path, content_type),
            )
            connection.commit()

    def add_finding(
        self,
        run_id: str,
        finding_key: str,
        title: str,
        detail: str,
        severity: str,
        status: str,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO findings (finding_key, run_id, title, detail, severity, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (finding_key, run_id, title, detail, severity, status),
            )
            connection.commit()

    def update_finding_status(self, run_id: str, finding_key: str, status: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE findings SET status = ? WHERE run_id = ? AND finding_key = ?",
                (status, run_id, finding_key),
            )
            connection.commit()

    def add_timeline_event(self, run_id: str, state: str, message: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO timeline_events (run_id, state, message) VALUES (?, ?, ?)",
                (run_id, state, message),
            )
            connection.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT run_id, project_slug, workflow_name, state, requires_verifier
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return row

    def list_artifacts(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT artifact_id, kind, version, path, content_type
                FROM artifacts
                WHERE run_id = ?
                ORDER BY kind, version
                """,
                (run_id,),
            ).fetchall()
        return rows

    def list_findings(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT finding_key, title, detail, severity, status
                FROM findings
                WHERE run_id = ?
                ORDER BY finding_key
                """,
                (run_id,),
            ).fetchall()
        return rows

    def list_timeline_events(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, state, message
                FROM timeline_events
                WHERE run_id = ?
                ORDER BY event_id
                """,
                (run_id,),
            ).fetchall()
        return rows

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

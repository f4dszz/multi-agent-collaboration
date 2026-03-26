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

CREATE TABLE IF NOT EXISTS run_contexts (
    run_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    workspace TEXT NOT NULL,
    executor_provider TEXT NOT NULL,
    reviewer_provider TEXT NOT NULL,
    verifier_provider TEXT NOT NULL DEFAULT '',
    max_plan_rounds INTEGER NOT NULL DEFAULT 2,
    plan_revision_rounds INTEGER NOT NULL DEFAULT 0,
    implementation_revision_rounds INTEGER NOT NULL DEFAULT 0,
    current_step_index INTEGER NOT NULL DEFAULT 0,
    approval_mode TEXT NOT NULL DEFAULT 'once',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
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

CREATE TABLE IF NOT EXISTS execution_steps (
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    implementation_artifact_id TEXT NOT NULL DEFAULT '',
    review_artifact_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(run_id, step_index),
    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
);

CREATE TABLE IF NOT EXISTS command_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    success INTEGER NOT NULL,
    exit_code INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    command TEXT NOT NULL,
    cwd TEXT NOT NULL,
    stdout TEXT NOT NULL,
    stderr TEXT NOT NULL,
    output_text TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
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

    def create_run_context(
        self,
        run_id: str,
        *,
        task: str,
        workspace: str,
        executor_provider: str,
        reviewer_provider: str,
        verifier_provider: str,
        max_plan_rounds: int,
        approval_mode: str,
        created_at: str,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO run_contexts (
                    run_id,
                    task,
                    workspace,
                    executor_provider,
                    reviewer_provider,
                    verifier_provider,
                    max_plan_rounds,
                    approval_mode,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task,
                    workspace,
                    executor_provider,
                    reviewer_provider,
                    verifier_provider,
                    max_plan_rounds,
                    approval_mode,
                    created_at,
                    created_at,
                ),
            )
            connection.commit()

    def update_run_state(self, run_id: str, state: str, requires_verifier: bool) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE workflow_runs SET state = ?, requires_verifier = ? WHERE run_id = ?",
                (state, int(requires_verifier), run_id),
            )
            connection.commit()

    def get_run_context(self, run_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    run_id,
                    task,
                    workspace,
                    executor_provider,
                    reviewer_provider,
                    verifier_provider,
                    max_plan_rounds,
                    plan_revision_rounds,
                    implementation_revision_rounds,
                    current_step_index,
                    approval_mode,
                    created_at,
                    updated_at
                FROM run_contexts
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return row

    def update_run_context(
        self,
        run_id: str,
        *,
        plan_revision_rounds: int | None = None,
        implementation_revision_rounds: int | None = None,
        current_step_index: int | None = None,
        approval_mode: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[object] = []
        if plan_revision_rounds is not None:
            assignments.append("plan_revision_rounds = ?")
            values.append(plan_revision_rounds)
        if implementation_revision_rounds is not None:
            assignments.append("implementation_revision_rounds = ?")
            values.append(implementation_revision_rounds)
        if current_step_index is not None:
            assignments.append("current_step_index = ?")
            values.append(current_step_index)
        if approval_mode is not None:
            assignments.append("approval_mode = ?")
            values.append(approval_mode)
        if updated_at is not None:
            assignments.append("updated_at = ?")
            values.append(updated_at)
        if not assignments:
            return
        values.append(run_id)
        with closing(self._connect()) as connection:
            connection.execute(
                f"UPDATE run_contexts SET {', '.join(assignments)} WHERE run_id = ?",
                tuple(values),
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

    def add_approval(self, run_id: str, stage: str, approved: bool, comment: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO approvals (run_id, stage, approved, comment)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, stage, int(approved), comment),
            )
            connection.commit()

    def list_approvals(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT approval_id, stage, approved, comment
                FROM approvals
                WHERE run_id = ?
                ORDER BY approval_id
                """,
                (run_id,),
            ).fetchall()
        return rows

    def replace_execution_steps(self, run_id: str, steps: list[dict[str, object]]) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM execution_steps WHERE run_id = ?", (run_id,))
            for step in steps:
                connection.execute(
                    """
                    INSERT INTO execution_steps (
                        run_id,
                        step_index,
                        title,
                        detail,
                        requires_approval,
                        status,
                        implementation_artifact_id,
                        review_artifact_id,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        int(step["step_index"]),
                        str(step["title"]),
                        str(step["detail"]),
                        int(bool(step.get("requires_approval", False))),
                        str(step.get("status", "pending")),
                        str(step.get("implementation_artifact_id", "")),
                        str(step.get("review_artifact_id", "")),
                        str(step.get("notes", "")),
                    ),
                )
            connection.commit()

    def list_execution_steps(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    step_index,
                    title,
                    detail,
                    requires_approval,
                    status,
                    implementation_artifact_id,
                    review_artifact_id,
                    notes
                FROM execution_steps
                WHERE run_id = ?
                ORDER BY step_index
                """,
                (run_id,),
            ).fetchall()
        return rows

    def update_execution_step(
        self,
        run_id: str,
        step_index: int,
        *,
        requires_approval: bool | None = None,
        status: str | None = None,
        implementation_artifact_id: str | None = None,
        review_artifact_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[object] = []
        if requires_approval is not None:
            assignments.append("requires_approval = ?")
            values.append(int(requires_approval))
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if implementation_artifact_id is not None:
            assignments.append("implementation_artifact_id = ?")
            values.append(implementation_artifact_id)
        if review_artifact_id is not None:
            assignments.append("review_artifact_id = ?")
            values.append(review_artifact_id)
        if notes is not None:
            assignments.append("notes = ?")
            values.append(notes)
        if not assignments:
            return
        values.extend((run_id, step_index))
        with closing(self._connect()) as connection:
            connection.execute(
                f"""
                UPDATE execution_steps
                SET {', '.join(assignments)}
                WHERE run_id = ? AND step_index = ?
                """,
                tuple(values),
            )
            connection.commit()

    def add_command_result(
        self,
        run_id: str,
        *,
        role: str,
        provider: str,
        operation: str,
        success: bool,
        exit_code: int,
        duration_ms: int,
        command: str,
        cwd: str,
        stdout: str,
        stderr: str,
        output_text: str,
        notes: str,
        created_at: str,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO command_results (
                    run_id,
                    role,
                    provider,
                    operation,
                    success,
                    exit_code,
                    duration_ms,
                    command,
                    cwd,
                    stdout,
                    stderr,
                    output_text,
                    notes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    role,
                    provider,
                    operation,
                    int(success),
                    exit_code,
                    duration_ms,
                    command,
                    cwd,
                    stdout,
                    stderr,
                    output_text,
                    notes,
                    created_at,
                ),
            )
            connection.commit()

    def list_command_results(self, run_id: str) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    result_id,
                    role,
                    provider,
                    operation,
                    success,
                    exit_code,
                    duration_ms,
                    command,
                    cwd,
                    stdout,
                    stderr,
                    output_text,
                    notes,
                    created_at
                FROM command_results
                WHERE run_id = ?
                ORDER BY result_id
                """,
                (run_id,),
            ).fetchall()
        return rows

    def list_runs(self) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    workflow_runs.run_id,
                    workflow_runs.project_slug,
                    workflow_runs.workflow_name,
                    workflow_runs.state,
                    workflow_runs.requires_verifier,
                    run_contexts.task,
                    run_contexts.workspace,
                    run_contexts.current_step_index,
                    run_contexts.approval_mode,
                    run_contexts.updated_at
                FROM workflow_runs
                LEFT JOIN run_contexts ON run_contexts.run_id = workflow_runs.run_id
                ORDER BY COALESCE(run_contexts.updated_at, workflow_runs.run_id) DESC
                """
            ).fetchall()
        return rows

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

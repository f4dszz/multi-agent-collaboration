from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.state_machine import WorkflowRun
from backend.app.services.artifacts import ArtifactStore
from backend.app.services.repository import WorkflowRepository


@dataclass(slots=True)
class OrchestratorService:
    repository: WorkflowRepository
    artifacts: ArtifactStore

    def bootstrap_run(self, run: WorkflowRun) -> None:
        self.repository.create_run(
            run_id=run.run_id,
            project_slug=run.project_slug,
            workflow_name=run.workflow_name,
            state=run.state.value,
        )
        for event in run.timeline:
            self.repository.add_timeline_event(run.run_id, event.state.value, event.message)

    def persist_run(self, run: WorkflowRun) -> None:
        self.repository.update_run_state(run.run_id, run.state.value, run.requires_verifier)
        for artifact in run.artifacts:
            existing = [row["artifact_id"] for row in self.repository.list_artifacts(run.run_id)]
            if artifact.artifact_id not in existing:
                self.repository.add_artifact(
                    run_id=run.run_id,
                    artifact_id=artifact.artifact_id,
                    kind=artifact.kind,
                    version=artifact.version,
                    path=artifact.path,
                    content_type=artifact.content_type,
                )
        for event in run.timeline:
            self.repository.add_timeline_event(run.run_id, event.state.value, event.message)

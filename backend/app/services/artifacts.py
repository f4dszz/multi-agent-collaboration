from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.app.domain.models import ArtifactRef


class ArtifactStore:
    """Writes human-readable artifacts to the filesystem while returning stable metadata."""

    DEFAULT_FOLDERS = ("plan", "review", "response", "implementation", "verification", "timeline")

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def prepare_run_workspace(self, project_slug: str, run_id: str) -> Path:
        run_root = self.root / project_slug / run_id
        for folder in self.DEFAULT_FOLDERS:
            (run_root / folder).mkdir(parents=True, exist_ok=True)
        return run_root

    def write_text_artifact(
        self,
        project_slug: str,
        run_id: str,
        kind: str,
        version: int,
        content: str,
        suffix: str = ".md",
    ) -> ArtifactRef:
        run_root = self.prepare_run_workspace(project_slug, run_id)
        directory = run_root / kind
        directory.mkdir(parents=True, exist_ok=True)
        artifact_id = uuid4().hex
        path = directory / f"{kind}_v{version}{suffix}"
        path.write_text(content, encoding="utf-8")
        return ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            path=str(path),
            version=version,
            content_type="text/markdown" if suffix == ".md" else "text/plain",
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True, frozen=True)
class ProjectSummary:
    slug: str
    name: str
    description: str


@dataclass(slots=True, frozen=True)
class RunSummary:
    run_id: str
    project_slug: str
    workflow_name: str
    state: str
    requires_verifier: bool


@dataclass(slots=True, frozen=True)
class ArtifactSummary:
    artifact_id: str
    kind: str
    version: int
    path: str
    content_type: str


@dataclass(slots=True, frozen=True)
class FindingSummary:
    key: str
    title: str
    severity: str
    status: str


@dataclass(slots=True, frozen=True)
class RunDashboard:
    run: RunSummary
    artifacts: Sequence[ArtifactSummary]
    findings: Sequence[FindingSummary]
    open_blockers: int

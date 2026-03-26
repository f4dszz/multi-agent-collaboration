export type RunState =
  | "drafting_plan"
  | "plan_review"
  | "plan_revision"
  | "awaiting_plan_approval"
  | "implementing"
  | "awaiting_checkpoint_approval"
  | "implementation_review"
  | "verifying"
  | "awaiting_final_approval"
  | "completed"
  | "blocked";

export type FindingSeverity = "blocker" | "concern" | "suggestion";
export type FindingStatus = "open" | "addressed" | "accepted_risk" | "closed";

export interface TimelineEvent {
  state: RunState;
  message: string;
}

export interface ArtifactSummary {
  artifactId: string;
  kind: string;
  version: number;
  path: string;
}

export interface FindingSummary {
  key: string;
  title: string;
  severity: FindingSeverity;
  status: FindingStatus;
}

export interface RunDashboardModel {
  runId: string;
  projectSlug: string;
  workflowName: string;
  state: RunState;
  requiresVerifier: boolean;
  timeline: TimelineEvent[];
  artifacts: ArtifactSummary[];
  findings: FindingSummary[];
}

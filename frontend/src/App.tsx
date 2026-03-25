import { RunDetailPage } from "./pages/RunDetailPage";
import type { RunDashboardModel } from "./types";

const mockRun: RunDashboardModel = {
  runId: "run-001",
  projectSlug: "local-agent-workflow-orchestrator",
  workflowName: "default_local_workflow",
  state: "plan_revision",
  requiresVerifier: true,
  timeline: [
    { state: "drafting_plan", message: "Run created" },
    { state: "plan_review", message: "Executor submitted plan v1" },
    { state: "plan_revision", message: "Plan requires revision" },
  ],
  artifacts: [
    {
      artifactId: "plan-v1",
      kind: "plan",
      version: 1,
      path: "artifacts/local-agent-workflow-orchestrator/run-001/plan/plan_v1.md",
    },
    {
      artifactId: "review-v1",
      kind: "review",
      version: 1,
      path: "artifacts/local-agent-workflow-orchestrator/run-001/review/review_v1.md",
    },
  ],
  findings: [
    { key: "F-001", title: "Plan lacks rollback strategy", severity: "blocker", status: "open" },
    { key: "F-002", title: "Need explicit verifier trigger rules", severity: "concern", status: "open" },
  ],
};

export default function App() {
  return <RunDetailPage run={mockRun} />;
}

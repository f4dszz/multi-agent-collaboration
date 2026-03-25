import type { CSSProperties } from "react";

import type { RunDashboardModel } from "../types";

interface RunDetailPageProps {
  run: RunDashboardModel;
}

export function RunDetailPage({ run }: RunDetailPageProps) {
  const blockers = run.findings.filter(
    (finding) => finding.severity === "blocker" && finding.status === "open",
  );

  return (
    <main style={styles.page}>
      <section style={styles.hero}>
        <div>
          <p style={styles.eyebrow}>{run.projectSlug}</p>
          <h1 style={styles.heading}>{run.workflowName}</h1>
          <p style={styles.meta}>Current state: {run.state}</p>
        </div>
        <div style={styles.sideCard}>
          <strong>Human Gate</strong>
          <p style={styles.sideText}>
            用户不再手动转发文档，只在审批关卡和争议节点介入。
          </p>
          <p style={styles.sideText}>
            {run.requiresVerifier ? "Verifier required" : "Verifier not required"}
          </p>
        </div>
      </section>

      <section style={styles.grid}>
        <article style={styles.card}>
          <h2 style={styles.cardTitle}>Timeline</h2>
          <ul style={styles.list}>
            {run.timeline.map((event, index) => (
              <li key={`${event.state}-${index}`} style={styles.listItem}>
                <strong>{event.state}</strong>
                <span>{event.message}</span>
              </li>
            ))}
          </ul>
        </article>

        <article style={styles.card}>
          <h2 style={styles.cardTitle}>Findings</h2>
          <ul style={styles.list}>
            {run.findings.map((finding) => (
              <li key={finding.key} style={styles.listItem}>
                <strong>
                  {finding.key} · {finding.severity}
                </strong>
                <span>
                  {finding.title} ({finding.status})
                </span>
              </li>
            ))}
          </ul>
        </article>

        <article style={styles.card}>
          <h2 style={styles.cardTitle}>Artifacts</h2>
          <ul style={styles.list}>
            {run.artifacts.map((artifact) => (
              <li key={artifact.artifactId} style={styles.listItem}>
                <strong>
                  {artifact.kind} v{artifact.version}
                </strong>
                <span>{artifact.path}</span>
              </li>
            ))}
          </ul>
        </article>

        <article style={styles.card}>
          <h2 style={styles.cardTitle}>Gate Summary</h2>
          <p style={styles.sideText}>Open blockers: {blockers.length}</p>
          <p style={styles.sideText}>Next action owner: Executor</p>
          <p style={styles.sideText}>User action: wait until approval gate or blocker dispute</p>
        </article>
      </section>
    </main>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100vh",
    background: "linear-gradient(180deg, #f2efe5 0%, #fffdf7 100%)",
    color: "#1f2421",
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    padding: "32px",
  },
  hero: {
    display: "flex",
    justifyContent: "space-between",
    gap: "24px",
    alignItems: "flex-start",
    marginBottom: "24px",
  },
  eyebrow: {
    margin: 0,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "#6f6655",
    fontSize: "12px",
  },
  heading: {
    fontSize: "36px",
    margin: "8px 0 8px",
    fontFamily: '"IBM Plex Serif", Georgia, serif',
  },
  meta: {
    margin: 0,
    color: "#51473b",
  },
  sideCard: {
    width: "320px",
    border: "1px solid #d8cfbe",
    background: "#f7f2e7",
    padding: "16px",
  },
  sideText: {
    marginBottom: "8px",
    color: "#4a4437",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: "20px",
  },
  card: {
    border: "1px solid #d8cfbe",
    background: "#fffdf7",
    padding: "20px",
  },
  cardTitle: {
    marginTop: 0,
    marginBottom: "12px",
    fontSize: "20px",
    fontFamily: '"IBM Plex Serif", Georgia, serif',
  },
  list: {
    listStyle: "none",
    margin: 0,
    padding: 0,
  },
  listItem: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    borderTop: "1px solid #ebe3d2",
    padding: "10px 0",
  },
};

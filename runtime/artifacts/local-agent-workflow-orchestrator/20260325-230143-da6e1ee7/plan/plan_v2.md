## Response to Findings
- `Blocking note`: the local shell failed to initialize in this run (`windows sandbox: setup refresh failed`), so I could not inspect the exact contents of the referenced `plan_v1.md` and `review_v1.md`. The revision below is based on the project brief and the review themes it implies.
- The revised plan makes provider abstraction a first-class boundary instead of letting orchestration depend directly on Codex CLI or Claude Code CLI behavior.
- The review step is upgraded from an informal prompt to a required workflow stage with structured findings, severity, and a bounded revise loop.
- Timeline and artifact outputs are defined before implementation so the system is testable and auditable from the first end-to-end run.
- The schedule is split by deliverable and exit criteria, which removes the ambiguity and optimism risk from the original one-pass implementation shape.

## Revised Plan
1. Freeze workflow and data contracts. `0.5 day`
- Define the run state machine as `plan -> review -> revise -> finalize`.
- Define a provider interface with explicit methods for process setup, invocation, streaming, result normalization, and shutdown.
- Define a normalized result schema covering `role`, `content`, `attachments`, `exit_code`, `duration_ms`, and provider metadata.
- Define the artifact layout up front:
```text
runtime/artifacts/<run_id>/
  manifest.json
  timeline.ndjson
  plan/plan_v1.md
  review/review_v1.md
  revision/plan_v2.md
  logs/<stage>.log
  final/summary.md
```
- Exit criterion: interfaces and schemas are committed before adapter or orchestration code starts.

2. Implement provider adapters. `1 day`
- Add `CodexCliProvider` and `ClaudeCodeCliProvider`.
- Normalize config for binary path, model, working directory, env allowlist, timeout, and retry policy.
- Capture stdout/stderr streaming and map provider-specific output into the normalized schema.
- Add startup validation for missing binaries and unsupported flags.
- Exit criterion: both providers can run a smoke prompt and emit normalized artifacts.

3. Build artifact and timeline persistence. `0.5 day`
- Write a run manifest at start and append timeline events as newline-delimited JSON.
- Persist raw provider output separately from normalized markdown artifacts.
- Use atomic writes for final artifacts to avoid partial files on failure.
- Exit criterion: every stage produces a timestamped timeline event and a corresponding artifact.

4. Implement the orchestration engine. `1 day`
- Create a stage runner for `plan`, `review`, `revise`, and `finalize` with explicit inputs and outputs.
- Pass artifact references between stages instead of copying large prompt bodies.
- Fail fast on missing required artifacts and write a final failed status with reason.
- Add resume support from the latest completed stage when artifacts already exist.
- Exit criterion: one end-to-end run produces the full artifact tree without manual intervention.

5. Implement the structured review and revise loop. `0.5 day`
- Require review output to include finding id, severity, impacted section, and requested change.
- Require revision output to answer each finding with `accepted`, `rejected`, or `deferred`, plus rationale.
- Allow at most one additional automatic review pass for blocking findings.
- Exit criterion: blocking review items cannot be dropped silently.

6. Add CLI surface and configuration. `0.5 day`
- Expose provider selection and run options through a single local CLI entrypoint.
- Support deterministic run ids, output directory override, dry-run mode, and verbose logging.
- Keep provider-specific flags inside adapter-level config, not orchestration logic.
- Exit criterion: the same top-level command can launch either provider without code changes.

7. Test and harden. `1 day`
- Add contract tests for the provider interface using mocked CLI output.
- Add golden tests for artifact layout and timeline events.
- Add orchestration tests for provider failure, invalid review format, interrupted runs, and resume behavior.
- Run one real smoke test with Codex CLI and one with Claude Code CLI.
- Exit criterion: green test suite plus two captured sample runs under `runtime/artifacts/`.

8. Document operational behavior. `0.5 day`
- Document prerequisites, binary discovery, expected artifact tree, and failure modes.
- Include a short operator guide for reading `timeline.ndjson` and diagnosing failed stages.
- Exit criterion: a new developer can run the orchestrator and inspect output without reading implementation code.

## Remaining Risks
- Codex CLI and Claude Code CLI may change flags or output format; adapter compatibility and version detection remain a maintenance risk.
- If review output is not constrained tightly enough, the revise stage will be brittle and difficult to validate automatically.
- Real CLI runs will be slower and less deterministic than mocks; smoke tests should stay minimal and separate from the default test suite.
- Resume behavior can damage auditability if artifacts are overwritten instead of versioned; immutability rules need to be enforced.
- Streaming and cancellation semantics will differ across providers; this is the highest-risk cross-provider integration area.
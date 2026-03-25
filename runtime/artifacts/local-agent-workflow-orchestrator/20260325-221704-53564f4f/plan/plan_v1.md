## Objective

Assumption for this first plan: the task is to add a provider-based agent execution layer that supports both `Codex CLI` and `Claude Code CLI`, and makes `review`, `timeline`, and `artifacts` first-class, provider-aware outputs.

Build a first production-ready path that:
- runs the same orchestration flow against either CLI provider,
- normalizes provider-specific behavior into one internal contract,
- persists enough metadata to review runs and inspect outputs later.

## Scope

In scope:
- Provider abstraction for agent execution.
- Initial providers: `Codex CLI`, `Claude Code CLI`.
- Provider selection from config or task input.
- Normalized run model: request, status, logs/events, artifacts, review result.
- Timeline capture for each run step.
- Artifact collection and storage metadata.
- Basic validation, error handling, and integration tests.

Out of scope for first implementation:
- Adding more providers.
- Deep UI redesign.
- Full historical analytics beyond basic persistence/queryability.
- Provider-specific advanced features unless they fit the shared contract.

## Implementation Steps

1. Define the internal execution contract.
- Create a provider interface with methods such as `prepare()`, `start()`, `streamEvents()`, `collectArtifacts()`, `finalize()`.
- Define normalized data models for:
  - `RunRequest`
  - `RunResult`
  - `ReviewRecord`
  - `TimelineEvent`
  - `ArtifactRecord`
- Decide the minimum required common fields: `provider`, `run_id`, `task_id`, `status`, `started_at`, `finished_at`, `exit_code`, `raw_output_ref`.

2. Refactor the current single-provider path behind the interface.
- Isolate existing CLI invocation logic from orchestration logic.
- Move command construction, env setup, process spawning, and output parsing into a provider implementation.
- Keep orchestration code dependent only on the normalized interface.

3. Implement provider adapters.
- `CodexCliProvider`
  - command builder
  - auth/env preflight
  - stdout/stderr capture
  - provider-specific artifact extraction
- `ClaudeCodeCliProvider`
  - same responsibilities, but mapped to the shared interface
- Add a provider registry/factory that resolves provider from config or runtime input.

4. Make review provider-aware.
- Introduce a normalized review schema with provider metadata.
- Persist both:
  - normalized review fields used by the app
  - provider-native review/raw response for debugging
- Ensure downstream review consumers no longer assume one provider.

5. Add timeline capture.
- Emit timeline events for at least:
  - queued
  - provider_selected
  - process_started
  - output_received
  - review_started
  - review_completed
  - artifacts_collected
  - run_completed
  - run_failed
- Store event timestamp, event type, provider, and optional payload.

6. Add artifact handling.
- Define first-pass artifact types: `stdout`, `stderr`, `report`, `patch`, `log`, `review_json`, `provider_raw_output`.
- Standardize artifact naming and directory layout by `run_id` and `provider`.
- Persist artifact metadata separately from files so artifacts are queryable even if storage later changes.

7. Update configuration and runtime inputs.
- Add a provider field to the task/run configuration.
- Define default-provider behavior.
- Validate unsupported provider names early.
- Decide whether provider can be overridden per task, per workflow, or both.

8. Add resilience and operational safeguards.
- Timeouts per provider.
- Explicit non-zero exit handling.
- Partial-result handling when review or artifact collection fails after execution.
- Clear error taxonomy: config error, auth error, process error, parse error, storage error.

9. Add tests.
- Unit tests for provider factory and status mapping.
- Contract tests that both providers produce the same normalized `RunResult` shape.
- Integration tests with mocked CLI outputs.
- Failure-path tests for timeout, malformed output, missing executable, and partial artifacts.

10. Roll out in phases.
- Phase 1: provider abstraction + current provider behind it.
- Phase 2: add second provider.
- Phase 3: provider-aware review/timeline/artifacts.
- Phase 4: test hardening and operational cleanup.

## Risks

- `Codex CLI` and `Claude Code CLI` may expose very different output formats, making normalization lossy or fragile.
- Non-interactive auth/setup may differ by provider and fail in CI or headless environments.
- Existing consumers may implicitly depend on current single-provider fields or status values.
- Artifact volume can grow quickly if raw outputs are always persisted.
- If review semantics differ by provider, a naive shared schema may hide meaningful differences.

## Acceptance Criteria

- A run can be started with either `Codex CLI` or `Claude Code CLI` using the same orchestration entrypoint.
- The orchestration layer depends on a provider interface, not provider-specific command logic.
- Each run produces normalized records for:
  - execution result
  - review
  - timeline events
  - artifacts
- Persisted records include `provider` metadata and a stable `run_id`.
- Failures are surfaced with provider-specific detail but normalized status/error categories.
- Automated tests cover both providers against the shared contract.
- Existing single-provider behavior remains functional after the refactor.

## Open Questions

- What is the exact current baseline: is there already one provider implemented, and if so which one?
- What does “review” mean in this system: a post-run summary, a code review result, or a workflow gate?
- Which artifacts are mandatory versus optional for first release?
- Does timeline data need only persistence, or also query/display support immediately?
- Should provider selection happen at workflow level, task level, or executor level?
- Do we need strict parity between `Codex CLI` and `Claude Code CLI`, or is “best effort with normalized core fields” acceptable?
- What storage backend is used for timeline/artifacts today, if any?
- The source task text is partially garbled; confirm whether the intended requirement is specifically “multi-provider agent support with provider-aware review, timeline, and artifacts.”
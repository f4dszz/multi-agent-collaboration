## Objective

Define a first implementation plan for adding a provider-based agent execution layer that can run both `Codex CLI` and `Claude Code CLI`, route execution by `provider`, and produce consistent `review`, `timeline`, and `artifacts` outputs for the local workflow orchestrator.

This plan assumes the task means: introduce a unified adapter model for multiple agent CLIs, standardize execution metadata, and make downstream review/audit outputs provider-agnostic. I could not inspect the repository because local sandbox reads failed, so this is a task-text-first plan.

## Scope

- Add a provider abstraction for supported agent CLIs.
- Support at least two providers in v1: `codex` and `claude`.
- Normalize execution inputs:
  - task payload
  - runtime options
  - working directory
  - timeout
  - environment
- Normalize execution outputs:
  - final result
  - intermediate events
  - review records
  - timeline entries
  - artifact references
- Persist enough metadata for replay, debugging, and audit.
- Keep the first version focused on local CLI orchestration, not distributed scheduling or UI redesign.

## Implementation Steps

1. Define the execution contract.
   Create a provider-agnostic schema for `ExecutionRequest`, `ExecutionResult`, `ReviewRecord`, `TimelineEvent`, and `ArtifactDescriptor`. This is the critical first step because all provider adapters and downstream consumers depend on it.

2. Define the provider interface.
   Introduce a small adapter interface such as `prepare()`, `run()`, `streamEvents()`, `collectArtifacts()`, and `mapResult()`. The interface should isolate provider-specific CLI flags, output parsing, and exit handling.

3. Implement provider registry and routing.
   Add a registry that resolves `provider -> adapter` and validates unsupported providers early. This should be the single entry point used by the orchestrator.

4. Implement the `Codex CLI` adapter.
   Map orchestrator requests into `Codex CLI` command invocations, capture stdout/stderr, parse structured markers if available, and emit normalized events into the shared timeline model.

5. Implement the `Claude Code CLI` adapter.
   Mirror the `Codex CLI` integration but keep its parsing logic isolated. Do not force a shared parser if the two CLIs emit different shapes; normalize only after provider-specific parsing.

6. Add a timeline event model and recorder.
   Record lifecycle events such as `queued`, `started`, `provider_selected`, `prompt_sent`, `tool_started`, `tool_finished`, `review_started`, `review_finished`, `artifact_emitted`, `completed`, and `failed`. Use stable timestamps and correlation IDs.

7. Add artifact collection and storage conventions.
   Define what counts as an artifact in v1: raw logs, structured result JSON, diff/patch output, generated files, and review summary. Store artifacts with stable names and link them from execution records.

8. Add a normalized review stage.
   Define a provider-independent review payload that captures status, findings, severity, rationale, and references to artifacts. If review is currently provider-specific, wrap it behind the same normalization layer rather than leaking provider formats outward.

9. Implement failure handling and retries.
   Standardize timeout behavior, non-zero exit handling, parse failures, and partial artifact retention. Failed runs should still produce timeline and error artifacts.

10. Add observability and debug surfaces.
    Emit structured logs around provider selection, command invocation, exit codes, parse errors, and artifact writes. Keep raw provider output available for debugging.

11. Add contract tests.
    Create tests around:
    - provider resolution
    - request validation
    - output normalization
    - timeline sequencing
    - artifact generation
    - review mapping
    - failure cases

12. Add provider fixture tests.
    Use captured sample outputs from both CLIs to test parsers without requiring live CLI invocation in every test run.

13. Add one end-to-end orchestrator flow.
    Verify that the same orchestrator task can run through `codex` and `claude` providers and produce the same output envelope shape, even if content differs.

14. Document the integration.
    Add developer docs for supported providers, required local binaries, environment variables, artifact paths, and expected review/timeline semantics.

## Risks

- `Codex CLI` and `Claude Code CLI` may expose materially different output formats, making full normalization harder than expected.
- If current review logic is tightly coupled to one provider, extracting it may require refactoring upstream orchestration code.
- Streaming event support may differ by provider; v1 may need polling or coarse-grained events for one adapter.
- Artifact volume can grow quickly if raw logs and generated outputs are always retained.
- Exit-code success does not guarantee parse success; the system must distinguish transport success from semantic success.
- If there is no existing canonical schema for timeline or review, downstream consumers may already rely on implicit provider-specific behavior.

## Acceptance Criteria

- An orchestrator request can specify a `provider` and execute through the correct adapter.
- `Codex CLI` and `Claude Code CLI` are both supported in v1.
- Both providers return a shared `ExecutionResult` shape.
- Every run produces a timeline with stable event types and timestamps.
- Every run produces artifact metadata, including at least raw execution logs and normalized result data.
- Review output is available in one normalized schema regardless of provider.
- Failed runs still emit usable timeline and error artifacts.
- Tests cover adapter selection, output normalization, and at least one failure path per provider.
- Documentation is sufficient for another engineer to add a third provider without changing orchestrator core logic.

## Open Questions

- What is the exact current meaning of `review` in this project: code review, execution validation, or human approval packaging?
- Are `timeline` and `artifacts` already existing domain objects, or do they need to be introduced from scratch?
- Is provider selection explicit in the task input, inferred from configuration, or chosen by a planner component?
- Do both CLIs already exist as local dependencies in the runtime environment, or must installation/bootstrap be part of the work?
- Is streaming required for v1, or is post-run normalization acceptable?
- What artifact retention policy is expected for logs, diffs, and generated files?
- Which fields are mandatory for auditability: run ID, prompt hash, command line, env snapshot, timestamps, reviewer, artifact checksums?
- Should review happen inside the same provider run, or as a separate orchestrator stage after execution?
- Is a backward-compatible wrapper needed so existing single-provider flows keep working unchanged?
- What is the expected output format for external consumers: JSON only, file-based records, database rows, or both?
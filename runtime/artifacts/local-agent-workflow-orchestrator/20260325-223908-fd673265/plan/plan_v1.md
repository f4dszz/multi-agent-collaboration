## Objective
Deliver a v1 multi-agent review workflow that can run against both `Codex CLI` and `Claude Code CLI` through a shared provider layer, and produce a review run record with:

- normalized review output
- execution timeline
- stored artifacts
- enough metadata to compare runs across providers

## Scope
In scope for the first implementation:

- A provider abstraction for `Codex CLI` and `Claude Code CLI`
- A review job model that defines inputs, run status, outputs, and metadata
- An orchestration flow that launches a provider-specific review run and tracks progress
- Timeline/event capture for major lifecycle steps
- Artifact capture for prompts, raw provider output, logs, and normalized review result
- Minimal retrieval surface for inspecting a completed review run
- Basic failure handling, retries only where low-risk

Out of scope for v1 unless already required elsewhere:

- Adding more providers beyond the two CLIs
- Sophisticated scheduling or distributed execution
- UI-heavy review visualization
- Deep policy engines for reviewer assignment
- Full historical analytics beyond basic run inspection

## Implementation Steps
1. Define the v1 domain model.
   - Create core entities such as `ReviewRequest`, `ReviewRun`, `ProviderConfig`, `TimelineEvent`, and `ArtifactRecord`.
   - Decide stable IDs, status enums, and timestamps for each lifecycle transition.

2. Define the provider interface.
   - Standardize methods such as `prepare`, `execute`, `stream_events` or `collect_output`, `normalize_result`, and `collect_artifacts`.
   - Keep the interface narrow so provider adapters only own CLI-specific behavior.

3. Implement the `Codex CLI` provider adapter.
   - Handle command construction, input packaging, working directory rules, timeout handling, and parsing of stdout/stderr.
   - Produce normalized result fields plus raw artifacts.

4. Implement the `Claude Code CLI` provider adapter.
   - Mirror the same contract as the `Codex CLI` adapter.
   - Isolate differences in invocation flags, output format, and error handling.

5. Build the review orchestrator.
   - Accept a review request, select provider, create a `ReviewRun`, invoke the adapter, and transition statuses deterministically.
   - Emit timeline events for `queued`, `started`, `input_prepared`, `provider_invoked`, `output_received`, `artifacts_written`, `completed`, and `failed`.

6. Add artifact persistence.
   - Store at least:
     - request payload
     - rendered prompt/input package
     - raw CLI stdout/stderr
     - normalized review result
     - execution metadata
   - Define a predictable artifact directory or persistence schema per run.

7. Add timeline persistence and retrieval.
   - Persist ordered events with timestamps and optional payloads.
   - Expose a simple way to query a run and reconstruct execution history.

8. Normalize review output.
   - Define a provider-independent result schema for findings, severity, summary, and references.
   - Keep the first version conservative: support only fields both providers can produce reliably.

9. Add operational safeguards.
   - Timeouts per run
   - Exit-code handling
   - Partial artifact capture on failure
   - Clear distinction between provider failure and review-content failure

10. Add tests.
   - Unit tests for provider adapters with fixture outputs
   - Orchestrator tests for success, timeout, malformed output, and provider failure
   - Contract tests to ensure both providers emit the same normalized schema
   - If possible, one non-blocking integration test per CLI behind environment gating

11. Document the workflow.
   - Document provider configuration, run lifecycle, artifact layout, and normalized result schema.
   - Include example review runs for both providers.

## Risks
- CLI behavior may differ substantially between `Codex CLI` and `Claude Code CLI`, especially around invocation, streaming, and machine-readable output.
- Output normalization may become lossy if one provider exposes richer review structure than the other.
- Artifact volume can grow quickly if raw outputs and logs are retained without limits.
- Timeline fidelity may be inconsistent if providers do not expose incremental events.
- Local execution constraints, auth state, or provider-specific environment setup may make integration tests flaky.
- If the orchestrator mixes provider logic with workflow logic, adding future providers will become expensive.

## Acceptance Criteria
- A review request can be executed with either `Codex CLI` or `Claude Code CLI` by switching only provider configuration.
- Each run produces a persisted `ReviewRun` record with status, provider, timestamps, and execution metadata.
- Each run produces a persisted ordered timeline with major lifecycle events.
- Each run stores the defined artifacts, including raw provider output and normalized review result.
- The normalized result shape is the same regardless of provider.
- Failures still produce a terminal run state and retain useful diagnostic artifacts.
- Automated tests cover the main success and failure paths for both provider adapters and the orchestrator.

## Open Questions
- What is the exact trigger for a “review” run: code diff, full repository, task prompt, or generated artifact bundle?
- Is provider selection manual, rule-based, or fallback-driven?
- What exact artifacts are mandatory in v1: prompt, transcript, stdout/stderr, patch suggestions, structured findings?
- Is the timeline only for backend observability, or will it be user-facing?
- Do we need real-time streaming of timeline/events, or is post-run inspection enough for v1?
- What storage layer should hold runs and artifacts: filesystem, database, object storage, or mixed?
- Do we need cross-provider comparison in v1, or only per-run inspection?
- Are there security or privacy constraints on storing raw prompts, repository context, or model outputs?
- Should the orchestrator support multi-agent fan-out in v1, or only one provider execution per review run?
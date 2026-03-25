## Objective
Build a first usable agent workflow that can run tasks through `Codex CLI` and `Claude Code CLI` behind a common `provider` abstraction, execute a configurable `review` step, and persist both `timeline` events and `artifacts` for later inspection.

## Scope
- Implement a local, single-process orchestration flow for one task run at a time.
- Support at least two execution providers: `Codex CLI` and `Claude Code CLI`.
- Define a shared provider contract for invocation, streaming/output capture, exit status, and metadata.
- Add a first review workflow after execution completes.
- Persist run data to disk, including structured `timeline` events and generated `artifacts`.
- Expose the flow through a simple CLI entrypoint.
- Exclude distributed scheduling, UI/dashboard work, and advanced multi-agent parallelism from the first version.
- Exclude cost optimization, retry tuning, and resume/checkpointing unless they are needed to make the first version reliable.

## Implementation Steps
1. Define the run model.
   - Create core entities such as `TaskRun`, `ProviderConfig`, `ExecutionResult`, `ReviewResult`, `TimelineEvent`, and `ArtifactManifest`.
   - Standardize run states: `pending`, `running`, `reviewing`, `completed`, `failed`, `cancelled`.

2. Define the provider interface.
   - Create a provider contract with methods for `prepare`, `execute`, `collect_artifacts`, and `cleanup`.
   - Normalize outputs into a shared structure: stdout/stderr, exit code, duration, artifact paths, and provider-specific metadata.
   - Keep provider-specific flags/config isolated behind adapter implementations.

3. Implement the `Codex CLI` provider.
   - Wrap the local CLI invocation.
   - Capture command, working directory, environment subset, stdout/stderr, exit code, and generated files.
   - Convert raw output into the shared execution result format.

4. Implement the `Claude Code CLI` provider.
   - Mirror the same adapter shape used for `Codex CLI`.
   - Handle any provider-specific invocation and output parsing differences without leaking them into orchestration code.

5. Build the orchestration pipeline.
   - Implement a deterministic flow: load task -> select provider -> execute -> review -> finalize.
   - Add explicit failure handling between phases so the run always ends with a persisted terminal state.
   - Make review policy configurable: disabled, same-provider review, or cross-provider review if supported.

6. Implement the review stage.
   - Start with a simple review contract: input is task context plus execution artifacts; output is pass/fail plus findings.
   - Persist the review decision and findings as both structured data and readable markdown/text.
   - Prevent unbounded review loops in v1; one execution pass and one review pass is enough.

7. Persist timeline and artifacts.
   - Write `timeline` as structured append-only records, ideally `jsonl`.
   - Store `artifacts` in a per-run directory with a manifest file that maps logical artifact names to file paths.
   - Capture at minimum: task input, provider selection, command invocation metadata, execution logs, review output, final status.

8. Add the CLI entrypoint.
   - Support a command such as `run-task --provider codex --review enabled --task-file ...`.
   - Print a concise run summary and the output directory path.
   - Return non-zero exit codes on orchestration or provider failures.

9. Add basic test coverage.
   - Unit test provider contract normalization.
   - Unit test orchestration state transitions and failure paths.
   - Add one integration-style test per provider using mocked CLI output if real CLI execution is too unstable for CI.

10. Add minimal operational docs.
   - Document required local dependencies for each provider.
   - Document run directory layout, timeline schema, artifact manifest format, and known limitations of v1.

## Risks
- `Codex CLI` and `Claude Code CLI` may have different output formats, making normalization brittle.
- CLI behavior may change across versions, especially if parsing depends on human-readable output.
- Review output may be inconsistent unless a strict review schema is enforced.
- Artifact discovery can be unreliable if providers modify files outside the expected workspace or do not report outputs explicitly.
- If the first version mixes orchestration logic with provider-specific branching, adding more providers later will become expensive.
- Cross-provider review may introduce environment and credential assumptions that are not yet modeled.
- Without a strict run directory structure, debugging failed runs will become difficult quickly.

## Acceptance Criteria
- A task can be executed through `Codex CLI` using the shared orchestration path.
- The same task can be executed through `Claude Code CLI` using the same orchestration path.
- The orchestration layer depends on a provider interface, not on CLI-specific code paths.
- Each run produces a durable output directory containing a structured `timeline` and an `artifacts` manifest.
- A review phase runs after execution and produces a persisted result with findings or approval status.
- Failures in execution or review still produce a terminal run record and persisted logs.
- The CLI returns clear status and exit codes that can be used by automation.
- Basic automated tests cover provider normalization and orchestration state transitions.

## Open Questions
- Should `review` always run, or should it be policy-driven per task/provider?
- Is review expected to be done by the same provider, a different provider, or either?
- What counts as an `artifact` in v1: logs only, patches/files, model transcripts, or all of them?
- What is the required retention format for `timeline`: JSONL, database rows, or both?
- Do we need streaming events during execution, or is post-run persistence sufficient for the first version?
- Should the orchestrator support provider-specific capabilities now, or keep the v1 contract intentionally minimal?
- Are there existing repository conventions for run directories, schema naming, or audit fields that this design must follow?
- Does the first version need resumability/cancellation, or can it treat each run as fire-and-forget?
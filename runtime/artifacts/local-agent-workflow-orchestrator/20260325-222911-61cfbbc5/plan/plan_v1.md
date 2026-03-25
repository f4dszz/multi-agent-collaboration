## Objective

Deliver a first vertical slice for provider-based review execution in the local agent workflow orchestrator.

Assumption: the task means “support `Codex CLI` and `Claude Code CLI` as review providers, select them via `provider`, and persist a common `timeline` plus `artifacts` for each run.” The task text is partially corrupted, so this assumption should be confirmed before implementation starts.

## Scope

- Add a provider abstraction for review execution, with `codex` and `claude` as the first two implementations.
- Route review runs through a single orchestrator entrypoint that accepts a `provider` field.
- Standardize run metadata, lifecycle states, timeline events, and artifact manifests across providers.
- Persist run outputs to a stable filesystem layout for the first implementation.
- Keep the first version synchronous and local-process based; do not add queueing, parallel scheduling, or distributed execution yet.
- Defer advanced result parsing if provider outputs are inconsistent; raw review output must still be preserved.

## Implementation Steps

1. Define the common review-run contract.
   Introduce a provider-independent request/response model such as `ReviewRequest`, `ReviewRun`, `ReviewEvent`, and `ArtifactRef`, plus normalized statuses like `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`.

2. Define a stable run directory layout.
   Use a layout such as `runs/<runId>/metadata.json`, `events.jsonl`, `stdout.log`, `stderr.log`, `review.json`, and `artifacts/`. This keeps the first version easy to inspect and test.

3. Refactor the orchestrator to dispatch by provider.
   Add a `ReviewProvider` interface with methods like `prepare`, `execute`, and `collectArtifacts`, then route existing review execution through that interface rather than branching inline.

4. Build a shared subprocess execution wrapper.
   Centralize process spawning, timeout handling, exit-code capture, stdout/stderr streaming, environment setup, and timestamped event emission so both providers use the same runtime behavior.

5. Implement the `Codex CLI` provider.
   Map the common `ReviewRequest` into the exact non-interactive `Codex CLI` invocation, capture raw output, and emit normalized lifecycle events.

6. Implement the `Claude Code CLI` provider.
   Apply the same contract and wrapper, with provider-specific command construction and output capture, while keeping emitted events and artifact structure identical to the `Codex CLI` path.

7. Normalize review outputs at the storage boundary.
   Persist raw provider output as an artifact in all cases. If lightweight parsing is reliable, also extract a normalized summary and findings list; if not, keep parsing optional in v1 and store only raw text plus metadata.

8. Record timeline events explicitly.
   Emit events for `run_created`, `provider_selected`, `process_started`, `stdout_chunk` or `phase_update`, `process_finished`, `artifacts_written`, and `run_completed` or `run_failed`. Store them as append-only `jsonl` for replay/debugging.

9. Add provider/config validation.
   Validate supported providers, CLI availability, required flags, timeout bounds, and output directory creation before execution starts. Fail early with actionable errors.

10. Add tests and fixtures.
    Cover provider dispatch, event emission order, artifact manifest generation, timeout/failure handling, and one smoke test per provider behind environment guards or mocks.

11. Document the operator contract.
    Document required CLIs, expected config shape, run directory structure, and how reviewers should inspect `timeline` and `artifacts`.

## Risks

- The two CLIs may not expose equally structured outputs, which can make normalized parsing brittle.
- CLI flags, output formats, or exit-code semantics may change between versions and break adapters.
- Non-interactive execution may still depend on local auth/session state, creating environment-specific failures.
- Raw logs and prompts may contain sensitive data, so artifact persistence needs redaction rules or an allowlist.
- If the current orchestrator already has provider-specific assumptions embedded in multiple layers, the refactor may touch more code than expected.

## Acceptance Criteria

- A single review entrypoint can execute with `provider=codex` and `provider=claude`.
- Each run produces a stable run directory with metadata, timeline, raw logs, and a review output artifact.
- Timeline events use a common schema regardless of provider.
- Provider selection, start/end timestamps, exit status, and artifact locations are recorded in normalized metadata.
- Failures such as missing CLI, timeout, or non-zero exit are surfaced consistently and leave inspectable artifacts.
- Basic automated tests cover dispatch, artifact creation, and at least one error path per provider.

## Open Questions

- The task text is partially corrupted. Is the core goal exactly “provider-based review execution for `Codex CLI` and `Claude Code CLI`,” or is there additional scope?
- What is the existing review entrypoint: CLI command, service endpoint, or internal worker?
- What should `review.json` contain in v1: raw text only, structured findings, or both?
- Should timeline events be streamed to consumers in real time, or is post-run persistence sufficient for the first version?
- Are both CLIs guaranteed to be installed on the same host, with stable authentication available in non-interactive mode?
- What artifact retention and redaction policy is required for prompts, logs, and provider outputs?
## Objective
Build a first usable implementation of a local agent workflow orchestrator that can run `Codex CLI` and `Claude Code CLI` behind a common provider interface, execute task and review stages, and persist execution `timeline` plus generated `artifacts`.

Assumption:
The task text appears partially corrupted. This plan assumes the intended project is an agent runner that supports multiple CLI providers, review workflows, and audit outputs.

## Scope
In scope for v1:
- Single-machine, non-interactive execution.
- Provider adapters for `Codex CLI` and `Claude Code CLI`.
- A common task spec for:
  - executor step
  - optional reviewer step
  - artifact collection
  - timeline/event logging
- Structured run output on disk.
- Basic retry/failure handling.
- Minimal configuration for provider selection and step parameters.

Out of scope for v1:
- Distributed execution.
- Real-time web UI.
- Human-in-the-loop approvals.
- Multi-tenant auth/permissions.
- Advanced scheduling/queuing.

## Implementation Steps
1. Define the run contract.
- Create a canonical workflow schema, for example:
  - `task_id`
  - `objective`
  - `inputs`
  - `executor`
  - `reviewer`
  - `artifacts`
  - `output_dir`
- Define normalized step result fields:
  - `status`
  - `stdout`
  - `stderr`
  - `exit_code`
  - `started_at`
  - `finished_at`
  - `artifacts`
  - `provider_metadata`

2. Design the provider abstraction.
- Introduce a `Provider` interface with methods such as:
  - `prepare()`
  - `run_step(step_spec)`
  - `collect_artifacts(run_context)`
  - `normalize_result(raw_result)`
- Keep provider-specific CLI flags isolated inside adapters.

3. Implement the CLI adapters.
- Add a `CodexCliProvider`.
- Add a `ClaudeCodeCliProvider`.
- Each adapter should:
  - build the correct command line
  - inject prompt/input payloads
  - capture stdout/stderr/exit code
  - enforce timeout and working directory
  - return normalized step results

4. Build the orchestration engine.
- Implement a run coordinator that executes:
  - executor step
  - reviewer step if configured
  - final aggregation
- Store each state transition as a timeline event:
  - `run_started`
  - `step_started`
  - `step_completed`
  - `artifact_collected`
  - `run_failed`
  - `run_completed`

5. Add artifact management.
- Define a stable output layout, for example:
  - `runs/<run_id>/timeline.jsonl`
  - `runs/<run_id>/steps/<step_id>.json`
  - `runs/<run_id>/artifacts/...`
  - `runs/<run_id>/summary.md`
- Collect:
  - rendered prompts
  - normalized step results
  - copied output files
  - final review notes

6. Implement review flow semantics.
- Decide the minimal review contract:
  - reviewer receives executor output plus task context
  - reviewer can emit `approved`, `changes_requested`, or `failed`
- For v1, keep it single-pass:
  - executor runs once
  - reviewer runs once
  - no automatic rework loop unless explicitly configured later

7. Add configuration and routing.
- Support provider selection per step:
  - executor can use `codex`
  - reviewer can use `claude`
- Add config for:
  - binary path
  - timeout
  - environment vars
  - working directory
  - artifact include/exclude rules

8. Add observability and auditability.
- Emit machine-readable logs.
- Include exact command metadata, redacting secrets.
- Write a final run summary with:
  - workflow spec
  - step statuses
  - artifact index
  - review outcome

9. Add failure handling.
- Handle:
  - missing provider binary
  - command timeout
  - malformed provider output
  - partial artifact collection
- Mark run state clearly and preserve partial outputs.

10. Validate with end-to-end fixtures.
- Create sample workflows:
  - executor only with Codex
  - executor Codex + reviewer Claude
  - executor Claude + reviewer Codex
  - failing provider command
- Verify timeline and artifact structure is deterministic.

## Risks
- The two CLIs may differ substantially in invocation model, output format, and non-interactive behavior.
- Provider output may not be stable enough for strict parsing; normalization may require defensive parsing.
- Artifact boundaries may be ambiguous if providers write files outside the expected workspace.
- Review semantics can become underspecified if the reviewer is expected to trigger automatic rework.
- If prompts and outputs are stored verbatim, secret leakage becomes a risk.

## Acceptance Criteria
- A workflow can be defined once and executed with either `Codex CLI` or `Claude Code CLI` as the provider for a step.
- The orchestrator can run at least:
  - one executor-only workflow
  - one executor + reviewer workflow
- Every run produces:
  - a timeline log
  - per-step normalized result files
  - a stable artifact directory
  - a final summary
- Provider failures are surfaced as structured run failures without losing prior timeline events or collected artifacts.
- Review output is persisted and linked to the executor result it evaluated.

## Open Questions
- What is the exact intended meaning of `review` in this project:
  - code review only
  - output quality review
  - approval gate
  - change-request loop
- Should `timeline` be optimized for human reading, machine parsing, or both?
- What counts as an `artifact`:
  - generated files
  - prompts
  - logs
  - patches
  - summaries
- Is the reviewer allowed to use a different provider than the executor by default?
- Do we need automatic retry or rework in v1, or only single-pass execution plus review?
- What is the required source of truth for run configuration:
  - YAML
  - JSON
  - CLI flags
  - Python/TS API
- Are there existing repo constraints on language, storage format, or logging framework that should shape the first implementation?
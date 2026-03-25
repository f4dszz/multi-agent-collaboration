## Objective
Implement the first end-to-end validation of the local agent workflow so that:

1. Codex produces an initial plan for a task.
2. Claude reviews that plan.
3. The orchestrator records the review result and transitions to a post-review state.
4. The workflow completes without hanging on reviewer coordination.

## Scope
Included in this first pass:

- One happy-path workflow: `draft -> review -> post-review`.
- Codex as plan author and Claude as reviewer.
- State persistence or in-memory state tracking for the review lifecycle.
- Non-blocking execution with bounded timeouts and explicit failure states.
- Automated validation of the full flow.

Out of scope for this pass:

- Multi-round review loops.
- Plan revision after review.
- Multiple reviewers.
- Production-grade retry policies beyond basic timeout/error handling.
- UI work beyond minimal logs or state output needed for debugging.

## Implementation Steps
1. Define the workflow state model.
   - Add explicit states for `drafting`, `review_requested`, `under_review`, `post_review`, and `failed`.
   - Define the exact transition conditions for entering `post_review`.

2. Define the message contracts between agents.
   - Specify the structure for the Codex plan output.
   - Specify the structure for the Claude review output.
   - Keep the schema minimal and machine-checkable.

3. Implement Codex draft generation in the orchestrator.
   - Invoke Codex with the task prompt.
   - Capture the returned markdown plan as a structured workflow artifact.
   - Mark the workflow as `review_requested` when draft creation succeeds.

4. Implement Claude review execution.
   - Send the captured draft to Claude using a reviewer-specific prompt.
   - Store the review result separately from the original draft.
   - Transition through `under_review` while the review is in progress.

5. Make review completion non-blocking.
   - Add a bounded wait with timeout.
   - Ensure the orchestrator never waits indefinitely for Claude.
   - On timeout or transport failure, move to `failed` with a concrete reason instead of hanging.

6. Implement post-review transition logic.
   - After any valid Claude review response, mark the workflow `post_review`.
   - Do not require approval semantics in this first pass unless the existing system already does.
   - Preserve both draft and review artifacts for later inspection.

7. Add logging and trace points.
   - Log each state transition with timestamps.
   - Log agent invocation start/end and timeout/error conditions.
   - Make the final workflow state easy to assert in tests.

8. Add automated tests.
   - Unit tests for state transitions.
   - Contract tests for parsing/validating Codex and Claude outputs.
   - An end-to-end test that runs the full happy path and asserts `post_review`.

9. Add one failure-path test.
   - Simulate Claude timeout or malformed response.
   - Assert that the workflow exits cleanly into `failed` and does not block.

## Risks
- “Post-review” may be underspecified, which can cause ambiguous transition logic.
- Reviewer output may vary in format unless the prompt contract is strict.
- The orchestrator may still block if subprocess or stream handling is not bounded.
- If state transitions are distributed across multiple modules, regressions are likely without focused tests.
- If existing workflow code assumes approval rather than review completion, integration may require a small refactor.

## Acceptance Criteria
- Given a task, Codex produces a draft plan artifact.
- The orchestrator sends that draft to Claude for review automatically.
- Claude’s review is persisted as a separate artifact.
- The workflow reaches `post_review` after a valid review response.
- The workflow does not hang; all waits are bounded by timeout.
- On reviewer timeout or malformed output, the workflow exits with a terminal non-blocking failure state.
- Automated tests cover the happy path and at least one non-blocking failure path.

## Open Questions
- What is the exact canonical name of the post-review state in the current codebase?
- Does “post-review” mean “review completed” or “review completed and approved”?
- Is Claude already integrated as a callable reviewer, or does this require a new adapter?
- Should the first pass persist workflow state to disk/database, or is in-memory state sufficient?
- What timeout threshold should define “without blocking” for reviewer completion?
const API_ROOT = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : window.location.origin;

const backendStatus = document.getElementById("backend-status");
const workspaceLabel = document.getElementById("workspace-label");
const providersNode = document.getElementById("providers");
const runsNode = document.getElementById("runs");
const runOverviewNode = document.getElementById("run-overview");
const actionConsoleNode = document.getElementById("action-console");
const stepsNode = document.getElementById("steps");
const approvalsNode = document.getElementById("approvals");
const timelineNode = document.getElementById("timeline");
const findingsNode = document.getElementById("findings");
const artifactsNode = document.getElementById("artifacts");
const resultsNode = document.getElementById("results");
const workspaceInput = document.getElementById("workspace");
const taskInput = document.getElementById("task");
const runForm = document.getElementById("run-form");
const refreshProvidersButton = document.getElementById("refresh-providers");
const refreshRunsButton = document.getElementById("refresh-runs");
const continueButton = document.getElementById("continue-button");

const executorSelect = document.getElementById("executor-provider");
const reviewerSelect = document.getElementById("reviewer-provider");
const verifierSelect = document.getElementById("verifier-provider");

const state = {
  selectedRunId: null,
  currentRun: null,
  providers: [],
  runs: [],
};

async function main() {
  await Promise.allSettled([loadHealth(), loadProviders(), loadRuns()]);
  bindEvents();
  if (!taskInput.value) {
    taskInput.value =
      "实现一个用户可审批的多 agent 协作流程：先讨论计划，再给用户审批，之后按步骤执行并在关键节点暂停。";
  }
}

function bindEvents() {
  refreshProvidersButton.addEventListener("click", loadProviders);
  refreshRunsButton.addEventListener("click", loadRuns);
  continueButton.addEventListener("click", continueSelectedRun);
  runForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await createRun();
  });
  runsNode.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-run-id]");
    if (!button) {
      return;
    }
    await selectRun(button.dataset.runId);
  });
  actionConsoleNode.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]");
    if (!action || !state.currentRun) {
      return;
    }
    const { run_id: runId } = state.currentRun;
    if (action.dataset.action === "approve-plan") {
      await submitPlanApproval(runId, true);
    }
    if (action.dataset.action === "reject-plan") {
      await submitPlanApproval(runId, false);
    }
    if (action.dataset.action === "approve-checkpoint") {
      await submitCheckpointApproval(runId, true);
    }
    if (action.dataset.action === "reject-checkpoint") {
      await submitCheckpointApproval(runId, false);
    }
    if (action.dataset.action === "approve-final") {
      await submitFinalApproval(runId, true);
    }
    if (action.dataset.action === "reject-final") {
      await submitFinalApproval(runId, false);
    }
  });
}

async function loadHealth() {
  try {
    const response = await fetch(`${API_ROOT}/api/health`);
    const data = await response.json();
    backendStatus.textContent = data.status;
    workspaceLabel.textContent = data.default_workspace;
    workspaceInput.value = data.default_workspace;
  } catch (error) {
    backendStatus.textContent = "offline";
    workspaceLabel.textContent = "backend unavailable";
  }
}

async function loadProviders() {
  try {
    const response = await fetch(`${API_ROOT}/api/providers`);
    const data = await response.json();
    state.providers = data.providers || [];
    renderProviders();
  } catch (error) {
    state.providers = [];
    renderProviders();
  }
}

async function loadRuns() {
  try {
    const response = await fetch(`${API_ROOT}/api/runs`);
    const data = await response.json();
    state.runs = data.runs || [];
    renderRuns();
    if (!state.selectedRunId && state.runs[0]) {
      await selectRun(state.runs[0].run_id);
    }
  } catch (error) {
    state.runs = [];
    renderRuns();
  }
}

async function selectRun(runId) {
  const response = await fetch(`${API_ROOT}/api/runs/${runId}`);
  const data = await response.json();
  state.selectedRunId = runId;
  state.currentRun = data.run;
  renderRuns();
  renderCurrentRun();
}

async function createRun() {
  const payload = {
    workspace: workspaceInput.value,
    executor_provider: executorSelect.value,
    reviewer_provider: reviewerSelect.value,
    verifier_provider: verifierSelect.value || null,
    task: taskInput.value,
    max_plan_rounds: Number(document.getElementById("max-plan-rounds").value || 2),
  };
  setOverviewMessage("计划讨论中...");
  const response = await fetch(`${API_ROOT}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    setOverviewMessage(data.error || "create run failed");
    return;
  }
  state.selectedRunId = data.run_id;
  state.currentRun = data;
  await loadRuns();
  renderCurrentRun();
}

async function continueSelectedRun() {
  if (!state.currentRun || !state.currentRun.can_continue) {
    return;
  }
  setOverviewMessage("继续处理中...");
  const response = await fetch(`${API_ROOT}/api/runs/${state.currentRun.run_id}/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await response.json();
  if (!response.ok) {
    setOverviewMessage(data.error || "continue failed");
    return;
  }
  state.currentRun = data;
  await loadRuns();
  renderCurrentRun();
}

async function submitPlanApproval(runId, approved) {
  const payload = {
    approved,
    comment: document.getElementById("plan-comment")?.value || "",
    checkpoint_step_indices: approved ? selectedCheckpointSteps() : [],
  };
  const response = await fetch(`${API_ROOT}/api/runs/${runId}/plan-approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  state.currentRun = data;
  await loadRuns();
  renderCurrentRun();
}

async function submitCheckpointApproval(runId, approved) {
  const awaitingStep = (state.currentRun.steps || []).find((step) => step.status === "awaiting_approval");
  if (!awaitingStep) {
    return;
  }
  const payload = {
    approved,
    step_index: awaitingStep.step_index,
    comment: document.getElementById("checkpoint-comment")?.value || "",
  };
  const response = await fetch(`${API_ROOT}/api/runs/${runId}/checkpoint-approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  state.currentRun = data;
  await loadRuns();
  renderCurrentRun();
}

async function submitFinalApproval(runId, approved) {
  const payload = {
    approved,
    comment: document.getElementById("final-comment")?.value || "",
  };
  const response = await fetch(`${API_ROOT}/api/runs/${runId}/final-approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  state.currentRun = data;
  await loadRuns();
  renderCurrentRun();
}

function renderProviders() {
  providersNode.innerHTML = "";
  populateProviderSelects();
  if (state.providers.length === 0) {
    providersNode.innerHTML = `<article class="card muted-card">backend unavailable</article>`;
    return;
  }
  for (const provider of state.providers) {
    const notes = (provider.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");
    const capabilities = (provider.capabilities || [])
      .map((item) => `<span class="tag">${escapeHtml(item)}</span>`)
      .join("");
    providersNode.innerHTML += `
      <article class="card">
        <strong>${escapeHtml(provider.name)}</strong>
        <div class="meta">available: ${provider.available ? "yes" : "no"}</div>
        <div class="meta">version: ${escapeHtml(provider.version)}</div>
        <div class="meta">executable: ${escapeHtml(provider.executable || "-")}</div>
        <div class="tag-row">${capabilities}</div>
        <ul class="notes">${notes}</ul>
      </article>
    `;
  }
}

function populateProviderSelects() {
  const availableProviders = state.providers.filter((provider) => provider.available).map((provider) => provider.name);
  fillSelect(executorSelect, availableProviders, "codex");
  fillSelect(reviewerSelect, availableProviders, "claude");
  fillSelect(verifierSelect, ["", ...availableProviders], "claude", true);
  document.getElementById("create-run-button").disabled = availableProviders.length === 0;
}

function fillSelect(node, values, preferredValue, allowEmpty = false) {
  node.innerHTML = "";
  const options = values.length > 0 ? values : allowEmpty ? [""] : [];
  for (const value of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value || "none";
    node.appendChild(option);
  }
  if (preferredValue && options.includes(preferredValue)) {
    node.value = preferredValue;
  } else if (allowEmpty) {
    node.value = "";
  }
}

function renderRuns() {
  runsNode.innerHTML = "";
  if (state.runs.length === 0) {
    runsNode.innerHTML = `<article class="card muted-card">暂无运行记录</article>`;
    return;
  }
  for (const run of state.runs) {
    const selected = run.run_id === state.selectedRunId ? " selected-card" : "";
    runsNode.innerHTML += `
      <button class="card button-card${selected}" data-run-id="${escapeHtml(run.run_id)}" type="button">
        <strong>${escapeHtml(run.run_id)}</strong>
        <div class="meta">${escapeHtml(run.state)}</div>
        <div class="meta">${escapeHtml(run.task || "").slice(0, 80)}</div>
      </button>
    `;
  }
}

function renderCurrentRun() {
  if (!state.currentRun) {
    setOverviewMessage("还没有选择 run。");
    actionConsoleNode.className = "action-console empty";
    actionConsoleNode.textContent = "等待创建或选择一个 run。";
    stepsNode.innerHTML = "";
    approvalsNode.innerHTML = "";
    timelineNode.innerHTML = "";
    findingsNode.innerHTML = "";
    artifactsNode.innerHTML = "";
    resultsNode.innerHTML = "";
    continueButton.disabled = true;
    return;
  }

  const run = state.currentRun;
  continueButton.disabled = !run.can_continue;
  runOverviewNode.className = "overview";
  runOverviewNode.innerHTML = `
    <strong>${escapeHtml(run.run_id)}</strong>
    <div class="meta">state: ${escapeHtml(run.state)}</div>
    <div class="meta">task: ${escapeHtml(run.task)}</div>
    <div class="meta">approval mode: ${escapeHtml(run.approval_mode || "once")}</div>
    <div class="meta">current step index: ${escapeHtml(String(run.current_step_index || 0))}</div>
    <div class="meta">generated at: ${escapeHtml(run.generated_at || "-")}</div>
  `;

  actionConsoleNode.className = "action-console";
  actionConsoleNode.innerHTML = renderActionConsole(run);
  renderCardList(stepsNode, run.steps || [], renderStepCard);
  renderCardList(approvalsNode, run.approvals || [], renderApprovalCard, "暂无审批记录");
  renderCardList(timelineNode, run.timeline || [], renderTimelineCard, "暂无时间线记录");
  renderCardList(findingsNode, run.findings || [], renderFindingCard, "暂无 findings");
  renderCardList(artifactsNode, run.artifacts || [], renderArtifactCard, "暂无产物");
  renderCardList(resultsNode, run.task_results || [], renderResultCard, "暂无命令记录");
}

function renderActionConsole(run) {
  if (run.can_approve_plan) {
    return `
      <p>计划讨论已结束。你现在可以勾选哪些步骤需要在执行后暂停审批；如果全部不勾选，就会一次性执行到最终审批。</p>
      <div class="stack compact">${(run.steps || []).map(renderCheckpointOption).join("")}</div>
      <label class="wide"><span>计划审批备注</span><textarea id="plan-comment" rows="3"></textarea></label>
      <div class="inline-actions">
        <button data-action="approve-plan" type="button">批准计划并开始执行</button>
        <button data-action="reject-plan" class="secondary" type="button">要求继续改计划</button>
      </div>
    `;
  }
  if (run.can_approve_checkpoint) {
    const awaitingStep = (run.steps || []).find((step) => step.status === "awaiting_approval");
    return `
      <p>当前已经执行到 checkpoint，需要你决定是否继续。</p>
      <div class="card">
        <strong>Step ${escapeHtml(String(awaitingStep?.step_index || "-"))}: ${escapeHtml(awaitingStep?.title || "")}</strong>
        <div class="meta">${escapeHtml(awaitingStep?.detail || "")}</div>
      </div>
      <label class="wide"><span>节点审批备注</span><textarea id="checkpoint-comment" rows="3"></textarea></label>
      <div class="inline-actions">
        <button data-action="approve-checkpoint" type="button">批准并继续</button>
        <button data-action="reject-checkpoint" class="secondary" type="button">要求返工</button>
      </div>
    `;
  }
  if (run.can_finalize) {
    return `
      <p>全部步骤已执行完成，等待最终人工确认。</p>
      <label class="wide"><span>最终审批备注</span><textarea id="final-comment" rows="3"></textarea></label>
      <div class="inline-actions">
        <button data-action="approve-final" type="button">批准交付</button>
        <button data-action="reject-final" class="secondary" type="button">要求继续修改</button>
      </div>
    `;
  }
  if (run.state === "plan_revision") {
    return "<p>Reviewer 或用户要求修订计划。点击上方“继续执行”会继续计划讨论。</p>";
  }
  if (run.state === "implementing") {
    return "<p>系统正在按已批准计划推进。若当前没有自动继续，请点击上方“继续执行”。</p>";
  }
  if (run.state === "completed") {
    return "<p>Run 已完成。你仍然可以回看全部步骤、产物和审批记录。</p>";
  }
  if (run.state === "blocked") {
    return "<p>Run 已阻塞。请检查 findings、review 和命令记录，决定是否继续人工处理。</p>";
  }
  return "<p>等待下一步动作。</p>";
}

function renderCheckpointOption(step) {
  return `
    <label class="checkbox-card">
      <input class="checkpoint-toggle" type="checkbox" value="${escapeHtml(String(step.step_index))}" />
      <span><strong>Step ${escapeHtml(String(step.step_index))}</strong> ${escapeHtml(step.title)}</span>
    </label>
  `;
}

function renderStepCard(step) {
  return `
    <article class="card">
      <strong>Step ${escapeHtml(String(step.step_index))}: ${escapeHtml(step.title)}</strong>
      <div class="meta">status: ${escapeHtml(step.status)}</div>
      <div class="meta">checkpoint: ${step.requires_approval ? "yes" : "no"}</div>
      <pre>${escapeHtml(step.detail || "")}</pre>
    </article>
  `;
}

function renderApprovalCard(approval) {
  return `
    <article class="card">
      <strong>${escapeHtml(approval.stage)}</strong>
      <div class="meta">approved: ${String(approval.approved)}</div>
      <div class="meta">${escapeHtml(approval.comment || "")}</div>
    </article>
  `;
}

function renderTimelineCard(event) {
  return `
    <article class="card">
      <strong>${escapeHtml(event.state)}</strong>
      <div class="meta">${escapeHtml(event.message)}</div>
    </article>
  `;
}

function renderFindingCard(finding) {
  return `
    <article class="card">
      <strong>${escapeHtml(finding.key)} · ${escapeHtml(finding.title)}</strong>
      <div class="meta">${escapeHtml(finding.severity)} / ${escapeHtml(finding.status)}</div>
      <pre>${escapeHtml(finding.detail || "")}</pre>
    </article>
  `;
}

function renderArtifactCard(artifact) {
  return `
    <article class="card">
      <strong>${escapeHtml(artifact.kind)} v${escapeHtml(String(artifact.version))}</strong>
      <div class="meta">${escapeHtml(artifact.path)}</div>
      <pre>${escapeHtml(artifact.content || "")}</pre>
    </article>
  `;
}

function renderResultCard(result) {
  return `
    <article class="card">
      <strong>${escapeHtml(result.role)} · ${escapeHtml(result.provider)} · ${escapeHtml(result.operation)}</strong>
      <div class="meta">success: ${String(result.success)} / exit: ${escapeHtml(String(result.exit_code))}</div>
      <div class="meta">duration: ${escapeHtml(String(result.duration_ms))} ms / ${escapeHtml(result.created_at || "")}</div>
      <div class="meta">command: ${escapeHtml((result.command || []).join(" "))}</div>
      <pre>${escapeHtml(result.output_text || result.stdout || result.stderr || "")}</pre>
    </article>
  `;
}

function renderCardList(node, items, renderItem, emptyText = "暂无数据") {
  node.innerHTML = "";
  if (!items || items.length === 0) {
    node.innerHTML = `<article class="card muted-card">${escapeHtml(emptyText)}</article>`;
    return;
  }
  for (const item of items) {
    node.innerHTML += renderItem(item);
  }
}

function selectedCheckpointSteps() {
  return Array.from(document.querySelectorAll(".checkpoint-toggle:checked")).map((node) => Number(node.value));
}

function setOverviewMessage(message) {
  runOverviewNode.className = "overview empty";
  runOverviewNode.textContent = message;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

main();

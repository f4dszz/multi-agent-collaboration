const API_ROOT = "http://127.0.0.1:8765";

const backendStatus = document.getElementById("backend-status");
const workspaceLabel = document.getElementById("workspace-label");
const providersNode = document.getElementById("providers");
const runOverviewNode = document.getElementById("run-overview");
const timelineNode = document.getElementById("timeline");
const findingsNode = document.getElementById("findings");
const artifactsNode = document.getElementById("artifacts");
const resultsNode = document.getElementById("results");
const workspaceInput = document.getElementById("workspace");
const form = document.getElementById("plan-form");
const refreshProvidersButton = document.getElementById("refresh-providers");

const executorSelect = document.getElementById("executor-provider");
const reviewerSelect = document.getElementById("reviewer-provider");
const verifierSelect = document.getElementById("verifier-provider");

async function main() {
  await Promise.all([loadHealth(), loadProviders(), loadLastRun()]);
  bindEvents();
}

function bindEvents() {
  refreshProvidersButton.addEventListener("click", async () => {
    await loadProviders();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runPlanCycle();
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
  const response = await fetch(`${API_ROOT}/api/providers`);
  const data = await response.json();
  renderProviders(data.providers || []);
}

async function loadLastRun() {
  const response = await fetch(`${API_ROOT}/api/last-run`);
  const data = await response.json();
  if (data.run) {
    renderRun(data.run);
  }
}

function renderProviders(providers) {
  providersNode.innerHTML = "";
  populateProviderSelects(providers);

  for (const provider of providers) {
    const card = document.createElement("article");
    card.className = "provider-card";
    const notes = (provider.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");
    const capabilities = (provider.capabilities || [])
      .map((item) => `<span class="tag">${escapeHtml(item)}</span>`)
      .join("");
    card.innerHTML = `
      <strong>${escapeHtml(provider.name)}</strong>
      <div class="provider-meta">available: ${provider.available ? "yes" : "no"}</div>
      <div class="provider-meta">version: ${escapeHtml(provider.version)}</div>
      <div class="provider-meta">executable: ${escapeHtml(provider.executable || "-")}</div>
      <div class="tag-row">${capabilities}</div>
      <ul class="muted">${notes}</ul>
    `;
    providersNode.appendChild(card);
  }
}

function populateProviderSelects(providers) {
  const providerNames = providers.filter((provider) => provider.available).map((provider) => provider.name);
  const verifierOptions = ["", ...providerNames];
  fillSelect(executorSelect, providerNames, "codex");
  fillSelect(reviewerSelect, providerNames, "claude");
  fillSelect(verifierSelect, verifierOptions, "claude", true);
}

function fillSelect(node, values, preferredValue, allowEmpty = false) {
  const previous = node.value;
  node.innerHTML = "";
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value || "none";
    node.appendChild(option);
  }
  const target = values.includes(previous) ? previous : preferredValue;
  if (target) {
    node.value = target;
  } else if (allowEmpty) {
    node.value = "";
  }
}

async function runPlanCycle() {
  const payload = {
    workspace: workspaceInput.value,
    executor_provider: executorSelect.value,
    reviewer_provider: reviewerSelect.value,
    verifier_provider: verifierSelect.value || null,
    task: document.getElementById("task").value,
    auto_revision: document.getElementById("auto-revision").checked,
  };

  runOverviewNode.textContent = "running...";
  const response = await fetch(`${API_ROOT}/api/workflows/plan-cycle`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    runOverviewNode.textContent = data.error || "request failed";
    return;
  }
  renderRun(data);
}

function renderRun(run) {
  runOverviewNode.className = "overview";
  runOverviewNode.innerHTML = `
    <strong>run: ${escapeHtml(run.run_id)}</strong>
    <div class="provider-meta">state: ${escapeHtml(run.state)}</div>
    <div class="provider-meta">requires_verifier: ${String(run.requires_verifier)}</div>
    <div class="provider-meta">generated_at: ${escapeHtml(run.generated_at || "-")}</div>
    <div class="provider-meta">workspace: ${escapeHtml(run.workspace || "-")}</div>
  `;

  timelineNode.innerHTML = "";
  for (const event of run.timeline || []) {
    const card = document.createElement("article");
    card.className = "timeline-card";
    card.innerHTML = `
      <strong>${escapeHtml(event.state)}</strong>
      <div>${escapeHtml(event.message)}</div>
    `;
    timelineNode.appendChild(card);
  }

  findingsNode.innerHTML = "";
  for (const finding of run.findings || []) {
    const card = document.createElement("article");
    card.className = "finding-card";
    card.innerHTML = `
      <strong>${escapeHtml(finding.key)} · ${escapeHtml(finding.title)}</strong>
      <div class="provider-meta">${escapeHtml(finding.detail)}</div>
      <div class="tag-row">
        <span class="tag blocker">${escapeHtml(finding.severity)}</span>
        <span class="tag ${escapeHtml(finding.status)}">${escapeHtml(finding.status)}</span>
      </div>
    `;
    findingsNode.appendChild(card);
  }

  artifactsNode.innerHTML = "";
  for (const artifact of run.artifacts || []) {
    const card = document.createElement("article");
    card.className = "artifact-card";
    card.innerHTML = `
      <strong>${escapeHtml(artifact.kind)} v${artifact.version}</strong>
      <div class="provider-meta">${escapeHtml(artifact.path)}</div>
      <pre>${escapeHtml(artifact.content || "")}</pre>
    `;
    artifactsNode.appendChild(card);
  }

  resultsNode.innerHTML = "";
  for (const result of run.task_results || []) {
    const card = document.createElement("article");
    card.className = `result-card ${result.success ? "" : "error"}`.trim();
    card.innerHTML = `
      <strong>${escapeHtml(result.role)} · ${escapeHtml(result.provider)} · ${escapeHtml(result.operation)}</strong>
      <div class="provider-meta">exit: ${result.exit_code} · duration: ${result.duration_ms} ms</div>
      <div class="provider-meta">cwd: ${escapeHtml(result.cwd)}</div>
      <div class="provider-meta">command: ${escapeHtml((result.command || []).join(" "))}</div>
      <pre>${escapeHtml(result.output_text || result.stdout || result.stderr || "")}</pre>
    `;
    resultsNode.appendChild(card);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

main();

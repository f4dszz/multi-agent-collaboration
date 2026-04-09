// Codex - Multi-Agent Orchestrator Frontend
// Chat-style UI: room list | message stream | mailbox viewer

const API = "";
const state = {
  selectedRoomId: null,
  rooms: [],
  polling: null,
  msgCount: 0,
  lastMsgContent: "",    // track last message content for streaming updates
  expandedMsgs: new Set(),
  mailboxState: {},
};

// --- API helpers ---

async function api(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API}${path}`, opts);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

// --- Init ---

async function init() {
  document.getElementById("btn-new-room").onclick = () =>
    document.getElementById("create-dialog").showModal();

  document.getElementById("create-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = Object.fromEntries(fd.entries());
    try {
      await api("POST", "/api/rooms", data);
      document.getElementById("create-dialog").close();
      e.target.reset();
      await loadRooms();
      selectRoom(data.room_id);
    } catch (err) {
      showError(err.message);
    }
  };

  await loadRooms();
  state.polling = setInterval(() => {
    if (state.selectedRoomId) loadRoom(state.selectedRoomId, true);
  }, 3000);

  // Enter key support for task and intervene inputs
  document.getElementById("task-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); submitTask(); }
  });
  document.getElementById("intervene-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); doIntervene(); }
  });
  // Track manual target override — reset after each send
  document.getElementById("intervene-target").addEventListener("change", () => {
    document.getElementById("intervene-target").dataset.userOverride = "1";
  });
}

// --- Rooms ---

async function loadRooms() {
  try {
    state.rooms = await api("GET", "/api/rooms");
  } catch {
    state.rooms = [];
  }
  renderRoomList();
}

function renderRoomList() {
  const el = document.getElementById("room-list");
  if (!state.rooms.length) {
    el.innerHTML = '<div style="padding:12px;color:var(--text-dim);font-size:12px">No rooms yet. Click + to create one.</div>';
    return;
  }
  el.innerHTML = state.rooms
    .map(
      (r) => `
    <div class="room-item ${r.room_id === state.selectedRoomId ? "active" : ""}">
      <div class="room-item-row" onclick="selectRoom('${r.room_id}')">
        <div>
          <div class="room-name">${esc(r.room_id)}</div>
          <div class="room-meta">${esc(r.state)} &middot; ${esc(r.task || "no task")}</div>
        </div>
      </div>
      <button class="room-delete" onclick="event.stopPropagation();deleteRoom('${r.room_id}')" title="Delete room">&times;</button>
    </div>`
    )
    .join("");
}

async function selectRoom(roomId) {
  state.selectedRoomId = roomId;
  state.msgCount = 0;
  state.expandedMsgs.clear();
  state.mailboxState = {};
  renderRoomList();
  await loadRoom(roomId);
}

async function deleteRoom(roomId) {
  if (!confirm(`Delete room "${roomId}"? This cannot be undone.`)) return;
  try {
    await api("DELETE", `/api/rooms/${roomId}`);
    if (state.selectedRoomId === roomId) {
      state.selectedRoomId = null;
      state.msgCount = 0;
      document.getElementById("chat-messages").innerHTML = "";
      document.getElementById("room-title").textContent = "Select a room";
      document.getElementById("room-state").textContent = "";
      document.getElementById("mailbox-files").innerHTML = "";
    }
    await loadRooms();
  } catch (err) {
    showError(err.message);
  }
}

// --- Room detail ---

async function loadRoom(roomId, silent) {
  try {
    const data = await api("GET", `/api/rooms/${roomId}`);
    renderRoom(data, silent);
  } catch (err) {
    if (!silent) showError(err.message);
  }
}

function renderRoom(data, silent) {
  const room = data.room;
  const messages = data.messages || [];
  const busy = data.busy || false;

  document.getElementById("room-title").textContent =
    `${room.room_id} — ${room.task || ""}`;
  const badge = document.getElementById("room-state");
  badge.textContent = busy ? `${room.state} (working...)` : room.state;

  // Detect if messages changed (new message or streaming content update)
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
  const lastContent = lastMsg ? lastMsg.content : "";
  const countChanged = messages.length !== state.msgCount;
  const contentChanged = lastContent !== state.lastMsgContent;

  if (countChanged || contentChanged) {
    const el = document.getElementById("chat-messages");
    const wasAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;

    if (countChanged) {
      // Full re-render when new messages arrive
      el.innerHTML = messages.map((m, i) => renderMessage(m, i, busy && i === messages.length - 1)).join("");
    } else if (contentChanged && messages.length > 0) {
      // Only update the last message (streaming update)
      const lastEl = el.querySelector(".message:last-child");
      if (lastEl) {
        const bodyEl = lastEl.querySelector(".msg-body");
        if (bodyEl) {
          bodyEl.innerHTML = md(lastContent);
          bodyEl.classList.remove("collapsed");
        }
      }
    }

    if (wasAtBottom || !silent) {
      el.scrollTop = el.scrollHeight;
    }
    state.msgCount = messages.length;
    state.lastMsgContent = lastContent;
  }

  // Mailbox: update content but preserve open/closed state
  renderMailbox(data.mailbox_files || {});

  updateActions(room.state, busy, data.auto_mode || false);

  // Update lightweight agent status badges
  updateAgentBadges(data);

  // Smart default: target the opposite of whoever spoke last
  const targetEl = document.getElementById("intervene-target");
  if (targetEl && messages.length > 0) {
    const lastAgent = [...messages].reverse().find(m => m.sender === "executor" || m.sender === "reviewer");
    if (lastAgent) {
      const defaultTarget = lastAgent.sender === "executor" ? "reviewer" : "executor";
      if (targetEl.value !== defaultTarget && !targetEl.dataset.userOverride) {
        targetEl.value = defaultTarget;
      }
    }
  }

  const indicator = document.getElementById("busy-indicator");
  if (busy) {
    indicator.innerHTML = '<span class="loading"></span> Agent is working...';
    indicator.style.display = "block";
  } else {
    indicator.style.display = "none";
  }
}

function renderMessage(m, index, isStreaming) {
  const sender = m.sender;
  const time = m.created_at ? new Date(m.created_at).toLocaleTimeString() : "";
  const raw = m.content || "";
  const html = md(raw);
  const isLong = raw.length > 500;
  const isExpanded = state.expandedMsgs.has(index);

  const labels = {
    executor: "EXECUTOR",
    reviewer: "REVIEWER",
    user: "USER",
    system: "SYSTEM",
  };

  return `
    <div class="message ${sender} ${isStreaming ? "streaming" : ""}">
      <div class="msg-header">${labels[sender] || sender}${isStreaming ? ' <span class="typing-dot"></span>' : ""}</div>
      <div class="msg-body ${isLong && !isExpanded ? "collapsed" : ""}">${html}</div>
      ${isLong && !isStreaming ? `<button class="msg-toggle" onclick="toggleMsg(this, ${index})">${isExpanded ? "Show less" : "Show more"}</button>` : ""}
      <div class="msg-time">${time}</div>
    </div>`;
}

function toggleMsg(btn, index) {
  if (state.expandedMsgs.has(index)) {
    state.expandedMsgs.delete(index);
  } else {
    state.expandedMsgs.add(index);
  }
  const body = btn.previousElementSibling;
  const collapsed = body.classList.toggle("collapsed");
  btn.textContent = collapsed ? "Show more" : "Show less";
}

function renderMailbox(files) {
  const el = document.getElementById("mailbox-files");
  const names = Object.keys(files).sort();
  if (!names.length) {
    el.innerHTML = '<div style="color:var(--text-dim);font-size:12px">No mailbox files</div>';
    return;
  }

  // Build new content and compare with existing to avoid unnecessary DOM thrash
  const newHtml = names
    .map((name) => {
      const isOpen = state.mailboxState[name] !== undefined
        ? state.mailboxState[name]
        : Object.keys(state.mailboxState).length === 0;
      return `
    <details class="mailbox-file" ${isOpen ? "open" : ""}>
      <summary>${esc(name)}</summary>
      <pre>${esc(files[name])}</pre>
    </details>`;
    })
    .join("");

  // Skip re-render if content hasn't changed (preserves scroll position)
  if (el._lastHtml === newHtml) return;
  el._lastHtml = newHtml;

  // Save current open/closed state before re-render
  el.querySelectorAll("details.mailbox-file").forEach((d) => {
    const name = d.querySelector("summary")?.textContent;
    if (name) state.mailboxState[name] = d.open;
  });

  // Save and restore scroll position of the right panel
  const panel = el.closest(".panel");
  const scrollPos = panel ? panel.scrollTop : 0;

  el.innerHTML = newHtml;

  if (panel) panel.scrollTop = scrollPos;

  // Listen for toggle events to track state
  el.querySelectorAll("details.mailbox-file").forEach((d) => {
    d.addEventListener("toggle", () => {
      const name = d.querySelector("summary")?.textContent;
      if (name) state.mailboxState[name] = d.open;
    });
  });
}

function updateAgentBadges(data) {
  const exEl = document.getElementById("status-executor");
  const rvEl = document.getElementById("status-reviewer");
  if (!exEl || !rvEl || !data || !data.room) return;

  const busy = data.busy;
  const st = data.room.state;
  const msgs = (data.messages || []).filter(m => m.sender === "executor" || m.sender === "reviewer");
  const last = msgs.length ? msgs[msgs.length - 1].sender : null;

  let exState = "idle", rvState = "idle";

  if (st === "completed") {
    exState = "done"; rvState = "done";
  } else if (busy) {
    if (last === "executor") { exState = "working"; }
    else if (last === "reviewer") { rvState = "working"; }
    else { exState = "working"; }
  }

  const labels = { idle: "idle", working: "working…", done: "✓ done" };
  exEl.textContent = `⚡ Executor: ${labels[exState]}`;
  rvEl.textContent = `📋 Reviewer: ${labels[rvState]}`;
  exEl.classList.toggle("working", exState === "working");
  rvEl.classList.toggle("working", rvState === "working");
}

function updateActions(roomState, busy, autoMode) {
  const onboard = document.getElementById("btn-onboard");
  const next = document.getElementById("btn-next");
  const autoBtn = document.getElementById("btn-auto");
  const approve = document.getElementById("btn-approve");
  const reject = document.getElementById("btn-reject");
  const interrupt = document.getElementById("btn-interrupt");
  const taskBar = document.getElementById("task-bar");
  const interveneBar = document.getElementById("intervene-bar");

  // Task input bar: show for awaiting_task AND completed (start new task)
  taskBar.style.display = (roomState === "awaiting_task" || roomState === "completed") ? "flex" : "none";
  const taskInput = document.getElementById("task-input");
  if (taskInput) {
    taskInput.placeholder = roomState === "completed"
      ? "Assign a new task to start another round..."
      : "Describe the task for executor...";
  }

  // Auto button text
  if (autoMode) {
    autoBtn.textContent = "⏸ Pause";
    autoBtn.classList.add("pause");
    autoBtn.classList.remove("auto");
  } else {
    autoBtn.textContent = "▶ Full-Auto";
    autoBtn.classList.remove("pause");
    autoBtn.classList.add("auto");
  }

  // Interrupt: only enabled when busy
  interrupt.disabled = !busy;

  if (busy) {
    onboard.disabled = true;
    next.disabled = true;
    autoBtn.disabled = false; // always allow toggling auto mode
    approve.disabled = true;
    reject.disabled = true;
    return;
  }

  // Completed / onboarding / awaiting_task: disable all working buttons
  const isTerminal = roomState === "completed" || roomState === "onboarding" || roomState === "awaiting_task";
  onboard.disabled = roomState !== "onboarding";
  next.disabled = isTerminal;
  autoBtn.disabled = isTerminal;
  // Approve/reject only when awaiting_approval
  approve.disabled = roomState !== "awaiting_approval";
  reject.disabled = roomState !== "awaiting_approval";
}

// --- Actions ---

async function doNext(action) {
  if (!state.selectedRoomId) return;
  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/next`, { action });
    renderRoom(data);
    await loadRooms();
  } catch (err) {
    showError(err.message);
  }
}

async function doApprove(decision) {
  if (!state.selectedRoomId) return;
  const comment = prompt(`Comment for ${decision}:`, "") || "";
  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/approve`, { decision, comment });
    renderRoom(data);
    await loadRooms();
  } catch (err) {
    showError(err.message);
  }
}

async function doIntervene() {
  if (!state.selectedRoomId) return;
  const input = document.getElementById("intervene-input");
  const target = document.getElementById("intervene-target").value;
  const message = input.value.trim();
  if (!message) return;

  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/approve`, { decision: "intervene", message, target });
    renderRoom(data);
    input.value = "";
    delete document.getElementById("intervene-target").dataset.userOverride;
  } catch (err) {
    showError(err.message);
  }
}

async function submitTask() {
  if (!state.selectedRoomId) return;
  const input = document.getElementById("task-input");
  const task = input.value.trim();
  if (!task) return;

  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/task`, { task });
    renderRoom(data);
    input.value = "";
  } catch (err) {
    showError(err.message);
  }
}

async function toggleAuto() {
  if (!state.selectedRoomId) return;
  // Check current auto_mode from latest room data
  const roomData = await api("GET", `/api/rooms/${state.selectedRoomId}`);
  const isAuto = roomData.auto_mode || false;

  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/auto`, {
      action: isAuto ? "stop" : "start",
    });
    renderRoom(data);
  } catch (err) {
    showError(err.message);
  }
}

async function doInterrupt() {
  if (!state.selectedRoomId) return;
  if (!confirm("Force stop all running agents? This will kill active processes.")) return;
  try {
    const data = await api("POST", `/api/rooms/${state.selectedRoomId}/interrupt`, {});
    renderRoom(data);
    await loadRooms();
  } catch (err) {
    showError(err.message);
  }
}

function showError(msg) {
  const el = document.getElementById("chat-messages");
  el.innerHTML += `
    <div class="message system" style="border-left-color:var(--reject);background:rgba(239,83,80,0.1)">
      <div class="msg-header" style="color:var(--reject)">ERROR</div>
      <div class="msg-body">${esc(msg)}</div>
      <div class="msg-time">${new Date().toLocaleTimeString()}</div>
    </div>`;
  el.scrollTop = el.scrollHeight;
}

// --- Markdown renderer (lightweight) ---

function md(raw) {
  // Escape HTML first, then apply markdown
  let s = esc(raw);

  // Code blocks: ```...```
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre class="md-code"><code>$2</code></pre>');

  // Inline code: `...`
  s = s.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>');

  // Headers: # ## ###
  s = s.replace(/^### (.+)$/gm, '<h4 class="md-h">$1</h4>');
  s = s.replace(/^## (.+)$/gm, '<h3 class="md-h">$1</h3>');
  s = s.replace(/^# (.+)$/gm, '<h2 class="md-h">$1</h2>');

  // Bold + Italic: ***text***
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');

  // Bold: **text**
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic: *text*
  s = s.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

  // Unordered list: - item
  s = s.replace(/^- (.+)$/gm, '<li>$1</li>');
  s = s.replace(/(<li>.*<\/li>\n?)+/g, '<ul class="md-list">$&</ul>');

  // Ordered list: 1. item
  s = s.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Horizontal rule: ---
  s = s.replace(/^---$/gm, '<hr class="md-hr">');

  return s;
}

// --- Star-Office-UI Sync ---

let officeSyncConnected = false;

async function toggleOfficeSync() {
  const btn = document.getElementById("btn-office-sync");
  const statusEl = document.getElementById("office-sync-status");
  try {
    if (officeSyncConnected) {
      await api("POST", "/api/office-sync", { action: "disconnect" });
      officeSyncConnected = false;
      btn.textContent = "🏢 Star-Office";
      btn.classList.remove("primary");
      statusEl.textContent = "Disconnected";
    } else {
      const url = prompt("Star-Office URL:", "http://localhost:19000");
      if (!url) return;
      const data = await api("POST", "/api/office-sync", { action: "connect", url });
      officeSyncConnected = data.ok;
      if (data.ok) {
        btn.textContent = "🏢 Connected";
        btn.classList.add("primary");
        statusEl.textContent = `→ ${url}`;
      } else {
        statusEl.textContent = "Failed to connect";
      }
    }
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// --- Boot ---
init();

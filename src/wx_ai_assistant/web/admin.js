const state = {
  overview: null,
  config: null,
  selectedConversationId: null,
  messageTab: "history",
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindActions();
  refreshAll();
  setInterval(refreshAll, 5000);
});

function bindNavigation() {
  document.querySelectorAll(".nav").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(`view-${button.dataset.view}`).classList.add("active");
      if (button.dataset.view === "settings") loadConfig();
    });
  });
  document.querySelectorAll(".segment").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".segment").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.messageTab = button.dataset.messageTab;
      renderMessages();
    });
  });
}

function bindActions() {
  $("refresh-btn").addEventListener("click", refreshAll);
  $("add-target-btn").addEventListener("click", addTarget);
  $("clear-memory-btn").addEventListener("click", clearMemory);
  $("save-config-btn").addEventListener("click", saveConfig);
}

async function refreshAll() {
  try {
    const overview = await api("/admin-api/overview?limit=80");
    state.overview = overview.data;
    setHealth(true, "服务正常", `${overview.data.targets.length} 个监听对象`);
    if (!state.selectedConversationId && overview.data.targets.length) {
      state.selectedConversationId = overview.data.targets[0].conversation.conversation_id;
    }
    renderDesk();
  } catch (error) {
    setHealth(false, "连接失败", error.message);
    showError(error.message);
  }
}

async function loadConfig() {
  try {
    const config = await api("/admin-api/config");
    state.config = config.data;
    fillConfig(config.data);
  } catch (error) {
    showError(error.message);
  }
}

async function addTarget() {
  const displayName = $("target-name").value.trim();
  const localId = $("target-local-id").value.trim() || displayName;
  if (!displayName) return showError("请填写联系人名称。");
  await action(async () => {
    await api("/listen/targets", {
      method: "POST",
      body: {
        display_name: displayName,
        conversation_type: "friend",
        remark_name: displayName,
        local_id: localId,
      },
    });
    $("target-name").value = "";
    $("target-local-id").value = "";
    await refreshAll();
  });
}

async function startTarget(id) {
  await action(async () => {
    await api(`/listen/targets/${encodeURIComponent(id)}/start`, { method: "POST" });
    await refreshAll();
  });
}

async function stopTarget(id) {
  await action(async () => {
    await api(`/listen/targets/${encodeURIComponent(id)}/stop`, { method: "POST" });
    await refreshAll();
  });
}

async function deleteTarget(id) {
  if (!confirm("确定删除这个监听对象？本地消息不会自动删除。")) return;
  await action(async () => {
    await api(`/listen/targets/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.selectedConversationId === id) state.selectedConversationId = null;
    await refreshAll();
  });
}

async function clearMemory() {
  const id = state.selectedConversationId;
  if (!id) return;
  if (!confirm("只清除本项目本地记忆，不会删除微信聊天记录。确定继续？")) return;
  await action(async () => {
    await api(`/admin-api/conversations/${encodeURIComponent(id)}/clear-memory`, { method: "POST" });
    await refreshAll();
  });
}

async function saveConfig() {
  await action(async () => {
    await api("/admin-api/config", {
      method: "POST",
      body: {
        base_url: $("cfg-base-url").value.trim(),
        api_key: $("cfg-api-key").value.trim() || null,
        model: $("cfg-model").value.trim(),
        temperature: numberOrNull("cfg-temperature"),
        max_tokens: numberOrNull("cfg-max-tokens"),
        timeout_seconds: numberOrNull("cfg-timeout"),
        proactive_mode: $("cfg-proactive").value,
        max_messages_per_turn: numberOrNull("cfg-max-messages"),
        turn_quiet_seconds: numberOrNull("cfg-quiet"),
        duplicate_guard_seconds: numberOrNull("cfg-duplicate"),
        core_prompt: $("cfg-core-prompt").value,
        turn_prompt: $("cfg-turn-prompt").value,
        style_prompt: $("cfg-style-prompt").value,
        contact_policies_json: $("cfg-contact-policies").value,
        conversation_profiles_json: $("cfg-conversation-profiles").value,
      },
    });
    $("cfg-api-key").value = "";
    showError("配置已保存，重启服务后生效。", false);
  });
}

function renderDesk() {
  renderTargets();
  renderMessages();
  renderDecision();
  renderSendTasks();
}

function renderTargets() {
  const targets = state.overview?.targets || [];
  $("target-count").textContent = `${targets.length} 个`;
  const root = $("targets");
  if (!targets.length) {
    root.innerHTML = `<div class="empty">还没有监听对象。</div>`;
    return;
  }
  root.innerHTML = targets.map((target) => {
    const id = target.conversation.conversation_id;
    const status = target.status;
    const active = id === state.selectedConversationId ? " active" : "";
    const error = target.last_error ? `<p class="muted">错误：${escapeHtml(target.last_error)}</p>` : "";
    return `
      <div class="target-item${active}" data-id="${escapeHtml(id)}">
        <div class="target-top">
          <strong>${escapeHtml(target.conversation.display_name)}</strong>
          <span class="badge ${escapeHtml(status)}">${escapeHtml(status)}</span>
        </div>
        <p class="muted">${escapeHtml(id)}</p>
        ${error}
        <div class="target-actions">
          <button class="btn" data-act="select">查看</button>
          <button class="btn" data-act="start">启动</button>
          <button class="btn" data-act="stop">停止</button>
          <button class="btn danger" data-act="delete">删除</button>
        </div>
      </div>
    `;
  }).join("");
  root.querySelectorAll(".target-item").forEach((item) => {
    const id = item.dataset.id;
    item.querySelector('[data-act="select"]').onclick = () => { state.selectedConversationId = id; renderDesk(); };
    item.querySelector('[data-act="start"]').onclick = () => startTarget(id);
    item.querySelector('[data-act="stop"]').onclick = () => stopTarget(id);
    item.querySelector('[data-act="delete"]').onclick = () => deleteTarget(id);
  });
  $("clear-memory-btn").disabled = !state.selectedConversationId;
}

function renderMessages() {
  const id = state.selectedConversationId;
  const root = $("messages");
  if (!id) {
    root.innerHTML = "请选择一个监听对象。";
    root.className = "message-list empty";
    return;
  }
  const target = targetById(id);
  let messages = [];
  if (state.messageTab === "visible") {
    const snapshots = state.overview?.diagnostics?.last_visible_snapshots || [];
    const latest = [...snapshots].reverse().find((item) => item.conversation_id === id);
    messages = latest?.messages || [];
  } else {
    messages = state.overview?.messages_by_target?.[id] || [];
  }
  if (!messages.length) {
    root.innerHTML = "暂无消息。";
    root.className = "message-list empty";
    return;
  }
  root.className = "message-list";
  root.innerHTML = messages.map((message) => {
    const sender = message.sender_type || "unknown";
    return `
      <div class="message-item ${escapeHtml(sender)}">
        <div class="message-meta">${escapeHtml(target?.conversation.display_name || "-")} · ${escapeHtml(sender)}</div>
        <div class="message-content">${escapeHtml(message.content || "")}</div>
      </div>
    `;
  }).join("");
}

function renderDecision() {
  const id = state.selectedConversationId;
  const decisions = (state.overview?.ai_decisions || []).filter((item) => !id || item.conversation_id === id);
  const root = $("decision");
  if (!decisions.length) {
    root.className = "decision empty";
    root.innerHTML = "暂无决策记录。";
    return;
  }
  const latest = decisions[0];
  root.className = "decision";
  root.innerHTML = `
    ${stage("触发", [`${latest.display_name || "-"}：${latest.trigger_message || "-"}`, `run_id：${latest.run_id}`])}
    ${stage("语义判断", [
      `意图：${latest.intent || "-"}`,
      `情绪：${latest.emotion || "-"}`,
      `需求：${latest.user_need || "-"}`,
      `关系信号：${latest.relationship_signal || "-"}`,
    ])}
    ${stage("回复决策", [
      `是否回复：${latest.should_reply ? "是" : "否"}`,
      `不回复原因：${latest.no_reply_reason || "-"}`,
      `策略：${latest.reply_strategy || "-"}`,
    ])}
    ${stage("安全与画像", [
      `动作：${latest.safety_action || "-"}`,
      `联系人策略：${policySummary(latest.contact_policy)}`,
      `会话画像：${profileSummary(latest.conversation_profile)}`,
      ...(latest.safety_reasons || []).map((item) => `原因：${item}`),
    ])}
    ${stage("草稿", latest.draft_messages || [])}
    ${stage("最终发送", latest.final_messages || [])}
  `;
}

function renderSendTasks() {
  const id = state.selectedConversationId;
  const tasks = (state.overview?.send_tasks || []).filter((task) => !id || task.conversation_id === id);
  $("send-count").textContent = `${tasks.length} 条任务`;
  const root = $("send-tasks");
  if (!tasks.length) {
    root.className = "send-list empty";
    root.innerHTML = "暂无发送任务。";
    return;
  }
  root.className = "send-list";
  root.innerHTML = tasks.map((task) => `
    <div class="send-item">
      <div class="send-top">
        <strong>${escapeHtml(task.content || "")}</strong>
        <span class="badge ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
      </div>
      <div class="send-meta">${escapeHtml(task.created_at || "")}</div>
      ${task.error_message ? `<div class="send-content">错误：${escapeHtml(task.error_message)}</div>` : ""}
    </div>
  `).join("");
}

function fillConfig(config) {
  $("api-key-state").textContent = config.api_key_configured ? "API Key 已配置" : "API Key 未配置";
  $("cfg-base-url").value = config.base_url || "";
  $("cfg-model").value = config.model || "";
  $("cfg-temperature").value = config.temperature ?? "";
  $("cfg-max-tokens").value = config.max_tokens ?? "";
  $("cfg-timeout").value = config.timeout_seconds ?? "";
  $("cfg-proactive").value = config.proactive_mode || "off";
  $("cfg-quiet").value = config.turn_quiet_seconds ?? "";
  $("cfg-duplicate").value = config.duplicate_guard_seconds ?? "";
  $("cfg-max-messages").value = config.max_messages_per_turn ?? "";
  $("cfg-core-prompt").value = config.core_prompt || "";
  $("cfg-turn-prompt").value = config.turn_prompt || "";
  $("cfg-style-prompt").value = config.style_prompt || "";
  $("cfg-contact-policies").value = formatJson(config.contact_policies_json);
  $("cfg-conversation-profiles").value = formatJson(config.conversation_profiles_json);
}

function stage(title, items) {
  const safeItems = (items || []).filter(Boolean);
  if (!safeItems.length) return "";
  return `<div class="stage"><h4>${escapeHtml(title)}</h4><ul>${safeItems.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul></div>`;
}

function policySummary(policy = {}) {
  return [policy.name, policy.proactive_mode, policy.tone].filter(Boolean).join(" / ") || "-";
}

function profileSummary(profile = {}) {
  return [profile.relationship, profile.communication_style, profile.initiative_level].filter(Boolean).join(" / ") || "-";
}

function targetById(id) {
  return (state.overview?.targets || []).find((target) => target.conversation.conversation_id === id);
}

async function action(callback) {
  try {
    await callback();
    hideError();
  } catch (error) {
    showError(error.message);
  }
}

async function api(path, options = {}) {
  const fetchOptions = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, fetchOptions);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.detail || data.message || `请求失败：${response.status}`);
  }
  return data;
}

function setHealth(ok, title, detail) {
  $("health-dot").className = ok ? "dot ok" : "dot bad";
  $("health-title").textContent = title;
  $("health-detail").textContent = detail;
}

function showError(message, isError = true) {
  const banner = $("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  banner.style.color = isError ? "var(--danger)" : "var(--ok)";
}

function hideError() {
  $("error-banner").classList.add("hidden");
}

function numberOrNull(id) {
  const value = $(id).value.trim();
  return value === "" ? null : Number(value);
}

function formatJson(text) {
  try {
    return JSON.stringify(JSON.parse(text || "{}"), null, 2);
  } catch {
    return text || "";
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

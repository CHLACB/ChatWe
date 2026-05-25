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
  $("open-targets-btn").addEventListener("click", () => openModal("target-modal"));
  $("close-targets-btn").addEventListener("click", () => closeModal("target-modal"));
  $("status-card").addEventListener("click", () => {
    renderStatusDetail();
    openModal("status-modal");
  });
  $("close-status-btn").addEventListener("click", () => closeModal("status-modal"));
}

async function refreshAll() {
  try {
    const overview = await api("/admin-api/overview?limit=80");
    state.overview = overview.data;
    updateHealth(overview.data);
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

async function retrySendTask(id) {
  await action(async () => {
    await api(`/send/tasks/${encodeURIComponent(id)}/retry`, { method: "POST" });
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
  renderSideTargets();
  renderMessages();
  renderDecision();
  renderSendTasks();
  renderStatusDetail();
}

function renderTargets() {
  const targets = state.overview?.targets || [];
  $("target-count").textContent = `${targets.length} 个`;
  const selected = state.selectedConversationId ? targetById(state.selectedConversationId) : null;
  const title = selected ? `监听详情：${selected.conversation.display_name}` : "监听列表";
  const subtitle = selected
    ? `${selected.status}${selected.last_error ? " · 有异常" : ""}`
    : `${targets.length} 个监听对象`;
  $("target-modal-title").textContent = title;
  $("target-count").textContent = subtitle;
  const root = $("targets");
  if (!targets.length) {
    root.innerHTML = `<div class="empty">还没有监听对象。</div>`;
    return;
  }
  const orderedTargets = selected
    ? [selected, ...targets.filter((target) => target.conversation.conversation_id !== selected.conversation.conversation_id)]
    : targets;
  root.innerHTML = orderedTargets.map((target) => {
    const id = target.conversation.conversation_id;
    const status = target.status;
    const active = id === state.selectedConversationId ? " active" : "";
    const error = target.last_error ? `<p class="target-error">错误：${escapeHtml(explainTargetError(target.last_error))}</p>` : "";
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

function renderSideTargets() {
  const targets = state.overview?.targets || [];
  const root = $("side-targets");
  if (!targets.length) {
    root.innerHTML = `<button class="side-target-item muted">暂无监听对象</button>`;
    return;
  }
  root.innerHTML = targets.map((target) => {
    const id = target.conversation.conversation_id;
    const active = id === state.selectedConversationId ? " active" : "";
    const error = target.last_error ? " error" : "";
    const errorLine = target.last_error ? `<small>${escapeHtml(shortError(target.last_error))}</small>` : "";
    return `
      <button class="side-target-item${active}${error}" data-id="${escapeHtml(id)}">
        <span class="side-target-main">
          <strong>${escapeHtml(target.conversation.display_name)}</strong>
          ${errorLine}
        </span>
        <em>${escapeHtml(target.status)}</em>
      </button>
    `;
  }).join("");
  root.querySelectorAll(".side-target-item[data-id]").forEach((button) => {
    button.onclick = () => {
      state.selectedConversationId = button.dataset.id;
      renderDesk();
      openModal("target-modal");
    };
  });
}

function renderMessages() {
  const id = state.selectedConversationId;
  const root = $("messages");
  const target = id ? targetById(id) : null;
  $("message-target-name").textContent = target ? `当前对象：${target.conversation.display_name}` : "请选择一个监听对象";
  if (!id) {
    root.innerHTML = "请选择一个监听对象。";
    root.className = "message-list empty";
    return;
  }
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
  const pendingTurns = (state.overview?.diagnostics?.pending_ai_turns || []).filter((item) => !id || item.conversation_id === id);
  const aiErrors = (state.overview?.diagnostics?.last_ai_errors || []).filter((item) => !id || item.conversation_id === id);
  const root = $("decision");
  if (!decisions.length && !pendingTurns.length && !aiErrors.length) {
    root.className = "decision empty";
    root.innerHTML = "暂无决策记录。若刚收到对方消息，会先等待静默时间后再启动 AI。";
    return;
  }
  if (!decisions.length) {
    root.className = "decision";
    root.innerHTML = `
      ${pendingTurns.length ? stage("等待 AI", pendingTurns.map((turn) => `已收到：${turn.trigger_content || "-"}；等待静默 ${turn.age_seconds || 0}s`), "trigger-stage") : ""}
      ${aiErrors.length ? stage("AI 错误", aiErrors.map((error) => `${error.display_name || "-"}：${error.error || "-"}`), "safety-stage") : ""}
    `;
    return;
  }
  const latest = decisions[0];
  root.className = "decision";
  root.innerHTML = `
    ${pendingTurns.length ? stage("等待下一轮", pendingTurns.map((turn) => `已收到：${turn.trigger_content || "-"}；等待静默 ${turn.age_seconds || 0}s`), "trigger-stage") : ""}
    ${aiErrors.length ? stage("最近 AI 错误", aiErrors.slice(0, 2).map((error) => `${error.display_name || "-"}：${error.error || "-"}`), "safety-stage") : ""}
    ${stage("触发消息", [`${latest.display_name || "-"}：${latest.trigger_message || "-"}`, `run_id：${latest.run_id}`], "trigger-stage")}
    ${stage("语义判断", [
      `意图：${latest.intent || "-"}`,
      `情绪：${latest.emotion || "-"}`,
      `需求：${latest.user_need || "-"}`,
      `关系信号：${latest.relationship_signal || "-"}`,
    ], "analysis-stage")}
    ${stage("回复决策", [
      `是否回复：${latest.should_reply ? "是" : "否"}`,
      `不回复原因：${latest.no_reply_reason || "-"}`,
      `策略：${latest.reply_strategy || "-"}`,
    ], "decision-stage")}
    ${stage("安全与画像", [
      `动作：${latest.safety_action || "-"}`,
      `联系人策略：${policySummary(latest.contact_policy)}`,
      `会话画像：${profileSummary(latest.conversation_profile)}`,
      ...(latest.safety_reasons || []).map((item) => `原因：${item}`),
    ], "safety-stage")}
    ${stage("草稿", latest.draft_messages || [], "draft-stage")}
    ${stage("最终发送", latest.final_messages || [], "final-stage")}
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
    <div class="send-item" data-send-id="${escapeHtml(task.send_task_id)}">
      <div class="send-top">
        <strong>${escapeHtml(task.content || "")}</strong>
        <span class="send-status-actions">
          <span class="badge ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
          ${task.status === "failed" ? `<button class="btn retry-btn" data-act="retry-send">重新发送</button>` : ""}
        </span>
      </div>
      <div class="send-meta">${escapeHtml(task.created_at || "")}</div>
      ${task.error_message ? `<div class="send-content">错误：${escapeHtml(task.error_message)}</div>` : ""}
    </div>
  `).join("");
  root.querySelectorAll('[data-act="retry-send"]').forEach((button) => {
    button.onclick = () => retrySendTask(button.closest(".send-item").dataset.sendId);
  });
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

function stage(title, items, className = "") {
  const safeItems = (items || []).filter(Boolean);
  if (!safeItems.length) return "";
  return `<div class="stage ${escapeHtml(className)}"><h4>${escapeHtml(title)}</h4><ul>${safeItems.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul></div>`;
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

function updateHealth(data) {
  const driver = data?.diagnostics?.driver_status || {};
  const current = data?.diagnostics?.current_conversation;
  const targets = data?.targets || [];
  const stoppedWithErrors = targets.filter((target) => target.last_error);
  if (!driver.ok) {
    setHealth(false, "微信连接失败", driver.message || "未完成微信自检");
  } else if (stoppedWithErrors.length) {
    $("health-dot").className = "dot warn";
    $("health-title").textContent = "监听需处理";
    $("health-detail").textContent = `${stoppedWithErrors.length} 个对象异常，点左侧对象查看`;
  } else if (current) {
    setHealth(true, "微信连接正常", `当前：${current.display_name || "-"} · ${targets.length} 个监听对象`);
  } else {
    $("health-dot").className = "dot warn";
    $("health-title").textContent = "微信待确认";
    $("health-detail").textContent = "已找到微信窗口，当前会话未确认";
  }
}

function renderStatusDetail() {
  const root = $("status-detail");
  if (!root || !state.overview) return;
  const diagnostics = state.overview.diagnostics || {};
  const driver = diagnostics.driver_status || {};
  const current = diagnostics.current_conversation;
  const targets = state.overview.targets || [];
  const errors = targets.filter((target) => target.last_error);
  root.innerHTML = `
    ${statusRow("API 服务", "ok", "FastAPI 已响应")}
    ${statusRow("微信 Driver", driver.ok ? "ok" : "failed", driver.message || "-")}
    ${statusRow("当前会话", current ? "ok" : "warning", current?.display_name || "无法读取当前会话身份")}
    ${statusRow("监听对象", errors.length ? "warning" : "ok", `${targets.length} 个，异常 ${errors.length} 个；具体错误见左侧监听列表或详情弹窗`)}
  `;
}

function statusRow(label, status, text) {
  return `
    <div class="status-row">
      <span class="mini-dot ${escapeHtml(status)}"></span>
      <strong>${escapeHtml(label)}</strong>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function explainTargetError(error) {
  const text = String(error || "");
  if (text.includes("search_box") || text.includes("搜索框")) {
    return `${text}。原因：切换会话需要先定位微信左侧搜索框，但当前 UIA locator 没匹配到。请确认微信窗口可见、当前使用的是已验证的 config/wechat_locators.local.json，必要时重新 dump 搜索框控件。`;
  }
  if (text.includes("chat_title") || text.includes("聊天标题") || text.includes("当前聊天标题")) {
    return `${text}。原因：切换会话后系统无法读取右侧聊天标题，不能确认当前会话是不是目标对象。为防串聊，监听会停止。请先手动打开该聊天并重新验证 chat_title/message_list/input_box。`;
  }
  if (text.includes("无法读取当前会话身份")) {
    return `${text}。原因：当前微信右侧没有暴露可验证的聊天标题或输入框名称，系统无法做入库前身份验证。`;
  }
  return text || "-";
}

function shortError(error) {
  const text = explainTargetError(error);
  return text.length > 70 ? `${text.slice(0, 70)}…` : text;
}

function openModal(id) {
  $(id).classList.remove("hidden");
}

function closeModal(id) {
  $(id).classList.add("hidden");
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

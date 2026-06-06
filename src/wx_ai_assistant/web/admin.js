const state = {
  overview: null,
  config: null,
  knowledge: { documents: [], selectedDocumentId: null, contactSettings: null, busy: false, busyText: "" },
  promptExtensions: { extensions: [], selectedId: null },
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
      if (button.dataset.view === "knowledge") loadStrategyKnowledge();
      if (button.dataset.view === "strategy") refreshStrategyPage();
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
  $("new-prompt-extension-btn").addEventListener("click", newPromptExtension);
  $("save-prompt-extension-btn").addEventListener("click", savePromptExtension);
  $("delete-prompt-extension-btn").addEventListener("click", deletePromptExtension);
  $("refresh-strategy-btn").addEventListener("click", loadStrategyKnowledge);
  $("refresh-strategy-page-btn").addEventListener("click", refreshStrategyPage);
  $("upload-knowledge-btn").addEventListener("click", uploadKnowledgeDocument);
  $("save-knowledge-text-btn").addEventListener("click", saveKnowledgeText);
  $("search-knowledge-btn").addEventListener("click", searchKnowledge);
  $("save-contact-knowledge-btn").addEventListener("click", saveContactKnowledgeSettings);
  $("run-strategy-analysis-btn").addEventListener("click", runStrategyAnalysis);
  $("knowledge-contact-select").addEventListener("change", loadContactKnowledgeSettings);
  $("open-targets-btn").addEventListener("click", () => openModal("target-modal"));
  $("close-targets-btn").addEventListener("click", () => closeModal("target-modal"));
  bindModalDismiss("target-modal");
  $("status-card").addEventListener("click", () => {
    renderStatusDetail();
    openModal("status-modal");
  });
  $("close-status-btn").addEventListener("click", () => closeModal("status-modal"));
  bindModalDismiss("status-modal");
}

async function refreshAll() {
  try {
    const overview = await api("/admin-api/overview?limit=80");
    state.overview = overview.data;
    updateHealth(overview.data);
    followBackendActiveTarget(overview.data);
    if (!state.selectedConversationId && overview.data.targets.length) {
      state.selectedConversationId = overview.data.targets[0].conversation.conversation_id;
    }
    renderDesk();
    renderStrategyContactOptions();
  } catch (error) {
    setHealth(false, "连接失败", error.message);
    showError(error.message);
  }
}

async function loadStrategyKnowledge() {
  try {
    const result = await api("/strategy-analysis/documents?limit=100");
    state.knowledge.documents = result.data || [];
    if (!state.knowledge.selectedDocumentId && state.knowledge.documents.length) {
      state.knowledge.selectedDocumentId = state.knowledge.documents[0].document_id;
    }
    renderKnowledgeDocuments();
    renderStrategyContactOptions();
    await loadContactKnowledgeSettings();
  } catch (error) {
    showError(error.message);
  }
}

async function refreshStrategyPage() {
  renderStrategyContactOptions();
  await loadContactKnowledgeSettings();
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
        extra_body: $("cfg-extra-body").value.trim(),
        auto_send_enabled: $("cfg-auto-send-enabled").value === "true",
        proactive_mode: $("cfg-proactive").value,
        max_messages_per_turn: numberOrNull("cfg-max-messages"),
        turn_quiet_seconds: numberOrNull("cfg-quiet"),
        duplicate_guard_seconds: numberOrNull("cfg-duplicate"),
        vision_enabled: $("cfg-vision-enabled").value === "true",
        vision_base_url: $("cfg-vision-base-url").value.trim(),
        vision_api_key: $("cfg-vision-api-key").value.trim() || null,
        vision_model: $("cfg-vision-model").value.trim(),
        vision_temperature: numberOrNull("cfg-vision-temperature"),
        vision_max_tokens: numberOrNull("cfg-vision-max-tokens"),
        vision_timeout_seconds: numberOrNull("cfg-vision-timeout"),
        vision_system_prompt: $("cfg-vision-system-prompt").value,
        vision_extra_body: $("cfg-vision-extra-body").value.trim(),
        speech_enabled: $("cfg-speech-enabled").value === "true",
        speech_base_url: $("cfg-speech-base-url").value.trim(),
        speech_api_key: $("cfg-speech-api-key").value.trim() || null,
        speech_model: $("cfg-speech-model").value.trim(),
        speech_language: $("cfg-speech-language").value.trim(),
        speech_prompt: $("cfg-speech-prompt").value,
        speech_timeout_seconds: numberOrNull("cfg-speech-timeout"),
        core_prompt: $("cfg-core-prompt").value,
        prompt_extensions_json: promptExtensionsJson(),
        langgraph_nodes_json: $("cfg-langgraph-nodes").value,
      },
    });
    $("cfg-api-key").value = "";
    $("cfg-vision-api-key").value = "";
    $("cfg-speech-api-key").value = "";
    showError("配置已保存，重启服务后生效。", false);
  });
}

async function uploadKnowledgeDocument() {
  if (state.knowledge.busy) return;
  const file = $("knowledge-file").files?.[0];
  if (!file) return showKnowledgeUploadResult("请选择要上传的文档。", true);
  setKnowledgeBusy(true, "正在读取文件并上传，随后会解析文档、调用 embedding、写入向量索引。");
  await action(async () => {
    const contentBase64 = await fileToBase64(file);
    showKnowledgeUploadResult("文件已读取，正在解析文档并创建向量索引。大文档可能需要几十秒，请不要重复上传。", false, true);
    const result = await api("/strategy-analysis/documents/upload", {
      method: "POST",
      body: {
        filename: file.name,
        title: $("knowledge-title").value.trim() || null,
        knowledge_type: $("knowledge-type").value,
        tags: selectedKnowledgeTags(),
        content_base64: contentBase64,
      },
    });
    showKnowledgeUploadResult(uploadSummary(result.data), result.data.document.parse_status === "failed");
    $("knowledge-file").value = "";
    $("knowledge-title").value = "";
    await loadStrategyKnowledge();
  }).finally(() => setKnowledgeBusy(false));
}

async function saveKnowledgeText() {
  if (state.knowledge.busy) return;
  const title = $("knowledge-text-title").value.trim();
  const content = $("knowledge-text-content").value.trim();
  if (!title || !content) return showKnowledgeUploadResult("请填写文本标题和内容。", true);
  setKnowledgeBusy(true, "正在保存文本并创建向量索引，请不要重复点击。");
  await action(async () => {
    const result = await api("/strategy-analysis/documents/text", {
      method: "POST",
      body: {
        title,
        content,
        source_type: "text",
        knowledge_type: "默认",
        tags: ["默认"],
      },
    });
    showKnowledgeUploadResult(uploadSummary(result.data), false);
    $("knowledge-text-title").value = "";
    $("knowledge-text-content").value = "";
    await loadStrategyKnowledge();
  }).finally(() => setKnowledgeBusy(false));
}

async function searchKnowledge() {
  const query = $("knowledge-search-query").value.trim();
  if (!query) return showKnowledgeDetail("请输入检索问题。", true);
  await action(async () => {
    const selectedOnly = $("knowledge-search-selected-only")?.checked;
    const documentIds = selectedOnly && state.knowledge.selectedDocumentId ? [state.knowledge.selectedDocumentId] : [];
    const result = await api("/strategy-analysis/knowledge/search", {
      method: "POST",
      body: { query, limit: 8, document_ids: documentIds },
    });
    renderKnowledgeMatches(result.data.matches || [], result.data.vector_entry || null);
  });
}

async function showKnowledgeDocument(id) {
  state.knowledge.selectedDocumentId = id;
  renderKnowledgeDocuments();
  await action(async () => {
    const result = await api(`/strategy-analysis/documents/${encodeURIComponent(id)}`);
    renderKnowledgeChunks(result.data.document, result.data.chunks || []);
  });
}

async function setKnowledgeDocumentEnabled(id, enabled) {
  await action(async () => {
    await api(`/strategy-analysis/documents/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`, { method: "POST" });
    await loadStrategyKnowledge();
  });
}

async function deleteKnowledgeDocument(id) {
  if (!confirm("确定删除这份知识文档？删除后不会再参与检索。")) return;
  await action(async () => {
    await api(`/strategy-analysis/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.knowledge.selectedDocumentId === id) state.knowledge.selectedDocumentId = null;
    await loadStrategyKnowledge();
  });
}

async function rebuildKnowledgeDocument(id) {
  if (state.knowledge.busy) return;
  setKnowledgeBusy(true, "正在重建索引：重新解析文档并调用 embedding。请等待完成。");
  await action(async () => {
    const result = await api(`/strategy-analysis/documents/${encodeURIComponent(id)}/rebuild-index`, { method: "POST" });
    showKnowledgeUploadResult(`已重建索引：${result.data.chunk_count} 个片段。`, false);
    await loadStrategyKnowledge();
  }).finally(() => setKnowledgeBusy(false));
}

async function loadContactKnowledgeSettings() {
  const id = $("knowledge-contact-select")?.value;
  if (!id) return;
  try {
    const result = await api(`/strategy-analysis/contacts/${encodeURIComponent(id)}/settings`);
    state.knowledge.contactSettings = result.data;
    $("knowledge-contact-enabled").value = result.data.enabled ? "true" : "false";
    $("contact-knowledge-result").textContent = result.data.enabled ? "该联系人已启用文档知识库。" : "该联系人未启用文档知识库。";
    $("contact-knowledge-result").className = "contact-config-result";
  } catch (error) {
    showError(error.message);
  }
}

async function saveContactKnowledgeSettings() {
  const id = $("knowledge-contact-select").value;
  if (!id) return showContactKnowledgeResult("请先选择联系人。", true);
  await action(async () => {
    const result = await api(`/strategy-analysis/contacts/${encodeURIComponent(id)}/settings`, {
      method: "POST",
      body: {
        enabled: $("knowledge-contact-enabled").value === "true",
        document_ids: [],
        tag_filters: [],
      },
    });
    showContactKnowledgeResult(result.data.enabled ? "已开启。默认使用全部 active 文档。" : "已关闭。不会影响自动回复。", false);
  });
}

async function runStrategyAnalysis() {
  const id = $("strategy-contact-select").value;
  const userDirection = $("strategy-user-direction").value.trim();
  const instruction = $("strategy-instruction").value.trim() || "分析对方意图、需求、关系信号和回复策略。";
  if (!id) return showStrategyResult("请先选择联系人。", true);
  await action(async () => {
    const result = await api(`/strategy-analysis/conversations/${encodeURIComponent(id)}/analyze`, {
      method: "POST",
      body: { instruction, user_direction: userDirection, message_limit: 120, knowledge_limit: 8 },
    });
    renderStrategyAnalysisResult(result.data);
  });
}

function followBackendActiveTarget(data) {
  const listener = data?.diagnostics?.listener || {};
  const active = listener.processing_conversation_id;
  if (active && listener.processing_reason !== "baseline" && targetById(active)) {
    state.selectedConversationId = active;
    return;
  }
  const activeTurn = data?.diagnostics?.active_ai_turns?.[0];
  if (activeTurn?.conversation_id && targetById(activeTurn.conversation_id)) {
    state.selectedConversationId = activeTurn.conversation_id;
    return;
  }
  const pendingTurn = data?.diagnostics?.pending_ai_turns?.[0];
  if (pendingTurn?.conversation_id && targetById(pendingTurn.conversation_id)) {
    state.selectedConversationId = pendingTurn.conversation_id;
    return;
  }
  const locked = listener.last_locked_conversation_id;
  const lockedIsQueued = (listener.pending_active_ids || []).includes(locked);
  if (locked && lockedIsQueued && targetById(locked)) {
    state.selectedConversationId = locked;
  }
}

function renderDesk() {
  renderTargets();
  renderSideTargets();
  renderMessages();
  renderDecision();
  renderSendTasks();
  renderStatusDetail();
  renderStrategyContactOptions();
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
    item.querySelector('[data-act="select"]').onclick = () => {
      state.selectedConversationId = id;
      renderDesk();
      closeModal("target-modal");
    };
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
  const decisionLogs = (state.overview?.ai_decisions || []).filter((item) => !id || item.conversation_id === id);
  const turnLogs = (state.overview?.diagnostics?.last_ai_turns || []).filter((item) => !id || item.conversation_id === id);
  const decisions = decisionLogs.length ? decisionLogs : turnLogs;
  const activeTurns = (state.overview?.diagnostics?.active_ai_turns || []).filter((item) => !id || item.conversation_id === id);
  const pendingTurns = (state.overview?.diagnostics?.pending_ai_turns || []).filter((item) => !id || item.conversation_id === id);
  const aiErrors = (state.overview?.diagnostics?.last_ai_errors || []).filter((item) => !id || item.conversation_id === id);
  const root = $("decision");
  if (!decisions.length && !activeTurns.length && !pendingTurns.length && !aiErrors.length) {
    root.className = "decision empty";
    root.innerHTML = "暂无决策记录。若刚收到对方消息，会先等待静默时间后再启动 AI。";
    return;
  }
  if (!decisions.length) {
    root.className = "decision";
    root.innerHTML = `
      ${activeTurns.length ? activeTurns.map((turn) => renderActiveTurn(turn)).join("") : ""}
      ${pendingTurns.length ? stage("等待 AI", pendingTurns.map((turn) => `已收到：${turn.trigger_content || "-"}；等待静默 ${turn.age_seconds || 0}s`), "trigger-stage") : ""}
      ${aiErrors.length ? stage("AI 错误", aiErrors.map((error) => `${error.display_name || "-"}：${error.error || "-"}`), "safety-stage") : ""}
    `;
    return;
  }
  const latest = decisions[0];
  root.className = "decision";
  root.innerHTML = `
    ${activeTurns.length ? activeTurns.map((turn) => renderActiveTurn(turn)).join("") : ""}
    ${pendingTurns.length ? stage("等待下一轮", pendingTurns.map((turn) => `已收到：${turn.trigger_content || "-"}；等待静默 ${turn.age_seconds || 0}s`), "trigger-stage") : ""}
    ${aiErrors.length ? stage("最近 AI 错误", aiErrors.slice(0, 2).map((error) => `${error.display_name || "-"}：${error.error || "-"}`), "safety-stage") : ""}
    ${stage("触发消息", triggerItems(latest), "trigger-stage")}
    ${stage("语义判断", [
      `意图：${latest.intent || "-"}`,
      `情绪：${latest.emotion || "-"}`,
      `需求：${latest.user_need || "-"}`,
      `关系信号：${latest.relationship_signal || "-"}`,
      `风险标记：${(latest.risk_flags || []).join("、") || "-"}`,
    ], "analysis-stage")}
    ${stage("安全检查", [
      `动作：${latest.safety_action || "-"}`,
      ...(latest.safety_reasons || []).map((item) => `原因：${item}`),
    ], "safety-stage")}
    ${stage("回复决策", [
      `是否回复：${latest.should_reply ? "是" : "否"}`,
      `不回复原因：${latest.no_reply_reason || "-"}`,
      `策略：${latest.reply_strategy || "-"}`,
      latest.send_suppressed ? "发送状态：自动发送关闭，仅保留 AI 建议" : "",
    ], "decision-stage")}
    ${stage("草稿", latest.draft_messages || latest.parsed_messages || [], "draft-stage")}
    ${stage(latest.send_suppressed ? "最终建议（未发送）" : "最终发送", latest.final_messages || latest.parsed_messages || [], "final-stage")}
  `;
}

function renderActiveTurn(turn) {
  const stageLabel = turn.stage === "draft_ready" ? "草稿已生成，发送前检查新消息" : "AI 思考中";
  return [
    stage("触发消息", triggerItems(turn), "trigger-stage"),
    stage("实时状态", [
      `阶段：${stageLabel}`,
      turn.parsed_messages?.length ? `草稿：${turn.parsed_messages.join(" / ")}` : "",
      turn.done !== undefined ? `本轮完成：${turn.done ? "是" : "否"}` : "",
    ], "analysis-stage"),
  ].join("");
}

function triggerItems(item) {
  const messages = item.trigger_messages || [];
  if (messages.length) {
    return [
      `${item.display_name || "-"}：本轮 ${item.trigger_message_count || messages.length} 条消息`,
      ...messages.map((message, index) => `${index + 1}. ${message}`),
      item.run_id ? `run_id：${item.run_id}` : "",
    ];
  }
  return [`${item.display_name || "-"}：${item.trigger_message || item.trigger_content || "-"}`, item.run_id ? `run_id：${item.run_id}` : ""];
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
  $("cfg-ai-mode").value = config.ai_mode || "";
  $("cfg-base-url").value = config.base_url || "";
  $("cfg-model").value = config.model || "";
  $("cfg-temperature").value = config.temperature ?? "";
  $("cfg-max-tokens").value = config.max_tokens ?? "";
  $("cfg-timeout").value = config.timeout_seconds ?? "";
  $("cfg-extra-body").value = config.extra_body || "";
  $("cfg-auto-send-enabled").value = config.auto_send_enabled ? "true" : "false";
  $("cfg-proactive").value = config.proactive_mode || "off";
  $("cfg-quiet").value = config.turn_quiet_seconds ?? "";
  $("cfg-duplicate").value = config.duplicate_guard_seconds ?? "";
  $("cfg-max-messages").value = config.max_messages_per_turn ?? "";
  $("vision-key-state").textContent = config.vision_api_key_configured ? "Vision Key 已配置" : "Vision Key 未配置";
  $("cfg-vision-enabled").value = config.vision_enabled ? "true" : "false";
  $("cfg-vision-base-url").value = config.vision_base_url || "";
  $("cfg-vision-model").value = config.vision_model || "";
  $("cfg-vision-temperature").value = config.vision_temperature ?? "";
  $("cfg-vision-max-tokens").value = config.vision_max_tokens ?? "";
  $("cfg-vision-timeout").value = config.vision_timeout_seconds ?? "";
  $("cfg-vision-system-prompt").value = config.vision_system_prompt || "";
  $("cfg-vision-extra-body").value = config.vision_extra_body || "";
  $("speech-key-state").textContent = config.speech_api_key_configured ? "Speech Key 已配置" : "Speech Key 未配置";
  $("cfg-speech-enabled").value = config.speech_enabled ? "true" : "false";
  $("cfg-speech-base-url").value = config.speech_base_url || "";
  $("cfg-speech-model").value = config.speech_model || "";
  $("cfg-speech-language").value = config.speech_language || "";
  $("cfg-speech-prompt").value = config.speech_prompt || "";
  $("cfg-speech-timeout").value = config.speech_timeout_seconds ?? "";
  $("cfg-core-prompt").value = config.core_prompt || "";
  loadPromptExtensionsFromJson(config.prompt_extensions_json);
  $("cfg-langgraph-nodes").value = formatJson(config.langgraph_nodes_json);
}

function stage(title, items, className = "") {
  const safeItems = (items || []).filter(Boolean);
  if (!safeItems.length) return "";
  return `<div class="stage ${escapeHtml(className)}"><h4>${escapeHtml(title)}</h4><ul>${safeItems.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul></div>`;
}

function loadPromptExtensionsFromJson(text) {
  const data = parseJsonObject(text);
  const extensions = Array.isArray(data.extensions) ? data.extensions : [];
  state.promptExtensions.extensions = extensions.map((item) => ({
    id: String(item.id || `ext_${Date.now()}_${Math.random().toString(16).slice(2)}`),
    name: String(item.name || "未命名扩展"),
    enabled: item.enabled !== false,
    weight: Number.isFinite(Number(item.weight)) ? Number(item.weight) : 1,
    content: String(item.content || ""),
  }));
  state.promptExtensions.selectedId = state.promptExtensions.extensions[0]?.id || null;
  renderPromptExtensions();
  fillPromptExtensionForm();
}

function renderPromptExtensions() {
  const root = $("prompt-extension-list");
  const extensions = state.promptExtensions.extensions;
  if (!extensions.length) {
    root.className = "prompt-extension-list empty";
    root.innerHTML = "暂无扩展提示词。";
    return;
  }
  root.className = "prompt-extension-list";
  root.innerHTML = extensions.map((item) => {
    const active = item.id === state.promptExtensions.selectedId ? " active" : "";
    return `
      <div class="prompt-extension-item${active}" data-id="${escapeHtml(item.id)}">
        <label class="inline-check">
          <input data-act="toggle" type="checkbox" ${item.enabled ? "checked" : ""} />
          <strong>${escapeHtml(item.name)}</strong>
        </label>
        <input data-act="weight" type="number" min="0" max="5" step="0.1" value="${escapeHtml(String(item.weight))}" />
      </div>
    `;
  }).join("");
  root.querySelectorAll(".prompt-extension-item").forEach((item) => {
    const id = item.dataset.id;
    item.addEventListener("click", (event) => {
      if (event.target?.dataset?.act) return;
      state.promptExtensions.selectedId = id;
      renderPromptExtensions();
      fillPromptExtensionForm();
    });
    item.querySelector('[data-act="toggle"]').addEventListener("change", (event) => {
      promptExtensionById(id).enabled = event.target.checked;
    });
    item.querySelector('[data-act="weight"]').addEventListener("change", (event) => {
      promptExtensionById(id).weight = Number(event.target.value || 1);
      fillPromptExtensionForm();
    });
  });
}

function fillPromptExtensionForm() {
  const item = promptExtensionById(state.promptExtensions.selectedId);
  $("delete-prompt-extension-btn").disabled = !item;
  if (!item) {
    $("prompt-extension-name").value = "";
    $("prompt-extension-weight").value = "1";
    $("prompt-extension-enabled").checked = true;
    $("prompt-extension-content").value = "";
    return;
  }
  $("prompt-extension-name").value = item.name || "";
  $("prompt-extension-weight").value = item.weight ?? 1;
  $("prompt-extension-enabled").checked = item.enabled !== false;
  $("prompt-extension-content").value = item.content || "";
}

function newPromptExtension() {
  const item = {
    id: `ext_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    name: "新的扩展提示词",
    enabled: true,
    weight: 1,
    content: "",
  };
  state.promptExtensions.extensions.push(item);
  state.promptExtensions.selectedId = item.id;
  renderPromptExtensions();
  fillPromptExtensionForm();
}

function savePromptExtension() {
  let item = promptExtensionById(state.promptExtensions.selectedId);
  if (!item) {
    newPromptExtension();
    item = promptExtensionById(state.promptExtensions.selectedId);
  }
  item.name = $("prompt-extension-name").value.trim() || "未命名扩展";
  item.weight = Number($("prompt-extension-weight").value || 1);
  item.enabled = $("prompt-extension-enabled").checked;
  item.content = $("prompt-extension-content").value.trim();
  renderPromptExtensions();
  showError("扩展提示词已更新，点击保存配置后写入文件。", false);
}

function deletePromptExtension() {
  const id = state.promptExtensions.selectedId;
  if (!id) return;
  if (!confirm("确定删除这个扩展提示词？")) return;
  state.promptExtensions.extensions = state.promptExtensions.extensions.filter((item) => item.id !== id);
  state.promptExtensions.selectedId = state.promptExtensions.extensions[0]?.id || null;
  renderPromptExtensions();
  fillPromptExtensionForm();
}

function promptExtensionById(id) {
  return state.promptExtensions.extensions.find((item) => item.id === id);
}

function promptExtensionsJson() {
  const selected = promptExtensionById(state.promptExtensions.selectedId);
  if (selected) {
    selected.name = $("prompt-extension-name").value.trim() || selected.name || "未命名扩展";
    selected.weight = Number($("prompt-extension-weight").value || selected.weight || 1);
    selected.enabled = $("prompt-extension-enabled").checked;
    selected.content = $("prompt-extension-content").value.trim();
  }
  return JSON.stringify({ extensions: state.promptExtensions.extensions }, null, 2);
}

function parseJsonObject(text) {
  try {
    const data = JSON.parse(text || "{}");
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch {
    return {};
  }
}

function renderStrategyContactOptions() {
  ["knowledge-contact-select", "strategy-contact-select"].forEach((id) => {
    const select = $(id);
    if (!select) return;
    const targets = state.overview?.targets || [];
    if (!targets.length) {
      select.innerHTML = `<option value="">暂无监听联系人</option>`;
      return;
    }
    const current = select.value || state.selectedConversationId || targets[0].conversation.conversation_id;
    select.innerHTML = targets.map((target) => {
      const conversationId = target.conversation.conversation_id;
      const selected = conversationId === current ? " selected" : "";
      return `<option value="${escapeHtml(conversationId)}"${selected}>${escapeHtml(target.conversation.display_name)}</option>`;
    }).join("");
  });
}

function renderKnowledgeDocuments() {
  const docs = state.knowledge.documents || [];
  const root = $("knowledge-documents");
  $("knowledge-count").textContent = `${docs.length} 份文档`;
  if (!docs.length) {
    root.className = "knowledge-doc-list empty";
    root.innerHTML = "暂无文档。";
    showKnowledgeDetail("上传文档后可在这里预览命中片段。", true);
    return;
  }
  root.className = "knowledge-doc-list";
  root.innerHTML = docs.map((doc) => {
    const active = doc.document_id === state.knowledge.selectedDocumentId ? " active" : "";
    const statusClass = doc.status === "active" && doc.parse_status === "success" ? "success" : doc.status === "disabled" ? "stopped" : "failed";
    return `
      <div class="knowledge-doc${active}" data-doc-id="${escapeHtml(doc.document_id)}">
        <div class="knowledge-doc-top">
          <strong>${escapeHtml(doc.title)}</strong>
          <span class="badge ${escapeHtml(statusClass)}">${escapeHtml(doc.status)} / ${escapeHtml(doc.parse_status)}</span>
        </div>
        <p>${escapeHtml([doc.source_type, doc.knowledge_type, (doc.tags || []).join("、")].filter(Boolean).join(" · "))}</p>
        ${doc.parse_error ? `<small class="target-error">${escapeHtml(doc.parse_error)}</small>` : ""}
        <div class="knowledge-actions">
          <button class="btn" data-act="view">查看</button>
          <button class="btn" data-act="rebuild" ${state.knowledge.busy ? "disabled" : ""}>重建</button>
          <button class="btn" data-act="${doc.status === "active" ? "disable" : "enable"}" ${state.knowledge.busy ? "disabled" : ""}>${doc.status === "active" ? "禁用" : "启用"}</button>
          <button class="btn danger" data-act="delete" ${state.knowledge.busy ? "disabled" : ""}>删除</button>
        </div>
      </div>
    `;
  }).join("");
  root.querySelectorAll(".knowledge-doc").forEach((item) => {
    const id = item.dataset.docId;
    item.querySelector('[data-act="view"]').onclick = () => showKnowledgeDocument(id);
    item.querySelector('[data-act="rebuild"]').onclick = () => rebuildKnowledgeDocument(id);
    const toggle = item.querySelector('[data-act="disable"], [data-act="enable"]');
    toggle.onclick = () => setKnowledgeDocumentEnabled(id, toggle.dataset.act === "enable");
    item.querySelector('[data-act="delete"]').onclick = () => deleteKnowledgeDocument(id);
  });
}

function renderKnowledgeChunks(document, chunks) {
  if (!chunks.length) {
    showKnowledgeDetail(`${document.title} 暂无可检索片段。`, true);
    return;
  }
  $("knowledge-detail").className = "knowledge-detail";
  $("knowledge-detail").innerHTML = `
    <div class="knowledge-detail-head">
      <strong>${escapeHtml(document.title)}</strong>
      <span>${escapeHtml(document.source_type)} · ${escapeHtml(document.status)} · ${escapeHtml(document.parse_status)}</span>
    </div>
    ${chunks.slice(0, 12).map(renderKnowledgeChunk).join("")}
  `;
}

function renderKnowledgeMatches(matches, vectorEntry = null) {
  if (!matches.length) return showKnowledgeDetail("没有命中文档片段。", true);
  $("knowledge-detail").className = "knowledge-detail";
  const stats = vectorEntry ? `
    <div class="knowledge-vector-stats">
      向量：${escapeHtml(vectorEntry.embedding_model || "-")}
      · 可用 ${Number(vectorEntry.usable_vectors || 0)}
      · 跳过旧模型 ${Number(vectorEntry.skipped_model_mismatch || 0)}
      · 向量命中 ${Number(vectorEntry.vector_hits || 0)}
      · 文档过滤 ${Number(vectorEntry.document_filter_count || 0)}
    </div>
  ` : "";
  $("knowledge-detail").innerHTML = stats + matches.map(renderKnowledgeChunk).join("");
}

function renderKnowledgeChunk(chunk) {
  const source = chunk.source_location || (chunk.source_locations || []).join(", ") || "-";
  const score = formatKnowledgeScore(chunk);
  const typeAndTags = [
    chunk.knowledge_type ? `类型 ${chunk.knowledge_type}` : "",
    (chunk.tags || []).length ? `标签 ${(chunk.tags || []).join("、")}` : "无标签",
  ].filter(Boolean).join(" · ");
  return `
    <div class="knowledge-chunk">
      <div class="knowledge-doc-top">
        <strong>${escapeHtml(chunk.title || "未命名片段")}</strong>
        <span class="muted">${escapeHtml(score)}</span>
      </div>
      <p class="knowledge-source">${escapeHtml(source)} · ${escapeHtml(typeAndTags)}</p>
      <div class="knowledge-preview">${escapeHtml(chunk.chunk_text || "")}</div>
    </div>
  `;
}

function formatKnowledgeScore(chunk) {
  if (!chunk.score_source && Number(chunk.score || 0) === 0) return "未检索";
  const score = Number(chunk.score || 0);
  const vector = Number(chunk.vector_score || 0);
  const lexical = Number(chunk.lexical_score || 0);
  const parts = [`score ${formatScoreValue(score)}`];
  if (chunk.score_source) parts.push(chunk.score_source);
  if (vector > 0) parts.push(`vec ${formatScoreValue(vector)}`);
  if (lexical > 0) parts.push(`lex ${formatScoreValue(lexical)}`);
  return parts.join(" · ");
}

function formatScoreValue(value) {
  if (!Number.isFinite(value)) return "0";
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs >= 0.01) return value.toFixed(3);
  if (abs >= 0.000001) return value.toFixed(6);
  return value.toExponential(2);
}

function renderStrategyAnalysisResult(data) {
  $("strategy-analysis-result").className = "strategy-result";
  $("strategy-analysis-result").innerHTML = `
    ${data.user_direction ? analysisBlock("用户思路", data.user_direction) : ""}
    ${analysisBlock("意图", data.intent)}
    ${analysisBlock("需求", (data.needs || []).join(" / "))}
    ${analysisBlock("关系信号", data.relationship_signal)}
    ${analysisBlock("风险", (data.risks || []).join(" / "))}
    ${analysisBlock("建议策略", data.suggested_strategy)}
    ${analysisBlock("候选回复", (data.reply_examples || []).join("\n"))}
    <h4>知识库命中</h4>
    ${(data.matched_knowledge || []).length ? (data.matched_knowledge || []).map(renderKnowledgeChunk).join("") : "<p class='muted'>无命中片段。</p>"}
  `;
}

function analysisBlock(title, text) {
  return `<h4>${escapeHtml(title)}</h4><p>${escapeHtml(text || "-")}</p>`;
}

function selectedKnowledgeTags() {
  const picked = [...document.querySelectorAll("#knowledge-tag-picks input:checked")].map((item) => item.value);
  const custom = $("knowledge-custom-tags").value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set([...picked, ...custom])];
}

function showKnowledgeUploadResult(message, isError = false, isLoading = false) {
  const root = $("knowledge-upload-result");
  root.className = isError ? "contact-config-result empty" : isLoading ? "contact-config-result loading" : "contact-config-result";
  root.innerHTML = isLoading ? `<span class="inline-spinner"></span><span>${escapeHtml(message)}</span>` : escapeHtml(message);
}

function showKnowledgeDetail(message, isEmpty = false) {
  const root = $("knowledge-detail");
  root.className = isEmpty ? "knowledge-detail empty" : "knowledge-detail";
  root.textContent = message;
}

function showContactKnowledgeResult(message, isError = false) {
  const root = $("contact-knowledge-result");
  root.className = isError ? "contact-config-result empty" : "contact-config-result";
  root.textContent = message;
}

function showStrategyResult(message, isError = false) {
  const root = $("strategy-analysis-result");
  root.className = isError ? "strategy-result empty" : "strategy-result";
  root.textContent = message;
}

function uploadSummary(data) {
  const doc = data.document || {};
  const error = doc.parse_error ? `\n解析提示：${doc.parse_error}` : "";
  return `已保存：${doc.title || "-"}\n片段：${data.chunk_count || 0}\n状态：${doc.status || "-"} / ${doc.parse_status || "-"}${error}`;
}

function setKnowledgeBusy(isBusy, message = "") {
  state.knowledge.busy = isBusy;
  state.knowledge.busyText = isBusy ? message : "";
  const ids = [
    "upload-knowledge-btn",
    "save-knowledge-text-btn",
    "refresh-strategy-btn",
    "knowledge-file",
    "knowledge-title",
    "knowledge-type",
    "knowledge-custom-tags",
    "knowledge-text-title",
    "knowledge-text-content",
  ];
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.disabled = isBusy;
  });
  document.querySelectorAll("#knowledge-tag-picks input").forEach((input) => {
    input.disabled = isBusy;
  });
  const uploadBtn = $("upload-knowledge-btn");
  if (uploadBtn) uploadBtn.innerHTML = isBusy ? `<span class="inline-spinner"></span><span>正在建立索引</span>` : "上传并建立索引";
  const textBtn = $("save-knowledge-text-btn");
  if (textBtn) textBtn.innerHTML = isBusy ? `<span class="inline-spinner"></span><span>正在建立索引</span>` : "保存文本知识";
  if (isBusy && message) showKnowledgeUploadResult(message, false, true);
  renderKnowledgeDocuments();
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

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",").pop() : result);
    };
    reader.onerror = () => reject(reader.error || new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
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

function bindModalDismiss(id) {
  const modal = $(id);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal(id);
  });
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

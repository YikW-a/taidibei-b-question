const askBtn = document.getElementById("askBtn");
const cancelBtn = document.getElementById("cancelBtn");
const resetBtn = document.getElementById("resetBtn");
const closeBtn = document.getElementById("closeBtn");
const bankToggle = document.getElementById("bankToggle");
const questionBankMenu = document.getElementById("questionBankMenu");
const selectedBankBox = document.getElementById("selectedBankBox");
const input = document.getElementById("questionInput");
const answerBox = document.getElementById("answerBox");
const imageBox = document.getElementById("imageBox");
const statusText = document.getElementById("statusText");
const sessionBadge = document.getElementById("sessionBadge");
const copyBtn = document.getElementById("copyBtn");
const exportMdBtn = document.getElementById("exportMdBtn");
const exportJsonBtn = document.getElementById("exportJsonBtn");
const imageModal = document.getElementById("imageModal");
const modalImage = document.getElementById("modalImage");
const modalClose = document.getElementById("modalClose");
const promptChips = Array.from(document.querySelectorAll(".prompt-chip"));

const storageKey = "financial_qa_session_id";
const thinkingSteps = ["解析问题意图", "规划数据库查询", "检索研报证据", "融合财务与文本证据", "复核并组织回答"];
let sessionId = localStorage.getItem(storageKey) || crypto.randomUUID();
let pendingTimer = null;
let pendingStartedAt = 0;
let questionBankItems = [];
let selectedBankItem = null;
let lastPayload = null;
let activeController = null;
let cancelRequested = false;

localStorage.setItem(storageKey, sessionId);
sessionBadge.textContent = `会话 ${sessionId.slice(0, 8)}`;
setAnswerToolState(false);

function setBusy(isBusy, text) {
  document.body.classList.toggle("is-busy", isBusy);
  askBtn.disabled = isBusy;
  cancelBtn.disabled = !isBusy;
  resetBtn.disabled = isBusy;
  closeBtn.disabled = isBusy;
  bankToggle.disabled = isBusy;
  promptChips.forEach((button) => {
    button.disabled = isBusy;
  });
  selectedBankBox.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
  statusText.textContent = text;
}

function setAnswerToolState(hasAnswer) {
  copyBtn.disabled = !hasAnswer;
  exportMdBtn.disabled = !hasAnswer;
  exportJsonBtn.disabled = !hasAnswer;
}

function startPendingTimer() {
  stopPendingTimer();
  pendingStartedAt = Date.now();
  const update = () => {
    const seconds = Math.max(0, Math.floor((Date.now() - pendingStartedAt) / 1000));
    const step = thinkingSteps[Math.min(thinkingSteps.length - 1, Math.floor(seconds / 4))];
    statusText.textContent = `${step}中，请稍候... 已等待 ${seconds} 秒`;
  };
  update();
  pendingTimer = window.setInterval(update, 1000);
}

function stopPendingTimer() {
  if (pendingTimer !== null) {
    window.clearInterval(pendingTimer);
    pendingTimer = null;
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderAnswerMarkdown(value) {
  const escaped = escapeHtml(value || "暂无回答。");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^\s*[-*]\s+(.+)$/gm, "<div class=\"answer-list-item\">• $1</div>")
    .replace(/^\s*(\d+)[.、]\s+(.+)$/gm, "<div class=\"answer-list-item\">$1. $2</div>")
    .replace(/\n/g, "<br>");
}

function basenameFromPath(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return text.split(/[\\/]/).filter(Boolean).pop() || text;
}

function closestFromEvent(event, selector) {
  return event.target instanceof Element ? event.target.closest(selector) : null;
}

function renderTurns(turns) {
  if (!turns.length) {
    answerBox.className = "answer-box empty";
    answerBox.textContent = "回答会显示在这里。";
    setAnswerToolState(false);
    return;
  }
  answerBox.className = "answer-box";
  answerBox.innerHTML = turns
    .map((turn, index) => {
      const question = escapeHtml(turn.Q || `第 ${index + 1} 轮`);
      const content = renderAnswerMarkdown(turn.A?.content || "暂无回答。");
      const elapsed = turn.elapsed_seconds ? `<span class="turn-time">回答时间：${escapeHtml(turn.elapsed_seconds)} 秒</span>` : "";
      const references = renderInlineReferences(turn.A?.references || []);
      const quality = renderQualityHints(turn);
      return `
        <article class="turn">
          <div class="turn-question">
            <span class="turn-label">问题 ${index + 1}</span>
            <span class="turn-question-text">${question}</span>
            ${elapsed}
          </div>
          ${quality}
          <div class="turn-answer">${content}</div>
          ${references}
        </article>
      `;
    })
    .join("");
  answerBox.scrollTop = answerBox.scrollHeight;
  setAnswerToolState(true);
}

function renderQualityHints(turn) {
  const content = String(turn.A?.content || "").trim();
  const references = turn.A?.references || [];
  const images = turn.A?.image || [];
  const hints = [];
  hints.push(content.length >= 120 ? "回答较完整" : "简要回答");
  hints.push(references.length ? `研报引用 ${references.length} 条` : "无研报引用");
  if (images.length) {
    hints.push(`生成图表 ${images.length} 张`);
  }
  if (/\d/.test(content)) {
    hints.push("含数值信息");
  }
  return `
    <div class="quality-hints" aria-label="回答质量提示">
      ${hints.map((hint) => `<span>${escapeHtml(hint)}</span>`).join("")}
    </div>
  `;
}

function renderInlineReferences(references) {
  if (!references.length) {
    return "";
  }
  return `
    <div class="turn-references">
      <div class="turn-references-title">引用依据</div>
      ${references
        .map((ref, index) => {
          const title = escapeHtml(basenameFromPath(ref.paper_path || ""));
          const image = escapeHtml(ref.paper_image || "");
          const text = escapeHtml(ref.text || "");
          const imageRow = image
            ? `<div class="reference-row"><span>引用图表：</span><strong>${image}</strong></div>`
            : "";
          const detail = text
            ? `<details class="reference-detail"><summary>查看引用原文</summary><p>${text}</p></details>`
            : "";
          return `
            <article class="turn-reference-item">
              <div class="reference-index">引用 ${index + 1}</div>
              <div class="reference-row"><span>研报标题：</span><strong>${title || "未提供"}</strong></div>
              ${imageRow}
              ${detail}
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderImages(images) {
  if (!images.length) {
    imageBox.className = "image-box empty";
    imageBox.textContent = "如果本轮生成图片，会在这里展示。";
    return;
  }
  imageBox.className = "image-box";
  imageBox.innerHTML = `
    <div class="image-grid">
      ${images
        .map((src, index) => {
          const safeSrc = escapeHtml(src);
          return `
            <figure class="image-card">
              <button class="image-preview" type="button" data-src="${safeSrc}" title="查看大图" aria-label="查看生成图表 ${index + 1}">
                <img src="${safeSrc}" alt="生成图表 ${index + 1}" />
              </button>
              <figcaption>生成图表 ${index + 1}</figcaption>
            </figure>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderQuestionBank(items) {
  if (!items.length) {
    questionBankMenu.innerHTML = "<div class=\"bank-loading\">题库为空</div>";
    return;
  }
  questionBankMenu.innerHTML = `
    <div class="bank-menu-title">
      <span>第三问题库</span>
      <span id="bankCount" class="bank-count"></span>
    </div>
    <label class="bank-search-wrap">
      <span>筛选</span>
      <input id="bankSearch" class="bank-search" type="search" placeholder="输入题号、类型或关键词" autocomplete="off" />
    </label>
    <div id="bankMenuList" class="bank-menu-list"></div>
  `;
  updateQuestionBankList("");
}

function updateQuestionBankList(query) {
  const normalized = String(query || "").trim().toLowerCase();
  const filtered = questionBankItems.filter((item) => {
    const haystack = `${item.id || ""} ${item.type || ""} ${item.display || ""} ${(item.questions || []).join(" ")}`.toLowerCase();
    return !normalized || haystack.includes(normalized);
  });
  const bankCount = document.getElementById("bankCount");
  const bankMenuList = document.getElementById("bankMenuList");
  if (bankCount) {
    bankCount.textContent = `${filtered.length}/${questionBankItems.length}`;
  }
  if (!bankMenuList) {
    return;
  }
  if (!filtered.length) {
    bankMenuList.innerHTML = "<div class=\"bank-loading\">没有匹配的问题</div>";
    return;
  }
  bankMenuList.innerHTML = filtered
    .map((item) => {
      const firstQuestion = escapeHtml(item.questions?.[0] || item.display || "");
      return `
        <button class="bank-item" type="button" role="menuitem" data-id="${escapeHtml(item.id)}">
          <span class="bank-id">${escapeHtml(item.id)}</span>
          <span class="bank-type">${escapeHtml(item.type || "任务三")}</span>
          <span class="bank-question">${firstQuestion}</span>
        </button>
      `;
    })
    .join("");
}

function renderSelectedBank(item) {
  if (!item) {
    selectedBankBox.hidden = true;
    selectedBankBox.innerHTML = "";
    return;
  }
  const questions = item.questions || [];
  selectedBankBox.hidden = false;
  selectedBankBox.innerHTML = `
    <div class="selected-bank-heading">
      <span>已选择 ${escapeHtml(item.id)} · ${escapeHtml(item.type || "任务三")}</span>
      <button class="selected-bank-clear" type="button" title="取消选择" aria-label="取消选择">×</button>
    </div>
    <button class="bank-auto-run" type="button">顺序执行本题 ${questions.length} 问</button>
    <div class="bank-turn-list">
      ${questions
        .map(
          (question, index) => `
            <button class="bank-turn-chip" type="button" data-turn-index="${index}">
              第 ${index + 1} 问：${escapeHtml(question)}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

async function loadQuestionBank() {
  try {
    const response = await fetch("/api/question-bank");
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "题库加载失败");
    }
    questionBankItems = payload.items || [];
    renderQuestionBank(questionBankItems);
  } catch (error) {
    questionBankMenu.innerHTML = `<div class="bank-loading">题库加载失败：${escapeHtml(error.message)}</div>`;
  }
}

async function selectBankQuestion(questionId) {
  const item = questionBankItems.find((candidate) => candidate.id === questionId);
  if (!item) {
    return;
  }
  selectedBankItem = item;
  await resetSession({ preserveBank: true, silent: true });
  selectedBankItem = item;
  renderSelectedBank(item);
  input.value = item.questions?.[0] || item.display || "";
  input.focus();
  statusText.textContent = `已载入 ${item.id}，可直接发送首问；后续追问可点击题组按钮填入。`;
}

async function askQuestion() {
  const question = input.value.trim();
  if (!question) {
    input.focus();
    return;
  }
  cancelRequested = false;
  setBusy(true, "正在调用任务三后端生成回答...");
  startPendingTimer();
  try {
    const payload = await requestAnswer(question);
    applyAnswerPayload(payload);
    input.value = "";
    stopPendingTimer();
    const elapsedText = payload.elapsed_seconds ? `，用时 ${payload.elapsed_seconds} 秒` : "";
    setBusy(false, payload.status === "ok" ? `回答完成${elapsedText}` : `状态：${payload.status}${elapsedText}`);
  } catch (error) {
    stopPendingTimer();
    if (cancelRequested || error.name === "AbortError") {
      setBusy(false, "已取消生成");
      return;
    }
    showError(error);
  }
}

async function requestAnswer(question) {
  activeController = new AbortController();
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
      signal: activeController.signal,
    });
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "请求失败");
    }
    return payload;
  } finally {
    activeController = null;
  }
}

function applyAnswerPayload(payload) {
  const renderedTurns = payload.turns || [];
  if (renderedTurns.length && payload.elapsed_seconds) {
    renderedTurns[renderedTurns.length - 1].elapsed_seconds = payload.elapsed_seconds;
  }
  lastPayload = { ...payload, turns: renderedTurns };
  renderTurns(renderedTurns);
  renderImages(payload.latest?.A?.image || []);
}

function showError(error) {
  setBusy(false, "请求失败");
  answerBox.className = "answer-box";
  answerBox.innerHTML = `<div class="turn-answer">运行出错：${escapeHtml(error.message)}</div>`;
}

async function cancelGeneration() {
  cancelRequested = true;
  cancelBtn.disabled = true;
  statusText.textContent = "正在取消生成，当前计算步骤结束后停止...";
  await fetch("/api/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    keepalive: true,
  }).catch(() => {});
}

async function runSelectedBankQuestion() {
  if (!selectedBankItem?.questions?.length) {
    return;
  }
  const item = selectedBankItem;
  await resetSession({ preserveBank: true, silent: true });
  selectedBankItem = item;
  renderSelectedBank(item);
  cancelRequested = false;
  setBusy(true, `正在顺序执行 ${item.id}...`);
  startPendingTimer();
  try {
    for (let index = 0; index < item.questions.length; index += 1) {
      if (cancelRequested) {
        break;
      }
      const question = item.questions[index];
      statusText.textContent = `正在顺序执行 ${item.id}：第 ${index + 1}/${item.questions.length} 问`;
      const payload = await requestAnswer(question);
      applyAnswerPayload(payload);
    }
    stopPendingTimer();
    input.value = "";
    setBusy(false, cancelRequested ? "已取消题组执行" : `${item.id} 已顺序执行完成`);
  } catch (error) {
    stopPendingTimer();
    if (cancelRequested || error.name === "AbortError") {
      setBusy(false, "已取消题组执行");
      return;
    }
    showError(error);
  }
}

async function resetSession(options = {}) {
  stopPendingTimer();
  setBusy(true, "正在清空会话...");
  try {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } finally {
    sessionId = crypto.randomUUID();
    localStorage.setItem(storageKey, sessionId);
    sessionBadge.textContent = `会话 ${sessionId.slice(0, 8)}`;
    lastPayload = null;
    renderTurns([]);
    renderImages([]);
    if (!options.preserveBank) {
      selectedBankItem = null;
      renderSelectedBank(null);
    }
    setBusy(false, options.silent ? "已开启独立题库会话" : "已开启新会话");
  }
}

function answerToMarkdown(payload) {
  const turns = payload?.turns || [];
  if (!turns.length) {
    return "";
  }
  return turns
    .map((turn, index) => {
      const references = turn.A?.references || [];
      const refText = references
        .map((ref, refIndex) => {
          const title = basenameFromPath(ref.paper_path || "") || "未提供";
          const image = ref.paper_image ? `\n- 引用图表：${ref.paper_image}` : "";
          const quote = ref.text ? `\n- 引用原文：${ref.text}` : "";
          return `引用 ${refIndex + 1}\n- 研报标题：${title}${image}${quote}`;
        })
        .join("\n\n");
      return `## 第 ${index + 1} 轮\n\n**问题：** ${turn.Q || ""}\n\n**回答：**\n${turn.A?.content || ""}${refText ? `\n\n**引用依据：**\n${refText}` : ""}`;
    })
    .join("\n\n");
}

function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function copyLatestAnswer() {
  const turns = lastPayload?.turns || [];
  const latest = turns.length ? turns[turns.length - 1] : null;
  if (!latest) {
    return;
  }
  const text = `问题：${latest.Q || ""}\n\n回答：\n${latest.A?.content || ""}`;
  try {
    await navigator.clipboard.writeText(text);
    statusText.textContent = "最新回答已复制";
  } catch {
    const helper = document.createElement("textarea");
    helper.value = text;
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
    statusText.textContent = "最新回答已复制";
  }
}

function exportMarkdown() {
  const markdown = answerToMarkdown(lastPayload);
  if (markdown) {
    downloadBlob(`智能问数助手_${sessionId.slice(0, 8)}.md`, markdown, "text/markdown;charset=utf-8");
  }
}

function exportJson() {
  if (lastPayload) {
    downloadBlob(
      `智能问数助手_${sessionId.slice(0, 8)}.json`,
      JSON.stringify(lastPayload, null, 2),
      "application/json;charset=utf-8",
    );
  }
}

function openImageModal(src) {
  modalImage.src = src;
  imageModal.hidden = false;
  modalClose.focus();
}

function closeImageModal() {
  imageModal.hidden = true;
  modalImage.removeAttribute("src");
}

function requestShutdown(useBeacon = false) {
  const body = JSON.stringify({ session_id: sessionId });
  if (useBeacon && navigator.sendBeacon) {
    const blob = new Blob([body], { type: "application/json" });
    navigator.sendBeacon("/api/shutdown", blob);
    return;
  }
  fetch("/api/shutdown", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {});
}

function sendHeartbeat() {
  fetch("/api/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    keepalive: true,
  }).catch(() => {});
}

async function closeAssistant() {
  stopPendingTimer();
  setBusy(true, "正在关闭服务...");
  requestShutdown(false);
  document.body.innerHTML = `
    <main class="shutdown-screen">
      <h1>服务已关闭</h1>
      <p>可以直接关闭这个浏览器标签页。</p>
    </main>
  `;
}

askBtn.addEventListener("click", askQuestion);
cancelBtn.addEventListener("click", cancelGeneration);
resetBtn.addEventListener("click", () => resetSession());
closeBtn.addEventListener("click", closeAssistant);
copyBtn.addEventListener("click", copyLatestAnswer);
exportMdBtn.addEventListener("click", exportMarkdown);
exportJsonBtn.addEventListener("click", exportJson);
modalClose.addEventListener("click", closeImageModal);
imageModal.addEventListener("click", (event) => {
  if (event.target === imageModal) {
    closeImageModal();
  }
});

bankToggle.addEventListener("mouseenter", () => {
  bankToggle.setAttribute("aria-expanded", "true");
});
bankToggle.addEventListener("focus", () => {
  bankToggle.setAttribute("aria-expanded", "true");
});
questionBankMenu.addEventListener("mouseleave", () => {
  bankToggle.setAttribute("aria-expanded", "false");
});
questionBankMenu.addEventListener("click", (event) => {
  const target = closestFromEvent(event, ".bank-item");
  if (!target) {
    return;
  }
  selectBankQuestion(target.dataset.id);
  bankToggle.setAttribute("aria-expanded", "false");
});
questionBankMenu.addEventListener("input", (event) => {
  const target = closestFromEvent(event, ".bank-search");
  if (target) {
    updateQuestionBankList(target.value);
  }
});

selectedBankBox.addEventListener("click", (event) => {
  const autoRun = closestFromEvent(event, ".bank-auto-run");
  if (autoRun) {
    runSelectedBankQuestion();
    return;
  }
  const clear = closestFromEvent(event, ".selected-bank-clear");
  if (clear) {
    selectedBankItem = null;
    renderSelectedBank(null);
    statusText.textContent = "已取消题库选择";
    return;
  }
  const chip = closestFromEvent(event, ".bank-turn-chip");
  if (!chip || !selectedBankItem) {
    return;
  }
  const index = Number(chip.dataset.turnIndex || 0);
  input.value = selectedBankItem.questions?.[index] || "";
  input.focus();
});

promptChips.forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.question || "";
    input.focus();
  });
});

imageBox.addEventListener("click", (event) => {
  const target = closestFromEvent(event, ".image-preview");
  if (target?.dataset.src) {
    openImageModal(target.dataset.src);
  }
});

input.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    askQuestion();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !imageModal.hidden) {
    closeImageModal();
  }
});

loadQuestionBank();
sendHeartbeat();
setInterval(sendHeartbeat, 5000);

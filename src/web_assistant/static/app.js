const askBtn = document.getElementById("askBtn");
const resetBtn = document.getElementById("resetBtn");
const closeBtn = document.getElementById("closeBtn");
const input = document.getElementById("questionInput");
const answerBox = document.getElementById("answerBox");
const imageBox = document.getElementById("imageBox");
const statusText = document.getElementById("statusText");
const sessionBadge = document.getElementById("sessionBadge");

const storageKey = "financial_qa_session_id";
let sessionId = localStorage.getItem(storageKey) || crypto.randomUUID();
localStorage.setItem(storageKey, sessionId);
sessionBadge.textContent = `会话 ${sessionId.slice(0, 8)}`;
let pendingTimer = null;
let pendingStartedAt = 0;

function setBusy(isBusy, text) {
  askBtn.disabled = isBusy;
  resetBtn.disabled = isBusy;
  closeBtn.disabled = isBusy;
  statusText.textContent = text;
}

function startPendingTimer() {
  stopPendingTimer();
  pendingStartedAt = Date.now();
  const update = () => {
    const seconds = Math.max(0, Math.floor((Date.now() - pendingStartedAt) / 1000));
    statusText.textContent = `正在生成回答，请稍候… 已等待 ${seconds} 秒`;
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

function renderTurns(turns) {
  if (!turns.length) {
    answerBox.className = "answer-box empty";
    answerBox.textContent = "回答会显示在这里。";
    return;
  }
  answerBox.className = "answer-box";
  answerBox.innerHTML = turns
    .map((turn, index) => {
      const question = escapeHtml(turn.Q || `第 ${index + 1} 轮`);
      const content = renderAnswerMarkdown(turn.A?.content || "暂无回答。");
      const elapsed = turn.elapsed_seconds ? `<span class="turn-time">回答时间：${escapeHtml(turn.elapsed_seconds)} 秒</span>` : "";
      const references = renderInlineReferences(turn.A?.references || []);
      return `
        <article class="turn">
          <div class="turn-question"><span>Q${index + 1}: ${question}</span>${elapsed}</div>
          <div class="turn-answer">${content}</div>
          ${references}
        </article>
      `;
    })
    .join("");
  answerBox.scrollTop = answerBox.scrollHeight;
}

function renderInlineReferences(references) {
  if (!references.length) {
    return "";
  }
  return `
    <div class="turn-references">
      <div class="turn-references-title">引用</div>
      ${references
        .map((ref, index) => {
          const title = escapeHtml(basenameFromPath(ref.paper_path || ""));
          const image = escapeHtml(ref.paper_image || "");
          const imageRow = image
            ? `<div class="reference-row"><span>引用图表：</span><strong>${image}</strong></div>`
            : "";
          return `
            <article class="turn-reference-item">
              <div class="reference-index">引用 ${index + 1}</div>
              <div class="reference-row"><span>研报标题：</span><strong>${title || "未提供"}</strong></div>
              ${imageRow}
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
              <img src="${safeSrc}" alt="生成图表 ${index + 1}" />
              <figcaption>生成图表 ${index + 1}</figcaption>
            </figure>
          `;
        })
        .join("")}
    </div>
  `;
}

async function askQuestion() {
  const question = input.value.trim();
  if (!question) {
    input.focus();
    return;
  }
  setBusy(true, "正在调用任务三后端生成回答...");
  startPendingTimer();
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) {
      throw new Error(payload.error || "请求失败");
    }
    const renderedTurns = payload.turns || [];
    if (renderedTurns.length && payload.elapsed_seconds) {
      renderedTurns[renderedTurns.length - 1].elapsed_seconds = payload.elapsed_seconds;
    }
    renderTurns(renderedTurns);
    renderImages(payload.latest?.A?.image || []);
    input.value = "";
    stopPendingTimer();
    const elapsedText = payload.elapsed_seconds ? `，用时 ${payload.elapsed_seconds} 秒` : "";
    setBusy(false, payload.status === "ok" ? `回答完成${elapsedText}` : `状态：${payload.status}${elapsedText}`);
  } catch (error) {
    stopPendingTimer();
    setBusy(false, "请求失败");
    answerBox.className = "answer-box";
    answerBox.innerHTML = `<div class="turn-answer">运行出错：${escapeHtml(error.message)}</div>`;
  }
}

async function resetSession() {
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
    renderTurns([]);
    renderImages([]);
    setBusy(false, "已开启新会话");
  }
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
resetBtn.addEventListener("click", resetSession);
closeBtn.addEventListener("click", closeAssistant);
input.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    askQuestion();
  }
});

sendHeartbeat();
setInterval(sendHeartbeat, 5000);

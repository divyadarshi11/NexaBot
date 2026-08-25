/* chatbot — front end.
   Talks to the Flask API in web.py. Replies arrive as SSE and are painted as
   raw text while streaming, then re-rendered as Markdown once the turn closes
   (parsing half-finished Markdown makes the page jump around). */

const $ = (id) => document.getElementById(id);

const els = {
  log: $("log"),
  empty: $("empty"),
  scroller: $("scroller"),
  input: $("input"),
  send: $("send"),
  banner: $("banner"),
  sessions: $("session-list"),
  sessionsEmpty: $("sessions-empty"),
  model: $("topbar-model"),
  turns: $("topbar-turns"),
  fModel: $("f-model"),
  fTokens: $("f-tokens"),
  fSystem: $("f-system"),
};

let turnCount = 0;
let busy = false;

/* ── helpers ─────────────────────────────────────────────────────────── */

const pad = (n) => String(n).padStart(2, "0");

function renderMarkdown(text) {
  if (window.marked) {
    return window.marked.parse(text, { breaks: true, gfm: true });
  }
  const escaped = text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  return `<p style="white-space:pre-wrap">${escaped}</p>`;
}

function notify(message, isError = false) {
  els.banner.textContent = message;
  els.banner.classList.toggle("is-error", isError);
  els.banner.hidden = false;
  if (!isError) setTimeout(() => { els.banner.hidden = true; }, 4000);
}

function scrollToEnd() {
  els.scroller.scrollTop = els.scroller.scrollHeight;
}

function setBusy(state) {
  busy = state;
  els.send.disabled = state;
  els.send.textContent = state ? "Working…" : "Send";
}

function updateHeader(session) {
  els.model.textContent = session.model;
  const asked = session.messages.filter((m) => m.role === "user").length;
  els.turns.textContent = asked === 1 ? "1 turn" : `${asked} turns`;
}

/* ── the ledger ──────────────────────────────────────────────────────── */

function addTurn(question) {
  els.empty.hidden = true;
  turnCount += 1;

  const turn = document.createElement("article");
  turn.className = "turn";
  turn.innerHTML = `
    <div class="turn-num">${pad(turnCount)}</div>
    <div class="turn-body">
      <div class="ask"></div>
      <div class="reply streaming"></div>
      <div class="turn-meta"></div>
    </div>`;
  turn.querySelector(".ask").textContent = question;
  els.log.appendChild(turn);

  return {
    reply: turn.querySelector(".reply"),
    meta: turn.querySelector(".turn-meta"),
  };
}

function paintStreaming(node, text) {
  node.textContent = text;
  node.appendChild(document.createElement("span")).className = "cursor";
}

function closeTurn(node, text) {
  node.classList.remove("streaming");
  node.innerHTML = renderMarkdown(text);
  node.querySelectorAll("a").forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
}

/* ── sending ─────────────────────────────────────────────────────────── */

async function send() {
  const question = els.input.value.trim();
  if (!question || busy) return;

  els.input.value = "";
  els.input.style.height = "auto";
  els.banner.hidden = true;
  setBusy(true);

  const { reply, meta } = addTurn(question);
  meta.textContent = "waiting for first token…";
  paintStreaming(reply, "");
  scrollToEnd();

  let full = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
    });

    if (!response.ok || !response.body) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || `Request failed (${response.status}).`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const payload = JSON.parse(line.slice(6));

        if (payload.text !== undefined) {
          full += payload.text;
          paintStreaming(reply, full);
          scrollToEnd();
        } else if (payload.error) {
          throw new Error(payload.error);
        } else if (payload.done) {
          closeTurn(reply, full);
          meta.textContent = `${payload.done.model} · ${payload.done.seconds}s`;
        }
      }
    }
  } catch (error) {
    closeTurn(reply, full);
    meta.classList.add("is-error");
    meta.textContent = error.message;
  } finally {
    setBusy(false);
    els.input.focus();
    refreshState();
    scrollToEnd();
  }
}

/* ── transcripts ─────────────────────────────────────────────────────── */

function rebuildLog(messages) {
  els.log.querySelectorAll(".turn").forEach((n) => n.remove());
  turnCount = 0;

  for (let i = 0; i < messages.length; i += 1) {
    if (messages[i].role !== "user") continue;
    const answer = messages[i + 1] && messages[i + 1].role === "assistant"
      ? messages[i + 1].content
      : "";
    const { reply, meta } = addTurn(messages[i].content);
    closeTurn(reply, answer);
    meta.textContent = "restored from transcript";
  }

  els.empty.hidden = messages.length > 0;
  scrollToEnd();
}

async function refreshSessions() {
  const data = await fetch("/api/sessions").then((r) => r.json());
  els.sessions.innerHTML = "";
  els.sessionsEmpty.hidden = data.sessions.length > 0;

  for (const item of data.sessions) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.className = "session-btn";
    button.type = "button";
    button.innerHTML = `<span class="session-name"></span><span class="session-preview"></span>`;
    button.querySelector(".session-name").textContent =
      `${item.name} · ${item.turns} turn${item.turns === 1 ? "" : "s"}`;
    button.querySelector(".session-preview").textContent = item.preview;
    button.addEventListener("click", () => loadSession(item.path));
    li.appendChild(button);
    els.sessions.appendChild(li);
  }
}

async function loadSession(path) {
  const data = await fetch("/api/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  }).then((r) => r.json());

  if (data.error) return notify(data.error, true);
  applySession(data.session);
  rebuildLog(data.session.messages);
  notify("Transcript loaded.");
}

function applySession(session) {
  els.fModel.value = session.model;
  els.fTokens.value = session.max_tokens;
  els.fSystem.value = session.system_prompt;
  updateHeader(session);
}

async function refreshState() {
  const data = await fetch("/api/state").then((r) => r.json());
  if (!data.ok) return notify(data.error, true);
  applySession(data.session);
  return data.session;
}

/* ── wiring ──────────────────────────────────────────────────────────── */

els.send.addEventListener("click", send);

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});

els.input.addEventListener("input", () => {
  els.input.style.height = "auto";
  els.input.style.height = `${els.input.scrollHeight}px`;
});

$("new-chat").addEventListener("click", async () => {
  const data = await fetch("/api/new", { method: "POST" }).then((r) => r.json());
  applySession(data.session);
  rebuildLog([]);
  els.input.focus();
});

$("save-chat").addEventListener("click", async () => {
  const data = await fetch("/api/save", { method: "POST" }).then((r) => r.json());
  if (data.error) return notify(data.error, true);
  notify(`Saved to ${data.path}`);
  refreshSessions();
});

$("save-settings").addEventListener("click", async () => {
  const data = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: els.fModel.value,
      max_tokens: Number(els.fTokens.value),
      system_prompt: els.fSystem.value,
    }),
  }).then((r) => r.json());

  if (data.error) return notify(data.error, true);
  applySession(data.session);
  notify("Settings applied.");
});

(async function init() {
  const session = await refreshState();
  if (session) rebuildLog(session.messages);
  await refreshSessions();
  els.input.focus();
})();

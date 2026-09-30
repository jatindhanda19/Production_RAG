// /api/* is proxied to the FastAPI app (serve.py in dev, nginx in Docker); it has no CORS middleware
const API = "/api";

const $ = (id) => document.getElementById(id);

const chatEl = $("chat");
const messagesEl = $("messages");
const emptyEl = $("empty");
const form = $("composer");
const input = $("input");
const sendBtn = $("send");

let threadId = newThreadId();
let busy = false;

function newThreadId() {
  return "web-" + Math.random().toString(36).slice(2, 10);
}

// ---------- API ----------

async function api(path, options) {
  let res;
  try {
    res = await fetch(API + path, options);
  } catch {
    throw { status: 0, data: null };
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON body; the status code is enough
  }
  if (!res.ok) throw { status: res.status, data };
  return data;
}

function describeError(err) {
  const detail = err.data && err.data.detail;
  switch (err.status) {
    case 0:
      return ["Can't reach the server", "Check your connection, then try again."];
    case 400:
      return ["Blocked by security filters", "This message matched a prompt-injection pattern and was not sent to the model."];
    case 422: {
      const msg = Array.isArray(detail) && detail[0] ? detail[0].msg : "The message was not accepted.";
      return ["Message rejected", msg];
    }
    case 429:
      return ["Rate limit reached", "Too many messages in the last minute. Wait a moment and try again."];
    case 502:
    case 503:
    case 504:
      return ["Can't reach the API", "The API isn't responding. Check that it is running, then try again."];
    default:
      return ["Something went wrong", typeof detail === "string" ? detail : `The API returned status ${err.status}.`];
  }
}

// ---------- Markdown (escapes everything, then adds a small safe subset) ----------

function esc(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function inline(raw) {
  const codes = [];
  let s = raw.replace(/`([^`]+)`/g, (_, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = esc(s)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[i])}</code>`);
}

const tableCells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const isTableRule = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line || "");

function renderBlocks(text) {
  const lines = text.split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      out.push(`<h4>${inline(heading[1])}</h4>`);
      i++;
      continue;
    }

    if (line.includes("|") && isTableRule(lines[i + 1])) {
      const head = tableCells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|")) rows.push(tableCells(lines[i++]));
      out.push(
        '<div class="table-wrap"><table><thead><tr>' +
        head.map((c) => `<th>${inline(c)}</th>`).join("") +
        "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
        "</tbody></table></div>"
      );
      continue;
    }

    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    const marker = bullet.test(line) ? bullet : numbered.test(line) ? numbered : null;
    if (marker) {
      const items = [];
      while (i < lines.length && marker.test(lines[i])) items.push(lines[i++].replace(marker, ""));
      const tag = marker === bullet ? "ul" : "ol";
      out.push(`<${tag}>` + items.map((it) => `<li>${inline(it)}</li>`).join("") + `</${tag}>`);
      continue;
    }

    const para = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^#{1,6}\s/.test(lines[i]) && !bullet.test(lines[i]) && !numbered.test(lines[i])
    ) para.push(lines[i++]);
    out.push(`<p>${para.map(inline).join("<br>")}</p>`);
  }

  return out.join("");
}

function renderMarkdown(src) {
  // Odd segments are the insides of ``` fences
  return src.split(/```/).map((part, idx) => {
    if (idx % 2 === 0) return renderBlocks(part);
    const code = part.replace(/^[\w+-]*\n/, "").replace(/\n$/, "");
    return `<pre><code>${esc(code)}</code></pre>`;
  }).join("");
}

// ---------- Chat ----------

function scrollToEnd() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role) {
  emptyEl.hidden = true;
  const msg = document.createElement("div");
  msg.className = `msg msg--${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  return { msg, bubble };
}

async function send(text) {
  if (busy) return;
  busy = true;
  updateComposer();

  addMessage("user").bubble.textContent = text;
  const pending = addMessage("bot");
  pending.bubble.innerHTML = '<div class="typing" aria-label="Thinking"><span></span><span></span><span></span></div>';
  scrollToEnd();

  try {
    const data = await api("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, thread_id: threadId }),
    });
    pending.bubble.innerHTML = renderMarkdown(data.response);
  } catch (err) {
    const [title, body] = describeError(err);
    pending.msg.classList.add("msg--error");
    pending.bubble.innerHTML = `<strong>${esc(title)}</strong>${esc(body)}`;
  }

  busy = false;
  updateComposer();
  scrollToEnd();
  input.focus();
}

function updateComposer() {
  sendBtn.disabled = busy || !input.value.trim();
  input.style.height = "auto";
  input.style.height = input.scrollHeight + "px";
}

function submit() {
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  send(text);
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  submit();
});

input.addEventListener("input", updateComposer);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
});

document.querySelectorAll(".chip-btn").forEach((chip) => {
  chip.addEventListener("click", () => send(chip.textContent));
});

$("newChat").addEventListener("click", () => {
  if (busy) return;
  messagesEl.querySelectorAll(".msg").forEach((m) => m.remove());
  emptyEl.hidden = false;
  threadId = newThreadId();
  input.focus();
});

// ---------- 3D motion ----------
// The slab floats on its own and leans toward the pointer; background shapes
// slide the other way, further the "closer" they are (data-depth, in px).

const MAX_TILT = 7;

function startMotion() {
  const shapes = [...document.querySelectorAll(".shape")].map((el) => ({
    el,
    depth: Number(el.dataset.depth),
  }));
  const compact = window.matchMedia("(max-width: 640px)");

  // Pointer position as -1..1 from the viewport centre; (x, y) eases toward the target
  let targetX = 0, targetY = 0, x = 0, y = 0;

  window.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch") return;
    targetX = (e.clientX / window.innerWidth) * 2 - 1;
    targetY = (e.clientY / window.innerHeight) * 2 - 1;
  });

  document.documentElement.addEventListener("pointerleave", () => {
    targetX = 0;
    targetY = 0;
  });

  function frame(now) {
    const t = now / 1000;
    // A small slab tilted as far as a big one reads as jittery on a phone
    const scale = compact.matches ? 0.45 : 1;

    x += (targetX - x) * 0.06;
    y += (targetY - y) * 0.06;

    const rotateX = (-y * MAX_TILT + Math.sin(t * 0.7) * 1.6) * scale;
    const rotateY = (x * MAX_TILT + Math.cos(t * 0.5) * 2.2) * scale;
    const lift = Math.sin(t * 0.9) * 7 * scale;

    chatEl.style.transform = `translateY(${lift.toFixed(2)}px) rotateX(${rotateX.toFixed(3)}deg) rotateY(${rotateY.toFixed(3)}deg)`;

    for (const { el, depth } of shapes) {
      el.style.translate = `${(-x * depth).toFixed(1)}px ${(-y * depth).toFixed(1)}px`;
    }

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) startMotion();

// ---------- Init ----------

updateComposer();
input.focus();

// The customer's side of a voice call: microphone up, answers down.
// Everything that decides anything runs on the server; this page captures,
// plays, and draws what the server reports.

const $ = (id) => document.getElementById(id);

const STATES = {
  loading: "Loading models",
  listening: "Listening",
  user: "You are speaking",
  thinking: "Thinking",
  speaking: "Speaking",
};

let ws = null;
let ctx = null;
let stream = null;
let playing = null; // { turn, items: [], queueEnd, started, stopped }
let decodeChain = Promise.resolve();
const cancelled = new Set();
const bubbles = new Map(); // "agent-3" -> element
const results = []; // metrics of every turn, across calls

// ── options ────────────────────────────────────────────────────────────────

async function loadOptions() {
  const options = await (await fetch("/api/options")).json();
  fill($("asr"), options.asr, "zipformer-30m");
  fill($("endpointing"), options.endpointing, "smart");
  fill($("voice"), options.voices, "vieneu:");
  fill($("agent"), options.agents, "backend");
}

// ── the backend's advisor model ───────────────────────────────────────────

async function loadAdvisor() {
  const note = $("advisor-note");
  const response = await fetch("/api/advisor");
  const report = await response.json();
  if (!response.ok) {
    $("advisor").innerHTML = "<option>Backend not reachable</option>";
    $("switch").disabled = true;
    note.textContent = `${report.detail}. Start the backend to switch models.`;
    return;
  }
  const select = $("advisor");
  select.innerHTML = "";
  const reset = document.createElement("option");
  reset.value = "";
  reset.textContent = `File default · ${report.default_model}`;
  select.appendChild(reset);
  for (const choice of report.choices) {
    const option = document.createElement("option");
    option.value = `${choice.provider}|${choice.model}`;
    option.textContent = choice.label;
    if (report.overridden && choice.provider === report.provider && choice.model === report.model) option.selected = true;
    select.appendChild(option);
  }
  $("switch").disabled = false;
  note.textContent = `Answering on ${report.model}${report.overridden ? " (switched here, not the file's choice)" : " (the file's choice)"}. A switch lasts until the backend restarts.`;
}

async function switchAdvisor() {
  const [provider, model] = $("advisor").value ? $("advisor").value.split("|") : [null, null];
  const button = $("switch");
  button.disabled = true;
  $("advisor-note").textContent = `Rebuilding the advisor on ${model || "the file default"}…`;
  try {
    const response = await fetch("/api/advisor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model }),
    });
    const report = await response.json();
    if (!response.ok) throw new Error(report.detail);
    await loadAdvisor();
    $("advisor-note").textContent = `Now answering on ${report.model}, rebuilt in ${report.rebuild_seconds} s. ${$("advisor-note").textContent.split(". ").slice(1).join(". ")}`;
    if (ws) divider(`Advisor switched to ${report.model}`);
  } catch (error) {
    $("advisor-note").textContent = `Could not switch: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function fill(select, items, preferred) {
  select.innerHTML = "";
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.label;
    if (item.name === preferred) option.selected = true;
    select.appendChild(option);
  }
}

// ── the call ───────────────────────────────────────────────────────────────

async function startCall() {
  ctx = new AudioContext();
  await ctx.audioWorklet.addModule("/static/capture.js");
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  const source = ctx.createMediaStreamSource(stream);
  const capture = new AudioWorkletNode(ctx, "capture");
  const mute = ctx.createGain();
  mute.gain.value = 0;
  // The worklet must be pulled by the graph to run; a silent path to the
  // speakers does that without playing the microphone back.
  source.connect(capture).connect(mute).connect(ctx.destination);

  const params = new URLSearchParams({
    asr: $("asr").value,
    endpointing: $("endpointing").value,
    voice: $("voice").value,
    agent: $("agent").value,
    compare: $("compare").checked ? "1" : "0",
  });
  ws = new WebSocket(`ws://${location.host}/ws?${params}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => send({ type: "hello", sample_rate: ctx.sampleRate });
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = () => endCall(false);

  capture.port.onmessage = (event) => {
    meter(event.data);
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(event.data.buffer);
  };

  $("empty")?.remove();
  divider(`Call started · ${$("asr").selectedOptions[0].textContent}`);
  $("call").textContent = "Hang up";
  $("call").classList.add("secondary");
  setControls(true);
}

function endCall(closeSocket = true) {
  if (closeSocket && ws) ws.close();
  ws = null;
  stopPlayback();
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  if (ctx) ctx.close();
  ctx = null;
  setState("idle");
  $("call").textContent = "Start call";
  $("call").classList.remove("secondary");
  setControls(false);
}

function setControls(inCall) {
  for (const id of ["asr", "endpointing", "voice", "agent", "compare"]) $(id).disabled = inCall;
}

function send(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

// ── what the server says ───────────────────────────────────────────────────

function handle(message) {
  switch (message.type) {
    case "state":
      setState(message.state);
      break;
    case "status":
      status(message.text);
      break;
    case "error":
      status(message.text);
      break;
    case "transcript":
      customerTurn(message);
      break;
    case "reply":
      agentTurn(message);
      break;
    case "audio":
      decodeChain = decodeChain.then(() => enqueue(message)).catch((error) => status(String(error)));
      break;
    case "audio_end":
      decodeChain = decodeChain.then(() => finish(message));
      break;
    case "stop":
      interrupt(message.turn);
      break;
    case "truncated":
      markHeard(message.turn, message.heard);
      break;
    case "metrics":
      addMetrics(message);
      break;
    case "compare":
      addCompare(message);
      break;
  }
}

function setState(state) {
  $("state").textContent = STATES[state] || "Idle";
  $("dot").classList.toggle("live", state !== "idle");
}

function status(text) {
  $("status").textContent = text;
}

// ── transcript ─────────────────────────────────────────────────────────────

function divider(text) {
  const line = document.createElement("div");
  line.className = "meta";
  line.style.alignSelf = "center";
  line.textContent = text;
  $("transcript").appendChild(line);
}

function turnElement(kind, who) {
  const wrap = document.createElement("div");
  wrap.className = `turn ${kind}`;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const meta = document.createElement("div");
  meta.className = "meta";
  wrap.append(label, bubble, meta);
  $("transcript").appendChild(wrap);
  $("transcript").scrollTop = $("transcript").scrollHeight;
  return { wrap, bubble, meta };
}

function customerTurn(m) {
  const el = turnElement("customer", "You");
  el.bubble.textContent = m.text || "(nothing recognised)";
  const parts = [m.model, `${m.audio_seconds} s of speech`, `ASR ${m.asr_seconds} s`, `ended by ${m.endpointing}`];
  el.meta.textContent = parts.join(" · ");
  if (m.corrections && m.corrections.length) {
    const raw = document.createElement("div");
    raw.className = "meta raw";
    raw.textContent = `Heard as: ${m.raw}`;
    el.wrap.appendChild(raw);
  }
}

function agentTurn(m) {
  const el = turnElement("agent", "Assistant");
  el.bubble.textContent = m.text;
  const meta = m.meta || {};
  const parts = [];
  if (meta.model) parts.push(meta.model);
  if (meta.tools && meta.tools.length) parts.push(`tools: ${meta.tools.join(", ")}`);
  if (m.superseded) parts.push("not spoken: you had already said more");
  el.meta.textContent = parts.join(" · ");
  if (meta.error) {
    const flag = document.createElement("p");
    flag.className = "flag";
    flag.style.marginTop = "6px";
    flag.textContent = `The agent failed, so this is the fallback line. ${meta.error}`;
    el.wrap.appendChild(flag);
  }
  bubbles.set(`agent-${m.turn}`, el);
}

function markHeard(turn, heard) {
  const el = bubbles.get(`agent-${turn}`);
  if (!el) return;
  const full = el.bubble.textContent;
  const rest = full.startsWith(heard) ? full.slice(heard.length) : "";
  el.bubble.textContent = heard;
  if (rest) {
    const unheard = document.createElement("span");
    unheard.className = "unheard";
    unheard.textContent = rest;
    el.bubble.appendChild(unheard);
  }
  el.meta.textContent = `${el.meta.textContent} · interrupted; the thread keeps only the part you heard`.replace(/^ · /, "");
}

// ── playback ───────────────────────────────────────────────────────────────

async function enqueue(m) {
  if (!ctx || cancelled.has(m.turn)) return;
  const bytes = Uint8Array.from(atob(m.data), (c) => c.charCodeAt(0));
  const buffer = await ctx.decodeAudioData(bytes.buffer);
  if (!ctx || cancelled.has(m.turn)) return;

  if (!playing || playing.turn !== m.turn) {
    playing = { turn: m.turn, items: [], queueEnd: ctx.currentTime, started: false, stopped: false, lastSeq: null };
  }
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  const at = Math.max(ctx.currentTime + 0.02, playing.queueEnd);
  source.start(at);
  const item = { seq: m.seq, start: at, duration: buffer.duration, source };
  playing.items.push(item);
  playing.queueEnd = at + buffer.duration;

  const turn = m.turn;
  if (!playing.started) {
    playing.started = true;
    const delay = Math.max(0, (at - ctx.currentTime) * 1000);
    setTimeout(() => send({ type: "playback_started", turn }), delay);
  }
  source.onended = () => {
    if (playing && playing.turn === turn && !playing.stopped && playing.lastSeq === item.seq) {
      send({ type: "playback_ended", turn });
    }
  };
}

// The server says which chunk is the last only once synthesis is over. If
// playback has already run past it (the stream starved), report the end now.
function finish(m) {
  if (!playing || playing.turn !== m.turn || !ctx) return;
  playing.lastSeq = m.last_seq;
  const item = playing.items.find((it) => it.seq === m.last_seq);
  if (item && ctx.currentTime >= item.start + item.duration) send({ type: "playback_ended", turn: m.turn });
}

function interrupt(turn) {
  cancelled.add(turn);
  if (!playing || playing.turn !== turn || !ctx) return;
  const now = ctx.currentTime;
  const current =
    playing.items.find((it) => now >= it.start && now < it.start + it.duration) ||
    playing.items.find((it) => now < it.start) ||
    playing.items[playing.items.length - 1];
  const played = current ? Math.max(0, (now - current.start) * 1000) : 0;
  stopPlayback();
  send({
    type: "playback_stopped",
    turn,
    seq: current ? current.seq : 0,
    played_ms: played,
    duration_ms: current ? current.duration * 1000 : 1,
  });
}

function stopPlayback() {
  if (!playing) return;
  playing.stopped = true;
  for (const item of playing.items) {
    try { item.source.stop(); } catch (_) { /* already ended */ }
  }
  playing = null;
}

// ── numbers ────────────────────────────────────────────────────────────────

function fmt(value) {
  return value === null || value === undefined ? "–" : value.toFixed(2);
}

function addMetrics(m) {
  const row = document.createElement("tr");
  const label = m.kind === "opening" ? "Greeting" : `${m.turn}`;
  const cells = m.kind === "opening"
    ? [label, null, null, m.agent, m.tts, m.delivery, m.ttfa]
    : [label, m.endpoint, m.asr, m.agent, m.tts, m.delivery, m.ttfa];
  cells.forEach((value, i) => {
    const cell = document.createElement("td");
    cell.textContent = i === 0 ? value : fmt(value);
    if (i === cells.length - 1) cell.className = "total";
    row.appendChild(cell);
  });
  $("rows").appendChild(row);
  if (m.kind === "turn") {
    const meta = m.agent_meta || {};
    const advisor = meta.error ? "failed" : meta.model || $("agent").value;
    results.push({ model: $("asr").value, advisor, ...m });
    summarise();
    summariseAdvisors();
  }
}

function median(values) {
  const sorted = values.filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function summarise() {
  const byModel = new Map();
  for (const r of results) {
    if (!byModel.has(r.model)) byModel.set(r.model, []);
    byModel.get(r.model).push(r);
  }
  const body = $("summary");
  body.innerHTML = "";
  for (const [model, rows] of byModel) {
    const tr = document.createElement("tr");
    const values = [model, rows.length, median(rows.map((r) => r.endpoint)), median(rows.map((r) => r.asr)), median(rows.map((r) => r.ttfa))];
    values.forEach((value, i) => {
      const cell = document.createElement("td");
      cell.textContent = i < 2 ? value : fmt(value);
      if (i === values.length - 1) cell.className = "total";
      tr.appendChild(cell);
    });
    body.appendChild(tr);
  }
}

function summariseAdvisors() {
  const byModel = new Map();
  for (const r of results) {
    if (!byModel.has(r.advisor)) byModel.set(r.advisor, []);
    byModel.get(r.advisor).push(r);
  }
  const body = $("by-advisor");
  body.innerHTML = "";
  for (const [model, rows] of byModel) {
    const tr = document.createElement("tr");
    const values = [model, rows.length, median(rows.map((r) => r.agent)), median(rows.map((r) => r.ttfa))];
    values.forEach((value, i) => {
      const cell = document.createElement("td");
      cell.textContent = i < 2 ? value : fmt(value);
      if (i === values.length - 1) cell.className = "total";
      tr.appendChild(cell);
    });
    body.appendChild(tr);
  }
}

function addCompare(m) {
  const list = $("compare-list");
  list.querySelector(".note")?.remove();
  const id = `cmp-${m.turn}-${m.model}`;
  let row = document.getElementById(id);
  if (!row) {
    row = document.createElement("div");
    row.id = id;
    row.className = "cmp";
    list.prepend(row);
  }
  row.innerHTML = "";
  const head = document.createElement("div");
  head.className = "model";
  head.textContent = m.pending
    ? `Turn ${m.turn} · ${m.model} · running`
    : `Turn ${m.turn} · ${m.model} · ${fmt(m.asr_seconds)} s · RTF ${fmt(m.rtf)}`;
  const text = document.createElement("div");
  text.textContent = m.pending ? "" : m.text || "(nothing recognised)";
  row.append(head, text);
}

function meter(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / samples.length);
  $("level").style.width = `${Math.min(100, rms * 400)}%`;
}

// ── wiring ─────────────────────────────────────────────────────────────────

$("call").addEventListener("click", () => {
  if (ws) endCall();
  else startCall().catch((error) => { status(String(error)); endCall(); });
});

$("switch").addEventListener("click", switchAdvisor);

loadOptions().catch((error) => status(`Could not load options: ${error}`));
loadAdvisor().catch((error) => { $("advisor-note").textContent = `Could not read the advisor model: ${error}`; });

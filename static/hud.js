// JARVIS — interface : horloge, état, conversation, voix, validations
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
let TOKEN = store.get("jarvis_token");

async function api(path, opts = {}) {
  const headers = { "X-Jarvis-Token": TOKEN, ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) { askToken(); throw new Error("auth"); }
  return r.json();
}

function askToken() {
  $("login").hidden = false; $("token").focus();
}
$("t-ok").onclick = () => { TOKEN = $("token").value.trim(); store.set("jarvis_token", TOKEN); $("login").hidden = true; poll(); };
$("token").onkeydown = (e) => e.key === "Enter" && $("t-ok").click();

// ---------- Horloge ----------
function tick() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  $("date").textContent = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }).toUpperCase();
}
setInterval(tick, 1000); tick();

// ---------- État système ----------
function gauge(id, v) {
  $("g-" + id).style.strokeDasharray = `${v ?? 0} 100`;
  $("v-" + id).textContent = v == null ? "--" : Math.round(v);
}
async function poll() {
  try {
    const s = await api("/api/status");
    gauge("cpu", s.cpu); gauge("ram", s.ram); gauge("bat", s.battery);
    const net = $("st-net"), br = $("st-brain");
    net.textContent = s.online ? "EN LIGNE" : "HORS LIGNE";
    net.className = "pill " + (s.online ? "ok" : "warn");
    br.textContent = s.claude ? "CLAUDE" : s.local ? "LOCAL" : "AUCUN CERVEAU";
    br.className = "pill " + (s.claude ? "ok" : s.local ? "warn" : "bad");
    $("ver").textContent = s.version ? "v." + s.version : "";
  } catch {
    $("st-net").textContent = "SERVEUR ?"; $("st-net").className = "pill bad";
  }
}
setInterval(poll, 5000); poll();

// ---------- Fil de conversation ----------
function line(text, cls = "") {
  const el = document.createElement("div");
  el.className = "line " + cls; el.textContent = text;
  $("feed").appendChild(el);
  while ($("feed").children.length > 14) $("feed").firstChild.remove();
}
function setState(s, label) {
  document.body.classList.remove("listening", "thinking", "speaking");
  if (s) document.body.classList.add(s);
  $("state").textContent = label;
}

// ---------- Voix (sortie) ----------
function speak(text) {
  if (!("speechSynthesis" in window)) return setState("", "EN VEILLE");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = 1.02; u.pitch = 0.9;
  const v = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("fr"));
  u.voice = v.find((x) => /Henri|Paul|Thomas|Male|Homme/i.test(x.name)) || v[0] || null;
  u.onstart = () => setState("speaking", "RÉPONSE");
  u.onend = () => setState("", "EN VEILLE");
  speechSynthesis.speak(u);
}
speechSynthesis?.getVoices();

// ---------- Ordres ----------
function handle(res) {
  (res.log || []).forEach((l) => line("› " + l, "log"));
  if (res.confirm) {
    const c = res.confirm;
    $("cbody").textContent = `${c.tool}\n\n${c.args.command || c.args.path || ""}${c.args.content ? "\n\n" + c.args.content.slice(0, 1500) : ""}`;
    $("confirm").hidden = false;
    $("c-yes").onclick = () => decide(c.id, true);
    $("c-no").onclick = () => decide(c.id, false);
    speak("J'ai besoin de votre autorisation.");
    return;
  }
  line(res.reply || "…");
  speak(res.reply || "");
}
async function decide(id, approve) {
  $("confirm").hidden = true;
  setState("thinking", "EXÉCUTION");
  try { handle(await api("/api/confirm", { method: "POST", body: JSON.stringify({ id, approve }) })); }
  catch (e) { line("Erreur : " + e.message); setState("", "EN VEILLE"); }
}
async function send(text) {
  text = text.trim(); if (!text) return;
  line(text, "user");
  setState("thinking", "ANALYSE");
  try { handle(await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) })); }
  catch (e) { if (e.message !== "auth") line("Erreur : " + e.message); setState("", "EN VEILLE"); }
}
$("form").onsubmit = (e) => { e.preventDefault(); send($("input").value); $("input").value = ""; };

// ---------- Voix (entrée) : enregistrement → Whisper local ----------
let rec = null, chunks = [];
async function startListen() {
  if (rec) return stopListen();
  speechSynthesis?.cancel();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    rec = new MediaRecorder(stream); chunks = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: "audio/webm" }), "voice.webm");
      setState("thinking", "TRANSCRIPTION");
      try { const r = await api("/api/transcribe", { method: "POST", body: fd }); r.text ? send(r.text) : setState("", "EN VEILLE"); }
      catch { line("Reconnaissance vocale indisponible."); setState("", "EN VEILLE"); }
      rec = null; $("btn-mic").classList.remove("on");
    };
    rec.start(); $("btn-mic").classList.add("on");
    setState("listening", "J'ÉCOUTE");
  } catch { line("Micro inaccessible (HTTPS requis sur téléphone)."); }
}
function stopListen() { rec && rec.state === "recording" && rec.stop(); }
$("btn-mic").onclick = startListen;
$("reactor").onclick = startListen;
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "") && !e.repeat) { e.preventDefault(); startListen(); }
});

window.jarvis = { send, line, api, speak };

// JARVIS — interface : démarrage, état, conversation, voix, validations, téléphone
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
let TOKEN = store.get("jarvis_token");

async function api(path, opts = {}) {
  const json = opts.body && !(opts.body instanceof FormData);
  const r = await fetch(path, { ...opts, headers: { "X-Jarvis-Token": TOKEN, ...(json ? { "Content-Type": "application/json" } : {}) } });
  if (r.status === 401) { askToken(); throw new Error("auth"); }
  return r.json();
}
function askToken() { $("login").hidden = false; setTimeout(() => $("token").focus(), 50); }
$("t-ok").onclick = () => { TOKEN = $("token").value.trim().toUpperCase(); store.set("jarvis_token", TOKEN); $("login").hidden = true; poll(); };
$("token").onkeydown = (e) => { if (e.key === "Enter") $("t-ok").click(); };

// ---------- Démarrage ----------
(function boot() {
  const lines = ["NOYAU NEURONAL", "MODULE VOCAL", "VISION & GESTES", "LIAISON MOBILE", "PROTOCOLES DE SÉCURITÉ"];
  const box = $("boot-lines");
  lines.forEach((l, i) => setTimeout(() => {
    const d = document.createElement("div"); d.innerHTML = `${l}<span class="okk">OK</span>`; box.appendChild(d);
  }, 280 + i * 380));
  setTimeout(() => document.body.classList.remove("booting"), 2900);
})();

// ---------- Horloge ----------
function tick() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  $("sec").textContent = String(d.getSeconds()).padStart(2, "0");
  $("date").textContent = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }).toUpperCase();
}
setInterval(tick, 1000); tick();

// ---------- État ----------
function bar(id, v, hot = 85) {
  const b = $("bar-" + id); if (!b) return;
  b.style.width = (v ?? 0) + "%"; b.classList.toggle("hot", v != null && v >= hot);
  $("v-" + id).textContent = v == null ? "--" : Math.round(v) + "%";
}
function chip(id, text, cls) { const c = $(id); c.textContent = text; c.className = "chip " + cls; }
async function poll() {
  try {
    const s = await api("/api/status"); lastStatus = s;
    bar("cpu", s.cpu); bar("ram", s.ram); bar("bat", s.battery, 101);
    window.FX && FX.pushCpu(s.cpu);
    chip("st-net", s.online ? "EN LIGNE" : "HORS LIGNE", s.online ? "ok" : "warn");
    chip("st-brain", s.claude ? "CLAUDE" : s.local ? "LOCAL" : "AUCUN CERVEAU", s.claude ? "ok" : s.local ? "warn" : "bad");
    chip("st-wake", s.wake ? "HEY JARVIS" : "MICRO OFF", s.wake ? "ok" : "warn");
    $("ver").textContent = (s.version ? "VERSION " + s.version.toUpperCase() : "") + "  ·  " + (s.update || "").toUpperCase();
  } catch { chip("st-net", "SERVEUR ?", "bad"); }
}
setInterval(poll, 5000); poll();

async function pollPhone() {
  try {
    const p = await api("/api/phone");
    chip("st-phone", p.connected ? "MOBILE" : "MOBILE OFF", p.connected ? "ok" : "warn");
    bar("pbat", p.connected ? p.battery : null, 101);
    $("ph-status").textContent = p.connected ? `Connecté : ${p.model || p.device} — batterie ${p.battery ?? "?"} %` : "Aucun téléphone associé.";
    return p;
  } catch { return {}; }
}
setInterval(pollPhone, 20000); pollPhone();

// ---------- Fil de conversation ----------
function line(text, cls = "") {
  const el = document.createElement("div");
  el.className = "line " + cls; el.textContent = text;
  el.dataset.who = cls === "user" ? "VOUS" : "JARVIS";
  $("feed").appendChild(el);
  while ($("feed").children.length > 40) $("feed").firstChild.remove();
  $("feed").scrollTop = 1e9;
}
const LABELS = { listening: "J'ÉCOUTE", thinking: "ANALYSE", speaking: "RÉPONSE", "": "EN VEILLE" };
function setState(s, label) {
  document.body.classList.remove("listening", "thinking", "speaking");
  if (s) document.body.classList.add(s);
  if (window.FX) FX.state = s || "idle";
  const t = label || LABELS[s] || "EN VEILLE";
  $("state").textContent = t; $("state").dataset.text = t;
}

// ---------- Voix (sortie) ----------
function speak(text) {
  if (!("speechSynthesis" in window) || !text) return setState("");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = 1.02; u.pitch = 0.85;
  const v = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("fr"));
  u.voice = v.find((x) => /Henri|Paul|Thomas|Male|Homme|Claude/i.test(x.name)) || v[0] || null;
  u.onstart = () => setState("speaking");
  u.onend = () => setState("");
  speechSynthesis.speak(u);
}
window.speechSynthesis?.getVoices();

// ---------- Ordres ----------
function handle(res, voice = true) {
  (res.log || []).forEach((l) => line("› " + l, "log"));
  if (res.confirm) {
    const c = res.confirm;
    $("cbody").textContent = `${c.tool}\n\n${c.args.command || c.args.path || ""}${c.args.content ? "\n\n" + c.args.content.slice(0, 1500) : ""}`;
    $("confirm").hidden = false;
    $("c-yes").onclick = () => decide(c.id, true);
    $("c-no").onclick = () => decide(c.id, false);
    setState("", "EN ATTENTE");
    if (voice) speak("J'ai besoin de votre autorisation.");
    return;
  }
  line(res.reply || "…");
  if (voice) speak(res.reply || ""); else setState("");
}
async function decide(id, approve) {
  $("confirm").hidden = true; setState("thinking", "EXÉCUTION");
  try { handle(await api("/api/confirm", { method: "POST", body: JSON.stringify({ id, approve }) })); }
  catch (e) { line("Erreur : " + e.message); setState(""); }
}
async function send(text) {
  text = text.trim(); if (!text) return;
  line(text, "user"); setState("thinking");
  try { handle(await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) })); }
  catch (e) { if (e.message !== "auth") line("Erreur : " + e.message); setState(""); }
}
$("form").onsubmit = (e) => { e.preventDefault(); send($("input").value); $("input").value = ""; };

// ---------- Voix (entrée) : enregistrement → Whisper local ----------
let rec = null, chunks = [], meter = null;
async function startListen() {
  if (rec) return stopListen();
  window.speechSynthesis?.cancel();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const an = ac.createAnalyser(); an.fftSize = 512; ac.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    meter = setInterval(() => { an.getByteTimeDomainData(buf); let s = 0; for (const v of buf) s += ((v - 128) / 128) ** 2; if (window.FX) FX.level = Math.min(1, Math.sqrt(s / buf.length) * 5); }, 50);
    rec = new MediaRecorder(stream); chunks = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      clearInterval(meter); if (window.FX) FX.level = 0; ac.close();
      stream.getTracks().forEach((t) => t.stop());
      const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: "audio/webm" }), "voice.webm");
      setState("thinking", "TRANSCRIPTION");
      try { const r = await api("/api/transcribe", { method: "POST", body: fd }); r.text ? send(r.text) : setState(""); }
      catch { line("Reconnaissance vocale indisponible."); setState(""); }
      rec = null; $("btn-mic").classList.remove("on");
    };
    rec.start(); $("btn-mic").classList.add("on"); setState("listening");
  } catch { line("Micro inaccessible (HTTPS requis sur téléphone)."); }
}
function stopListen() { rec && rec.state === "recording" && rec.stop(); }
$("btn-mic").onclick = startListen;
$("reactor").onclick = startListen;
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "") && !e.repeat) { e.preventDefault(); startListen(); }
});

// ---------- Téléphone ----------
$("btn-phone").onclick = () => { $("phone").hidden = false; pollPhone(); };
$("ph-close").onclick = () => { $("phone").hidden = true; };
$("ph-usb").onclick = () => { $("ph-host").value = "usb"; $("ph-code").value = ""; $("ph-go").click(); $("ph-host").value = ""; };
$("ph-go").onclick = async () => {
  const host = $("ph-host").value.trim(), code = $("ph-code").value.trim();
  if (!host) return;
  $("ph-out").textContent = "Liaison en cours…";
  try {
    const r = await api("/api/phone", { method: "POST", body: JSON.stringify({ host, code }) });
    $("ph-out").textContent = r.output || "";
    if (!r.connected && code) $("ph-out").textContent += "\n\nAssocié. Saisissez maintenant l'adresse affichée sous « Adresse IP et port » de l'écran Débogage sans fil (sans code), puis ASSOCIER.";
    $("ph-code").value = "";
    pollPhone();
  } catch (e) { $("ph-out").textContent = "Erreur : " + e.message; }
};

// ---------- Réglages : clé Claude ----------
let lastStatus = {};
$("btn-cfg").onclick = () => {
  $("cfg").hidden = false; $("cfg-out").textContent = "";
  $("cfg-status").textContent = lastStatus.claude ? "Claude est actif." : "Aucune clé Claude : Jarvis utilise le cerveau local (lent).";
};
$("cfg-close").onclick = () => { $("cfg").hidden = true; };
$("cfg-save").onclick = async () => {
  $("cfg-out").textContent = "Vérification de la clé…";
  try {
    const r = await api("/api/config", { method: "POST", body: JSON.stringify({ anthropic_key: $("cfg-key").value.trim(), claude_model: $("cfg-model").value }) });
    $("cfg-out").textContent = r.ok ? (r.has_key ? "✔ Clé valide, Claude activé (" + r.model + ")." : "Modèle enregistré.") : "✖ Clé refusée : " + r.error;
    if (r.ok) { $("cfg-key").value = ""; poll(); }
  } catch (e) { $("cfg-out").textContent = "Erreur : " + e.message; }
};

// ---------- Conversations vocales lancées sur le PC (« Hey Jarvis ») ----------
let lastEvt = -1;
async function pollEvents() {
  try {
    const r = await api("/api/events?after=" + Math.max(lastEvt, 0));
    if (lastEvt < 0) { lastEvt = r.last; return; }
    for (const e of r.events) {
      lastEvt = e.id;
      if (e.type === "state") setState(e.state === "idle" ? "" : e.state);
      if (e.type === "user") line(e.text, "user");
      if (e.type === "reply" || e.type === "confirm") handle(e.res, false);
    }
  } catch {}
}
setInterval(pollEvents, 1500); pollEvents();

window.jarvis = { send, line, api, speak };

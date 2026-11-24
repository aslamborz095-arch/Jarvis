// JARVIS — interface : démarrage, état, conversation, voix, validations, téléphone
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
let TOKEN = store.get("jarvis_token");
const LS = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let SOLO = false;   // true = PC injoignable, le téléphone fonctionne seul

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

// ---------- Mémoire commune PC ⇄ téléphone ----------
async function sync() {
  const pend = LS.get("jarvis_pending", { notes: [], history: [] });
  if (pend.notes.length || pend.history.length) {
    await api("/api/sync", { method: "POST", body: JSON.stringify(pend) });
    LS.set("jarvis_pending", { notes: [], history: [] });
    line("Mémoire synchronisée avec le PC.", "log");
  }
  const d = await api("/api/sync");
  LS.set("jarvis_notes", d.notes || []); LS.set("jarvis_hist", d.history || []); LS.set("jarvis_brains", d.brains || []);
  if (d.groq_key) store.set("jarvis_groq", d.groq_key);
}
function setSolo(on) {
  if (SOLO === on) return;
  SOLO = on;
  if (on) {
    chip("st-net", "AUTONOME", "warn");
    const nb = LS.get("jarvis_brains", []).length || (store.get("jarvis_groq") ? 1 : 0);
    chip("st-brain", nb ? nb + " IA DIRECT" : "AUCUN CERVEAU", nb ? "ok" : "bad");
    chip("st-wake", "MICRO TEL.", "ok"); chip("st-phone", "PC HORS LIGNE", "warn");
    line("PC injoignable : mode autonome. Ce que vous dites sera ajouté à la mémoire commune au retour du PC.", "log");
  } else sync().catch(() => {});
}
async function soloAsk(text) {
  const brains = LS.get("jarvis_brains", []);
  if (!brains.length && store.get("jarvis_groq")) brains.push({ id: "groq", base: "https://api.groq.com/openai/v1", model: "openai/gpt-oss-120b", key: store.get("jarvis_groq") });
  if (!brains.length) return { reply: "Mode autonome impossible : ouvrez Jarvis une fois avec le PC allumé pour récupérer vos IA." };
  let bi = 0;
  const notes = LS.get("jarvis_notes", []), hist = LS.get("jarvis_hist", []);
  const d = new Date(), stamp = d.toLocaleString("fr-FR", { weekday: "long", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const msgs = [{ role: "system", content: "Tu es JARVIS, l'assistant personnel d'Aslambek. Le PC est éteint : tu réponds depuis son téléphone, sans accès au PC. Français, court, ton calme et légèrement britannique, pas de markdown (réponse lue à voix haute). Utilise remember pour retenir une info durable.\nCe que tu sais de lui :\n" + (notes.slice(-50).map((n) => "- " + n.note).join("\n") || "(rien)") },
    ...hist.slice(-12), { role: "user", content: `[${stamp}] ${text}` }];
  const tools = [{ type: "function", function: { name: "remember", description: "Mémorise durablement une info sur l'utilisateur.", parameters: { type: "object", properties: { note: { type: "string" } }, required: ["note"] } } }];
  const pend = LS.get("jarvis_pending", { notes: [], history: [] }), log = [];
  for (let step = 0; step < 4; step++) {
    let r = null;
    for (; bi < brains.length; bi++) {           // cascade : IA suivante si quota/crédit épuisé
      const b = brains[bi];
      try {
        r = await fetch(b.base.replace(/\/$/, "") + "/chat/completions", { method: "POST",
          headers: { Authorization: "Bearer " + b.key, "Content-Type": "application/json" },
          body: JSON.stringify({ model: b.model, messages: msgs, tools, max_tokens: 900 }) });
        if (r.ok) break;
        log.push(b.id + " indisponible (" + r.status + ") → IA suivante");
      } catch { log.push(b.id + " injoignable → IA suivante"); }
      r = null;
    }
    if (!r) return { reply: "Aucune IA en ligne ne répond pour le moment, monsieur.", log };
    const m = (await r.json()).choices[0].message;
    msgs.push({ role: "assistant", content: m.content || "", ...(m.tool_calls ? { tool_calls: m.tool_calls } : {}) });
    if (!m.tool_calls?.length) {
      const reply = (m.content || "").trim();
      const add = [{ role: "user", content: `[${stamp}] ${text}` }, { role: "assistant", content: reply }];
      LS.set("jarvis_hist", [...hist, ...add].slice(-30));
      pend.history.push(...add); LS.set("jarvis_pending", pend);
      return { reply, log };
    }
    for (const c of m.tool_calls) {
      let note = ""; try { note = JSON.parse(c.function.arguments || "{}").note || ""; } catch {}
      if (note) { const n = { date: new Date().toISOString().slice(0, 10), note }; pend.notes.push(n); LS.set("jarvis_notes", [...notes, n]); }
      log.push("remember → " + note);
      msgs.push({ role: "tool", tool_call_id: c.id, content: "Mémorisé." });
    }
  }
  LS.set("jarvis_pending", pend);
  return { reply: "C'est noté, monsieur.", log };
}

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
    const s = await api("/api/status"); lastStatus = s; setSolo(false);
    bar("cpu", s.cpu); bar("ram", s.ram); bar("bat", s.battery, 101);
    window.FX && FX.pushCpu(s.cpu);
    chip("st-net", s.online ? "EN LIGNE" : "HORS LIGNE", s.online ? "ok" : "warn");
    const live = (s.brains || []).filter((b) => b.status === "ok");
    chip("st-brain", s.claude ? "CLAUDE" : live.length ? live[0].name.toUpperCase() + (live.length > 1 ? " +" + (live.length - 1) : "") : s.local ? "LOCAL" : "AUCUN CERVEAU", s.claude || live.length ? "ok" : s.local ? "warn" : "bad");
    chip("st-wake", s.wake ? "HEY JARVIS" : "MICRO OFF", s.wake ? "ok" : "warn");
    $("ver").textContent = (s.version ? "VERSION " + s.version.toUpperCase() : "") + "  ·  " + (s.update || "").toUpperCase();
  } catch (e) { if (e.message !== "auth") setSolo(true); }
}
setInterval(poll, 5000); poll();

async function pollPhone() {
  if (SOLO) return {};
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

// ---------- Écriture animée des réponses (écran d'accueil) ----------
let typer = null;
function typeOut(text, userText) {
  const el = $("say"); clearInterval(typer);
  el.innerHTML = ""; el.classList.add("typing");
  if (userText) { const u = document.createElement("span"); u.className = "u"; u.textContent = "« " + userText + " »"; el.appendChild(u); }
  const t = document.createTextNode(""); el.appendChild(t);
  let i = 0;
  typer = setInterval(() => { t.data = text.slice(0, i += 2); if (i >= text.length) { clearInterval(typer); el.classList.remove("typing"); } }, 28);
}
let lastAsked = "";

// ---------- Conversation mains libres ----------
let CONV = false;
$("btn-talk").onclick = () => {
  CONV = !CONV; $("btn-talk").classList.toggle("on", CONV);
  if (CONV) { typeOut("Je vous écoute, monsieur."); startListen(); } else stopListen();
};
function nextTurn() { if (CONV && !rec && !srec) setTimeout(() => CONV && startListen(), 350); }

// ---------- Voix (sortie) : voix neuronale du serveur, secours voix du navigateur ----------
let player = null;
function speakBrowser(text) {
  if (!("speechSynthesis" in window)) return setState("");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = 1.02; u.pitch = 0.85;
  const v = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("fr"));
  u.voice = v.find((x) => /Henri|Paul|Thomas|Male|Homme|Claude/i.test(x.name)) || v[0] || null;
  u.onstart = () => setState("speaking");
  u.onend = () => { setState(""); nextTurn(); };
  speechSynthesis.speak(u);
}
async function speak(text) {
  if (!text) return setState("");
  window.speechSynthesis?.cancel(); player?.pause();
  if (SOLO) return speakBrowser(text);
  try {
    const r = await fetch("/api/tts?t=" + encodeURIComponent(text.slice(0, 1500)), { headers: { "X-Jarvis-Token": TOKEN } });
    if (!r.ok) throw 0;
    player = new Audio(URL.createObjectURL(await r.blob()));
    player.onplay = () => setState("speaking");
    player.onended = () => { setState(""); nextTurn(); };
    await player.play();
  } catch { speakBrowser(text); }
}
window.speechSynthesis?.getVoices();

// ---------- Ordres ----------
function handle(res, voice = true) {
  (res.log || []).forEach((l) => line("› " + l, "log"));
  if (res.confirm) {
    const c = res.confirm;
    const a = c.args || {};
    $("cbody").textContent = c.tool === "create_skill"
      ? `NOUVELLE COMPÉTENCE : ${a.name}\n${a.description || ""}\n\n${(a.code || "").slice(0, 4000)}`
      : `${c.tool}\n\n` + (a.command || a.path || a.to || a.event_id || a.name || "") +
        (a.subject ? "\nObjet : " + a.subject : "") + (a.content || a.body ? "\n\n" + (a.content || a.body).slice(0, 1500) : "");
    $("confirm").hidden = false;
    $("c-yes").onclick = () => decide(c.id, true);
    $("c-no").onclick = () => decide(c.id, false);
    setState("", "EN ATTENTE");
    if (voice) speak("J'ai besoin de votre autorisation.");
    return;
  }
  line(res.reply || "…");
  typeOut(res.reply || "…", lastAsked);
  if (voice) speak(res.reply || ""); else { setState(""); nextTurn(); }
}
async function decide(id, approve) {
  $("confirm").hidden = true; setState("thinking", "EXÉCUTION");
  try { handle(await api("/api/confirm", { method: "POST", body: JSON.stringify({ id, approve }) })); }
  catch (e) { line("Erreur : " + e.message); setState(""); }
}
async function send(text) {
  text = text.trim(); if (!text) return;
  if (CONV && /^(stop|arr[eê]te|merci jarvis|c'est tout|fin de la conversation)\b/i.test(text)) {
    CONV = false; $("btn-talk").classList.remove("on"); typeOut("Très bien, monsieur."); return speak("Très bien, monsieur.");
  }
  lastAsked = text; line(text, "user"); setState("thinking"); typeOut("…", text);
  try {
    if (SOLO) return handle(await soloAsk(text));
    handle(await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) }));
  } catch (e) {
    if (e.message === "auth") return setState("");
    if (!SOLO && e instanceof TypeError) { setSolo(true); return handle(await soloAsk(text)); }   // PC coupé en pleine demande
    line("Erreur : " + e.message); setState("");
  }
}
$("form").onsubmit = (e) => { e.preventDefault(); send($("input").value); $("input").value = ""; };

// ---------- Voix (entrée) : arrêt automatique quand vous vous taisez ----------
let rec = null, chunks = [], meter = null, srec = null;
function soloListen() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return line("Reconnaissance vocale indisponible sur ce navigateur.");
  srec = new SR(); srec.lang = "fr-FR"; srec.interimResults = false;
  srec.onstart = () => { $("btn-mic").classList.add("on"); setState("listening"); };
  srec.onresult = (e) => send(e.results[0][0].transcript);
  srec.onerror = (e) => line("Micro : " + e.error);
  srec.onend = () => { srec = null; $("btn-mic").classList.remove("on"); if (document.body.classList.contains("listening")) { setState(""); nextTurn(); } };
  srec.start();
}
async function startListen() {
  if (srec) return srec.stop();
  if (rec) return stopListen();
  window.speechSynthesis?.cancel(); player?.pause();
  if (SOLO) return soloListen();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const an = ac.createAnalyser(); an.fftSize = 1024; ac.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    let spoke = false, quiet = 0, t0 = Date.now(), noise = 0, peak = 0, samples = [];
    meter = setInterval(() => {
      an.getByteTimeDomainData(buf); let s = 0; for (const v of buf) s += ((v - 128) / 128) ** 2;
      const lvl = Math.sqrt(s / buf.length); peak = Math.max(peak, lvl);
      if (window.FX) FX.level = Math.min(1, lvl * 18);            // anneau visible même avec un micro faible
      if (Date.now() - t0 < 350) { samples.push(lvl); return; }      // bruit de fond (médiane)
      if (!noise) noise = samples.sort((a, b) => a - b)[samples.length >> 1] || 0.003;
      const loud = lvl > Math.max(0.008, noise * 1.8);
      if (loud) { spoke = true; quiet = 0; } else if (spoke) quiet += 50;
      if ((spoke && quiet > 1400) || Date.now() - t0 > 15000) stopListen();
    }, 50);
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => window.MediaRecorder?.isTypeSupported?.(m)) || "";
    rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); chunks = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      clearInterval(meter); if (window.FX) FX.level = 0; ac.close();
      stream.getTracks().forEach((t) => t.stop());
      rec = null; $("btn-mic").classList.remove("on");
      if (peak < 0.003) { line("Le micro ne capte aucun son : vérifiez le micro sélectionné (Windows : Paramètres → Son → Entrée) et son volume."); CONV = false; $("btn-talk").classList.remove("on"); return setState(""); }
      if (!spoke && CONV) { setState(""); return nextTurn(); }
      const type = chunks[0]?.type || mime || "audio/webm";
      const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
      const fd = new FormData(); fd.append("audio", new Blob(chunks, { type }), "voice." + ext);
      setState("thinking", "TRANSCRIPTION");
      try {
        const r = await api("/api/transcribe", { method: "POST", body: fd });
        if (r.text) send(r.text); else if (CONV) { setState(""); nextTurn(); } else { line(`Je n'ai pas compris, pouvez-vous répéter ? (niveau micro : ${Math.round(peak * 1000)})`); setState(""); }
      } catch { line("Reconnaissance vocale indisponible."); setState(""); }
    };
    rec.start(250); $("btn-mic").classList.add("on"); setState("listening");
  } catch (err) {
    const n = err && err.name;
    line(!window.isSecureContext ? "Micro bloqué : ouvrez Jarvis en https (adresse …ts.net) sur le téléphone."
      : n === "NotAllowedError" ? "Micro refusé : autorisez le micro pour ce site (icône 🔒 de la barre d'adresse), ou ouvrez Jarvis dans Chrome/Edge — le navigateur intégré de l'app Claude bloque le micro."
      : n === "NotFoundError" ? "Aucun micro détecté sur cet appareil."
      : n === "NotReadableError" ? "Micro déjà utilisé par une autre application."
      : "Micro indisponible : " + (err && err.message || n));
  }
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
  $("cfg-status").textContent = lastStatus.claude ? "Cerveau actif : Claude." : lastStatus.groq ? "Cerveau actif : Groq (gratuit)." : "Aucune clé : Jarvis utilise le cerveau local (lent).";
};
$("cfg-close").onclick = () => { $("cfg").hidden = true; };
async function gStatus() {
  try {
    const g = await api("/api/google");
    $("g-status").textContent = g.connected ? "✔ Google connecté (Gmail + Agenda)." : g.client ? "Fichier enregistré. Cliquez CONNECTER GOOGLE (sur le PC)." : "Pas encore configuré.";
  } catch {}
}
$("btn-cfg").addEventListener("click", gStatus);
let PRESETS = {};
async function loadBrains() {
  try {
    const r = await api("/api/providers"); PRESETS = r.presets || {};
    $("brains").innerHTML = "";
    r.active.forEach((b, i) => {
      const d = document.createElement("div"); d.className = "brain";
      const name = document.createElement("b"); name.textContent = `${i + 1}. ${b.name}`;
      const m = document.createElement("small"); m.textContent = b.model;
      const st = document.createElement("span"); st.className = "st " + (b.status === "ok" ? "ok" : "wait"); st.textContent = b.status === "ok" ? "PRÊT" : b.status.toUpperCase();
      const del = document.createElement("button"); del.textContent = "✕"; del.title = "Retirer";
      del.onclick = async () => { await api("/api/providers/" + b.id, { method: "DELETE" }); loadBrains(); };
      d.append(name, m, st, del); $("brains").appendChild(d);
    });
    if (!r.active.length) $("brains").innerHTML = '<p class="muted">Aucune IA en ligne : Jarvis utilise le cerveau local.</p>';
    const have = new Set(r.active.map((b) => b.id));
    $("br-id").innerHTML = Object.entries(PRESETS).filter(([id]) => !have.has(id)).sort(([, a], [, b]) => (b.free - a.free) || (a.rank - b.rank))
      .map(([id, p]) => `<option value="${id}">${p.name}${p.free ? " — gratuit" : " — payant"}</option>`).join("");
    showPreset();
  } catch {}
}
function showPreset() {
  const p = PRESETS[$("br-id").value]; if (!p) { $("br-info").textContent = "Toutes les IA connues sont ajoutées."; return; }
  $("br-info").innerHTML = "";
  const a = document.createElement("a"); a.href = p.signup; a.target = "_blank"; a.rel = "noopener"; a.textContent = "Créer la clé : " + p.signup.replace(/^https?:\/\//, "");
  const t = document.createElement("div"); t.textContent = p.note || "";
  $("br-info").append(a, t);
}
$("br-id").onchange = showPreset;
$("btn-cfg").addEventListener("click", loadBrains);
async function loadVoices() {
  try {
    const r = await api("/api/voices");
    $("vx").innerHTML = Object.entries(r.voices).map(([id, n]) => `<option value="${id}"${id === r.current ? " selected" : ""}>${n}</option>`).join("");
    $("vx-pitch").value = r.pitch; $("vx-rate").value = r.rate;
    $("vx-key").placeholder = r.eleven ? "Clé ElevenLabs enregistrée ✔ (coller pour la remplacer)" : "Clé ElevenLabs pour les voix ★ (gratuit : elevenlabs.io → API Keys)";
  } catch {}
}
async function saveVoice() {
  const body = { voice: $("vx").value, pitch: +$("vx-pitch").value, rate: +$("vx-rate").value };
  if ($("vx-key").value.trim()) body.eleven_key = $("vx-key").value.trim();
  await api("/api/voices", { method: "POST", body: JSON.stringify(body) });
  $("vx-key").value = ""; loadVoices();
}
$("vx-save").onclick = saveVoice;
$("vx-pitch").onchange = $("vx-rate").onchange = saveVoice;
$("btn-cfg").addEventListener("click", loadVoices);
$("vx").onchange = () => saveVoice().then(() => $("vx-test").click());
$("vx-test").onclick = () => speak("Bonsoir monsieur. Tous les systèmes sont opérationnels. Je reste à votre disposition.");
$("br-add").onclick = async () => {
  const id = $("br-id").value, key = $("br-key").value.trim(); if (!id || !key) return;
  $("cfg-out").textContent = "Test de la clé…";
  const r = await api("/api/providers", { method: "POST", body: JSON.stringify({ id, key }) });
  $("cfg-out").textContent = r.ok ? "✔ " + PRESETS[id].name + " ajoutée à la cascade." : "✖ " + r.error;
  if (r.ok) { $("br-key").value = ""; loadBrains(); poll(); }
};
$("g-save").onclick = async () => {
  const r = await api("/api/google", { method: "POST", body: JSON.stringify({ json: $("g-json").value.trim() }) });
  $("g-status").textContent = r.ok ? "✔ Fichier enregistré. Cliquez CONNECTER GOOGLE." : "✖ " + r.error;
  if (r.ok) $("g-json").value = "";
};
$("g-connect").onclick = () => {
  if (!/^(127\.0\.0\.1|localhost)$/.test(location.hostname)) { $("g-status").textContent = "La connexion Google se fait depuis le PC (http://127.0.0.1:8765)."; return; }
  window.open("/api/google/auth", "_blank");
  const t = setInterval(async () => { await gStatus(); if ($("g-status").textContent.startsWith("✔ Google")) clearInterval(t); }, 3000);
};
$("cfg-save").onclick = async () => {
  $("cfg-out").textContent = "Vérification de la clé…";
  try {
    const r = await api("/api/config", { method: "POST", body: JSON.stringify({ anthropic_key: $("cfg-key").value.trim(), claude_model: $("cfg-model").value }) });
    $("cfg-out").textContent = r.ok ? (r.has_key ? "✔ Claude activé (" + r.model + ")." : r.has_groq ? "✔ Clé Groq valide, cerveau gratuit activé." : "Enregistré.") : "✖ Clé refusée : " + r.error;
    if (r.ok) { $("cfg-key").value = ""; poll(); }
  } catch (e) { $("cfg-out").textContent = "Erreur : " + e.message; }
};

// ---------- Conversations vocales lancées sur le PC (« Hey Jarvis ») ----------
let lastEvt = -1;
async function pollEvents() {
  if (SOLO) return;
  try {
    const r = await api("/api/events?after=" + Math.max(lastEvt, 0));
    if (lastEvt < 0) { lastEvt = r.last; return; }
    for (const e of r.events) {
      lastEvt = e.id;
      if (e.type === "state") setState(e.state === "idle" ? "" : e.state);
      if (e.type === "user") line(e.text, "user");
      if (e.type === "reply" || e.type === "confirm") handle(e.res, false);
      if (e.type === "idea") line("💡 Idée de nouvelle compétence : " + e.text + " — dites « crée cette compétence » pour que je l'apprenne.", "log");
    }
  } catch {}
}
setInterval(pollEvents, 1500); pollEvents();

window.jarvis = { send, line, api, speak };

// ---------- Appli installable + fonctionnement sans le PC ----------
if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});

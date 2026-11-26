// JARVIS — contrôle par les mains v3 (caméra + MediaPipe, local)
// Bouton ✋ : OFF → HUD (pilote l'interface) → PC (pilote Windows) → OFF
const V = "/static/vendor/mediapipe";
const MODEL_LOCAL = `${V}/hand_landmarker.task`;
const MODEL_WEB = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const GESTES = [
  ["point", "☝", "Curseur"], ["pinch", "🤏", "Clic · tenir = glisser"], ["rpinch", "🖕", "Clic droit (pouce-majeur)"],
  ["vee", "✌", "Défiler"], ["fist", "✊", "STOP"], ["palm", "🖐", "Immobile = écoute · balayer = ◀ ▶"],
  ["thumb", "👍", "Pause musique"], ["three", "🤟", "Alt+Tab"],
];
const HOLD_MS = { fist: 500, thumb: 700, three: 700, palm: 1200 };
const BONES = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];

const btn = document.getElementById("btn-hands");
const cam = document.getElementById("cam");
document.getElementById("handfx")?.remove();
const cur = document.getElementById("cursor");
cur.innerHTML = `<svg viewBox="0 0 60 60"><circle class="r0" cx="30" cy="30" r="13"/><circle class="rh" cx="30" cy="30" r="22" pathLength="100"/><path class="tk" d="M30 2v8M30 50v8M2 30h8M50 30h8"/><circle class="dot" cx="30" cy="30" r="3"/></svg><b></b>`;
const curLabel = cur.querySelector("b"), ring = cur.querySelector(".rh");

// Panneau holographique
const ui = document.createElement("div");
ui.id = "hand-ui"; ui.hidden = true;
ui.innerHTML = `<div class="hu-head"><span class="hu-dot"></span><span class="hu-mode">MAINS</span><span class="hu-fps"></span></div>
<div class="hu-view"><canvas></canvas><div class="hu-msg"></div></div>
<div class="hu-list">${GESTES.map(([k, i, t]) => `<div class="hu-g" data-k="${k}"><i>${i}</i><span>${t}</span></div>`).join("")}</div>`;
document.body.appendChild(ui);
const view = ui.querySelector("canvas"), vctx = view.getContext("2d");
view.width = 320; view.height = 240;
const msg = ui.querySelector(".hu-msg"), fpsEl = ui.querySelector(".hu-fps"), modeEl = ui.querySelector(".hu-mode");
const chips = Object.fromEntries([...ui.querySelectorAll(".hu-g")].map((e) => [e.dataset.k, e]));

const MODES = ["off", "hud", "pc"];
let mode = "off", landmarker = null, stream = null, sx = 0.5, sy = 0.5, lastSend = 0, lastVT = -1;
let sm = null;                    // repères lissés
let votes = [], gesture = "none";
let pinch = null, rpinch = false, hold = { g: "", t: 0, fired: false };
let lastFire = 0, palmTrail = [], scrollY = null, scrollAcc = 0, lostSince = 0, seenAt = 0;
let frames = 0, fpsT = 0, flashT = 0, tgt = null, fpsNow = 30, lastDet = 0;

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const send = (body) => window.jarvis.api("/api/pointer", { method: "POST", body: JSON.stringify({ x: sx, y: sy, ...body }) }).catch(() => {});

async function load() {
  const { HandLandmarker, FilesetResolver } = await import(`${V}/vision_bundle.mjs`);
  const files = await FilesetResolver.forVisionTasks(V);
  const opts = (path, delegate) => ({ baseOptions: { modelAssetPath: path, delegate }, runningMode: "VIDEO", numHands: 1,
    minHandDetectionConfidence: 0.45, minHandPresenceConfidence: 0.45, minTrackingConfidence: 0.45 });
  for (const path of [MODEL_LOCAL, MODEL_WEB]) for (const d of ["GPU", "CPU"]) {
    try { return await HandLandmarker.createFromOptions(files, opts(path, d)); } catch {}
  }
  throw new Error("modèle de suivi des mains introuvable");
}

async function start() {
  try {
    ui.hidden = false; say("Initialisation…");
    landmarker ||= await load();
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 30 }, facingMode: "user" } });
    cam.srcObject = stream; await cam.play();
    cur.hidden = false; seenAt = performance.now(); requestAnimationFrame(loop);
    window.jarvis.line(mode === "pc" ? "Mains → souris du PC." : "Mains → interface Jarvis.", "log");
  } catch (e) { window.jarvis.line("Caméra / suivi des mains indisponible : " + e.message, "log"); setMode("off"); }
}
function stop() {
  if (pinch?.drag && mode === "pc") send({ action: "up" });
  pinch = null; sm = null; votes = [];
  stream?.getTracks().forEach((t) => t.stop()); stream = null;
  cur.hidden = true; ui.hidden = true;
}
let poll = null;
async function setMode(m) {
  const was = mode;
  if (pinch?.drag) send({ action: "up" });
  mode = m; btn.classList.toggle("on", m !== "off");
  btn.textContent = m === "pc" ? "🖱" : "✋";
  modeEl.textContent = m === "pc" ? "MAINS · TOUT LE PC" : "MAINS · INTERFACE";
  ui.classList.toggle("pc", m === "pc");
  if (m === "pc") {
    // Mode PC : la caméra est pilotée par le serveur → marche sur tout Windows, Jarvis réduit ou fermé
    stop(); ui.hidden = false; say("Démarrage de la caméra du PC…");
    const ctx2 = view.getContext("2d"); ctx2.fillStyle = "#02101a"; ctx2.fillRect(0, 0, view.width, view.height);
    try {
      const r = await window.jarvis.api("/api/hands", { method: "POST", body: JSON.stringify({ on: true }) });
      window.jarvis.line(r.reply, "log");
      if (r.error) throw new Error(r.error);
      say("Actif sur tout le PC — tu peux réduire Jarvis. Voyant en bas à droite de l'écran.");
      poll = setInterval(async () => {
        try {
          const st = await window.jarvis.api("/api/hands");
          fpsEl.textContent = st.fps + " IPS";
          for (const k in chips) chips[k].classList.toggle("on", k === st.gesture);
          ui.querySelector(".hu-dot").classList.toggle("live", st.running && st.gesture !== "none");
          if (!st.running) { say("Arrêté : " + (st.error || "")); clearInterval(poll); }
        } catch {}
      }, 400);
    } catch (e) {
      say("Mode PC indisponible : " + e.message + " — repli sur le mode navigateur.");
      if (!stream) start();
    }
    return;
  }
  if (was === "pc") {
    clearInterval(poll);
    await window.jarvis.api("/api/hands", { method: "POST", body: JSON.stringify({ on: false }) }).catch(() => {});
  }
  if (m === "off") stop(); else if (!stream) start();
}
btn.onclick = () => setMode(MODES[(MODES.indexOf(mode) + 1) % 3]);
function say(t) { msg.textContent = t; msg.hidden = !t; }

// ---------- Lecture de la main ----------
function classify(h) {
  const palm = dist(h[0], h[9]) || 1e-3;
  const ext = (tip, pip, mcp) => dist(h[tip], h[0]) > dist(h[pip], h[0]) * 1.08 && dist(h[tip], h[mcp]) / palm > 0.55;
  const f = [ext(8, 6, 5), ext(12, 10, 9), ext(16, 14, 13), ext(20, 18, 17)];
  const n = f.filter(Boolean).length;
  const thumbOut = dist(h[4], h[9]) / palm > 0.65 && dist(h[4], h[2]) / palm > 0.5;   // pouce écarté de la paume
  const thumbUp = thumbOut && h[4].y < h[2].y - palm * 0.35 && h[4].y < h[6].y;
  const pI = dist(h[4], h[8]) / palm, pM = dist(h[4], h[12]) / palm;
  if (pI < (gesture === "pinch" ? 0.45 : 0.32) && !f[2] && dist(h[8], h[5]) / palm > 0.45) return "pinch";
  if (pM < 0.3 && pI > 0.45 && f[0] && dist(h[12], h[9]) / palm > 0.5) return "rpinch";
  if (n === 0) return thumbUp ? "thumb" : "fist";
  if (n === 4) return thumbOut ? "palm" : "four";
  if (f[0] && f[1] && f[2] && !f[3]) return "three";
  if (f[0] && f[1] && !f[2] && !f[3]) return "vee";
  if (f[0] && !f[1] && !f[2]) return "point";
  return "other";
}
// vote sur les 5 dernières images : un geste doit être vu 3 fois pour compter (anti-tremblement)
function stable(g) {
  const nv = fpsNow >= 15 ? 5 : 3;
  votes.push(g); while (votes.length > nv) votes.shift();
  const c = {}; for (const v of votes) c[v] = (c[v] || 0) + 1;
  const [best, k] = Object.entries(c).sort((a, b) => b[1] - a[1])[0];
  if (k >= (nv >> 1) + 1) gesture = best;
  return gesture;
}

// ---------- Actions ----------
function act(a, extra = {}) {
  const X = sx * innerWidth, Y = sy * innerHeight;
  flash(a);
  if (a === "stop") { window.jarvis.hush?.(); send({ action: "stop" }); window.jarvis.line("✊ Stop.", "log"); return; }
  if (a === "listen") { document.getElementById("btn-mic")?.click(); return; }
  if (a === "playpause") { send({ action: "hotkey", keys: "playpause" }); return; }
  if (mode === "hud") {
    if (a === "click") {
      const el = document.elementFromPoint(X, Y);
      const t = el?.closest("button,input,textarea,select,a,[onclick],.pill") || el;
      t?.click?.(); t?.focus?.();
    } else if (a === "scroll") {
      let el = document.elementFromPoint(X, Y);
      while (el && el !== document.body && !(el.scrollHeight > el.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(el).overflowY))) el = el.parentElement;
      (el && el !== document.body ? el : document.scrollingElement).scrollBy({ top: -extra.amount * 60 });
    }
    return;
  }
  if (["click", "right", "down", "up"].includes(a)) send({ action: a });
  else if (a === "scroll") send({ action: "scroll", amount: extra.amount });
  else if (a === "back") send({ action: "hotkey", keys: "alt+left" });
  else if (a === "forward") send({ action: "hotkey", keys: "alt+right" });
  else if (a === "switch") send({ action: "hotkey", keys: "alt+tab" });
}
function flash(a) {
  const t = { click: "CLIC", right: "CLIC DROIT", down: "GLISSER", up: "DÉPOSÉ", stop: "STOP", listen: "J'ÉCOUTE", playpause: "LECTURE / PAUSE",
    back: "◀ PRÉCÉDENT", forward: "SUIVANT ▶", switch: "ALT+TAB" }[a];
  if (!t) return;
  curLabel.textContent = t; flashT = performance.now();
  ui.classList.remove("fire"); void ui.offsetWidth; ui.classList.add("fire");
}
function held(g, now) {
  if (hold.g !== g) { hold = { g, t: now, fired: false }; return 0; }
  if (hold.fired) return 1;
  const p = (now - hold.t) / HOLD_MS[g];
  if (p >= 1 && now - lastFire > 900) { hold.fired = true; lastFire = now; return 2; }
  return Math.min(p, 0.99);
}

// ---------- Dessin ----------
function drawView(h, g) {
  const W = view.width, H = view.height;
  vctx.save(); vctx.translate(W, 0); vctx.scale(-1, 1);
  vctx.filter = "grayscale(1) brightness(1.15) contrast(1.1)";
  vctx.drawImage(cam, 0, 0, W, H); vctx.filter = "none";
  vctx.restore();
  vctx.fillStyle = "rgba(0,40,60,.45)"; vctx.fillRect(0, 0, W, H);
  if (!h) return;
  const col = g === "fist" ? "#ff3d5a" : g === "pinch" ? "#4dffb5" : "#35e0ff";
  const P = (p) => [(1 - p.x) * W, p.y * H];
  vctx.shadowColor = col; vctx.shadowBlur = 10; vctx.strokeStyle = col; vctx.lineWidth = 2.5; vctx.lineCap = "round";
  vctx.beginPath(); for (const [a, b] of BONES) { const [x1, y1] = P(h[a]), [x2, y2] = P(h[b]); vctx.moveTo(x1, y1); vctx.lineTo(x2, y2); } vctx.stroke();
  vctx.fillStyle = "#fff";
  for (const i of [4, 8, 12, 16, 20]) { const [x, y] = P(h[i]); vctx.beginPath(); vctx.arc(x, y, 4, 0, 7); vctx.fill(); }
  vctx.shadowBlur = 0;
}

// ---------- Boucle ----------
function loop() {
  if (!stream) return;
  requestAnimationFrame(loop);
  // curseur interpolé à chaque image d'écran (fluide même si la caméra est lente)
  if (tgt) {
    const d = Math.hypot(tgt.x - sx, tgt.y - sy), k = d < 0.01 ? 0.18 : 0.32;
    sx += (tgt.x - sx) * k; sy += (tgt.y - sy) * k;
    cur.style.transform = `translate(${sx * innerWidth}px,${sy * innerHeight}px)`;
  }
  if (cam.readyState < 2 || cam.currentTime === lastVT) return;     // pas de nouvelle image : on ne recalcule pas
  lastVT = cam.currentTime;
  const now = performance.now();
  frames++; if (now - fpsT > 1000) { fpsEl.textContent = frames + " IPS"; fpsNow = frames; frames = 0; fpsT = now; }

  if (lostSince && now - lostSince > 4000 && now - lastDet < 250) return;   // personne : 4 analyses/s (économie CPU)
  lastDet = now;
  const raw = landmarker.detectForVideo(cam, now).landmarks?.[0];
  if (!raw) {
    sm = null; votes = []; gesture = "none"; tgt = null;
    if (!lostSince) lostSince = now;
    if (pinch && now - lostSince > 500) { if (pinch.drag) act("up"); pinch = null; }
    hold.g = ""; scrollY = null; palmTrail = [];
    say(now - seenAt > 2500 ? "Aucune main — lève la main face caméra, à 40-80 cm, bien éclairée" : "");
    drawView(null); paint("none", 0); return;
  }
  lostSince = 0; seenAt = now; say("");
  // lissage des repères (moins de tremblements, réactif sur les grands gestes)
  if (!sm) sm = raw.map((p) => ({ ...p }));
  else for (let i = 0; i < 21; i++) {
    const k = Math.min(0.85, 0.4 + Math.hypot(raw[i].x - sm[i].x, raw[i].y - sm[i].y) * 12);
    sm[i].x += (raw[i].x - sm[i].x) * k; sm[i].y += (raw[i].y - sm[i].y) * k; sm[i].z = raw[i].z;
  }
  const h = sm, g = stable(classify(h));
  drawView(h, g);

  // Curseur (bouge seulement en pointage / pince : pas de saut pendant les autres gestes)
  if (g === "point" || g === "pinch" || g === "rpinch") {
    const ref = g === "point" ? h[8] : { x: (h[4].x + h[8].x) / 2, y: (h[4].y + h[8].y) / 2 };
    const tx = Math.min(1, Math.max(0, ((1 - ref.x) - 0.2) / 0.6));
    const ty = Math.min(1, Math.max(0, (ref.y - 0.15) / 0.55));
    tgt = { x: tx, y: ty };
  }

  // Pince : clic court / glisser si tenu
  if (g === "pinch") {
    if (!pinch) pinch = { t: now, drag: false };
    else if (!pinch.drag && now - pinch.t > 400) { pinch.drag = true; act("down"); }
  } else if (pinch) { act(pinch.drag ? "up" : "click"); pinch = null; }

  if (g === "rpinch" && !rpinch && now - lastFire > 600) { rpinch = true; lastFire = now; act("right"); }
  if (g !== "rpinch") rpinch = false;

  // Défilement deux doigts
  if (g === "vee") {
    const y = (h[8].y + h[12].y) / 2;
    if (scrollY != null) { scrollAcc += (scrollY - y) * 45; const s = Math.trunc(scrollAcc); if (s) { scrollAcc -= s; act("scroll", { amount: s }); } }
    scrollY = y;
  } else { scrollY = null; scrollAcc = 0; }

  // Gestes tenus + balayage
  let prog = 0;
  if (g === "palm") {
    const wx = 1 - h[9].x;
    palmTrail.push([now, wx]); while (now - palmTrail[0][0] > 450) palmTrail.shift();
    const dx = wx - palmTrail[0][1];
    if (Math.abs(dx) > 0.2 && now - lastFire > 900) { lastFire = now; palmTrail = []; hold = { g: "palm", t: now, fired: true }; act(dx > 0 ? "forward" : "back"); }
    else {
      const xs = palmTrail.map((p) => p[1]);
      if (Math.max(...xs) - Math.min(...xs) > 0.05) hold = { g: "palm", t: now, fired: false };
      const r = held("palm", now); if (r === 2) act("listen"); else prog = r;
    }
  } else { palmTrail = []; }
  if (g === "fist" || g === "thumb" || g === "three") {
    const r = held(g, now);
    if (r === 2) act({ fist: "stop", thumb: "playpause", three: "switch" }[g]); else prog = r;
  } else if (g !== "palm") hold.g = g;

  paint(g, prog);
  if (mode === "pc" && (g === "point" || g === "pinch" || g === "rpinch") && now - lastSend > 40) { lastSend = now; send({ action: "move" }); }
}

function paint(g, prog) {
  cur.style.transform = `translate(${sx * innerWidth}px,${sy * innerHeight}px)`;
  cur.className = "g-" + g + (pinch ? " pinch" : "") + (pinch?.drag ? " drag" : "") + (performance.now() - flashT < 500 ? " fire" : "");
  ring.style.strokeDashoffset = 100 - (prog >= 1 ? 0 : prog * 100);
  if (performance.now() - flashT > 800) curLabel.textContent = prog > 0.05 && prog < 1 ? (GESTES.find((x) => x[0] === g)?.[2] || "").toUpperCase() : "";
  for (const k in chips) chips[k].classList.toggle("on", k === g);
  ui.querySelector(".hu-dot").classList.toggle("live", g !== "none");
}

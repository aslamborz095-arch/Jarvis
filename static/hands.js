// JARVIS — contrôle par les mains (caméra + MediaPipe, 100 % local)
// Bouton ✋ : OFF → HUD (pilote l'interface) → PC (pilote Windows) → OFF
// Gestes :
//   ☝ index levé ............ déplace le curseur
//   🤏 pince pouce-index ..... clic ; pince tenue 0,35 s = glisser (relâcher = déposer)
//   🤏 pince pouce-majeur .... clic droit
//   ✌ deux doigts haut/bas .. défilement
//   ✊ poing tenu ............ STOP (arrête Jarvis, la voix et l'autopilote)
//   🖐 main ouverte immobile . Jarvis écoute (micro)
//   🖐 balayage ← / → ....... précédent / suivant (Alt+←/→, page ou dossier)
//   👍 pouce levé ............ lecture / pause musique
//   🤟 trois doigts tenus .... changer de fenêtre (Alt+Tab)
const V = "/static/vendor/mediapipe";
const MODEL_LOCAL = `${V}/hand_landmarker.task`;
const MODEL_WEB = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const btn = document.getElementById("btn-hands");
const cam = document.getElementById("cam");
const fx = document.getElementById("handfx");
const ctx = fx.getContext("2d");
const cur = document.getElementById("cursor");
const MODES = ["off", "hud", "pc"];
const BONES = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];

let mode = "off", landmarker = null, stream = null, sx = 0.5, sy = 0.5, lastSend = 0;
// état des gestes
let pinch = null;          // {t, x, y, drag}
let rpinch = false;
let hold = { g: "", t: 0, fired: false };
let lastFire = 0, palmTrail = [], scrollY = null, scrollAcc = 0, lostSince = 0;

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const send = (body) => window.jarvis.api("/api/pointer", { method: "POST", body: JSON.stringify({ x: sx, y: sy, ...body }) }).catch(() => {});

async function load() {
  const { HandLandmarker, FilesetResolver } = await import(`${V}/vision_bundle.mjs`);
  const files = await FilesetResolver.forVisionTasks(V);
  const opts = (path) => ({ baseOptions: { modelAssetPath: path, delegate: "GPU" }, runningMode: "VIDEO", numHands: 1,
    minHandDetectionConfidence: 0.6, minTrackingConfidence: 0.6 });
  try { return await HandLandmarker.createFromOptions(files, opts(MODEL_LOCAL)); }
  catch { return await HandLandmarker.createFromOptions(files, opts(MODEL_WEB)); }
}

async function start() {
  try {
    landmarker ||= await load();
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" } });
    cam.srcObject = stream; await cam.play();
    cur.hidden = false; requestAnimationFrame(loop);
    window.jarvis.line((mode === "pc" ? "Mains → PC. " : "Mains → interface. ") +
      "☝ curseur · 🤏 clic (tenir = glisser) · pouce-majeur = clic droit · ✌ défiler · ✊ STOP · 🖐 immobile = écoute · 🖐 balayage = préc./suiv. · 👍 pause · 🤟 Alt+Tab", "log");
  } catch (e) { window.jarvis.line("Caméra / suivi des mains indisponible : " + e.message, "log"); setMode("off"); }
}
function stop() {
  if (pinch?.drag && mode === "pc") send({ action: "up" });
  pinch = null;
  stream?.getTracks().forEach((t) => t.stop()); stream = null;
  cur.hidden = true; ctx.clearRect(0, 0, fx.width, fx.height);
}
function setMode(m) {
  if (pinch?.drag && mode === "pc") send({ action: "up" });
  mode = m; btn.classList.toggle("on", m !== "off");
  btn.textContent = m === "pc" ? "🖱" : "✋";
  if (m === "off") stop(); else if (!stream) start();
  else window.jarvis.line(m === "pc" ? "Mains : PC." : "Mains : interface.", "log");
}
btn.onclick = () => setMode(MODES[(MODES.indexOf(mode) + 1) % 3]);

// ---------- Lecture de la main ----------
function read(h) {
  const palm = dist(h[0], h[9]) || 0.001;
  const up = (tip, pip) => dist(h[tip], h[0]) > dist(h[pip], h[0]) * 1.12;
  const f = [up(8, 6), up(12, 10), up(16, 14), up(20, 18)];         // index, majeur, annulaire, auriculaire
  const thumb = dist(h[4], h[5]) / palm > 0.75 && dist(h[4], h[17]) / palm > 1.1;
  const n = f.filter(Boolean).length;
  const pinchI = dist(h[4], h[8]) / palm;
  const pinchM = dist(h[4], h[12]) / palm;
  let g = "point";
  if (pinchI < (pinch ? 0.42 : 0.3)) g = "pinch";
  else if (pinchM < 0.3 && f[0]) g = "rpinch";
  else if (n === 0 && !thumb) g = "fist";
  else if (n === 0 && thumb && h[4].y < h[3].y && h[4].y < h[5].y - palm * 0.3) g = "thumb";
  else if (n === 4 && thumb) g = "palm";
  else if (f[0] && f[1] && f[2] && !f[3]) g = "three";
  else if (f[0] && f[1] && !f[2] && !f[3]) g = "vee";
  else if (f[0] && !f[1]) g = "point";
  else g = "other";
  return g;
}

const LABEL = { pinch: "CLIC", rpinch: "CLIC DROIT", fist: "STOP", thumb: "PAUSE", palm: "", three: "ALT+TAB", vee: "DÉFILER", point: "", other: "" };

// ---------- Actions (HUD ou PC) ----------
function act(a, extra = {}) {
  const X = sx * innerWidth, Y = sy * innerHeight;
  flash(a);
  if (a === "stop") {
    window.jarvis.hush?.();
    send({ action: "stop" });
    window.jarvis.line("✊ Stop.", "log");
    return;
  }
  if (a === "listen") { document.getElementById("btn-mic")?.click(); return; }
  if (a === "playpause") { send({ action: "hotkey", keys: "playpause" }); return; }
  if (mode === "hud") {
    if (a === "click") {
      const el = document.elementFromPoint(X, Y);
      (el?.closest("button,input,textarea,select,a,.pill") || el)?.click?.();
      el?.focus?.();
    } else if (a === "scroll") {
      let el = document.elementFromPoint(X, Y);
      while (el && el !== document.body && !(el.scrollHeight > el.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(el).overflowY))) el = el.parentElement;
      (el || document.scrollingElement).scrollBy({ top: -extra.amount * 60 });
    } else if (a === "back") history.length > 1 && history.back();
    return;
  }
  // mode PC
  if (a === "click" || a === "right" || a === "down" || a === "up") send({ action: a });
  else if (a === "scroll") send({ action: "scroll", amount: extra.amount });
  else if (a === "back") send({ action: "hotkey", keys: "alt+left" });
  else if (a === "forward") send({ action: "hotkey", keys: "alt+right" });
  else if (a === "switch") send({ action: "hotkey", keys: "alt+tab" });
}

let flashT = 0;
function flash(a) {
  const txt = { click: "CLIC", right: "CLIC DROIT", down: "GLISSER", up: "DÉPOSÉ", stop: "STOP", listen: "ÉCOUTE", playpause: "PAUSE",
    back: "◀ PRÉCÉDENT", forward: "SUIVANT ▶", switch: "ALT+TAB", scroll: "DÉFILER" }[a];
  if (!txt) return;
  cur.dataset.g = txt; flashT = performance.now();
  cur.classList.remove("fire"); void cur.offsetWidth; cur.classList.add("fire");
}

// geste à tenir (fist, thumb, palm immobile, three)
function held(g, ms, now) {
  if (hold.g !== g) { hold = { g, t: now, fired: false }; return false; }
  if (!hold.fired && now - hold.t > ms && now - lastFire > 900) { hold.fired = true; lastFire = now; return true; }
  return false;
}

// ---------- Boucle ----------
function loop() {
  if (!stream) return;
  if (fx.width !== innerWidth) fx.width = innerWidth;
  if (fx.height !== innerHeight) fx.height = innerHeight;
  ctx.clearRect(0, 0, fx.width, fx.height);
  const now = performance.now();
  const res = landmarker.detectForVideo(cam, now);
  const h = res.landmarks?.[0];
  if (!h) {
    // main perdue : relâcher un glisser en cours au bout de 0,5 s
    if (!lostSince) lostSince = now;
    if (pinch && now - lostSince > 500) { if (pinch.drag) act("up"); pinch = null; }
    hold.g = ""; scrollY = null; palmTrail = [];
    requestAnimationFrame(loop); return;
  }
  lostSince = 0;
  const W = fx.width, H = fx.height, P = (p) => [(1 - p.x) * W, p.y * H];
  const g = read(h);

  // Hologramme de la main (os + articulations)
  ctx.strokeStyle = g === "fist" ? "rgba(255,90,90,.7)" : "rgba(62,230,255,.45)"; ctx.lineWidth = 2;
  ctx.beginPath(); for (const [a, b] of BONES) { const [x1, y1] = P(h[a]), [x2, y2] = P(h[b]); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); } ctx.stroke();
  ctx.fillStyle = "rgba(62,230,255,.8)";
  for (const p of h) { const [x, y] = P(p); ctx.beginPath(); ctx.arc(x, y, 3, 0, 7); ctx.fill(); }

  // Curseur : suit l'index en pointage / pince (pas pendant les autres gestes → pas de saut)
  if (g === "point" || g === "pinch" || g === "rpinch") {
    const ref = g === "pinch" ? { x: (h[4].x + h[8].x) / 2, y: (h[4].y + h[8].y) / 2 } : h[8];
    const tx = Math.min(1, Math.max(0, ((1 - ref.x) - 0.15) / 0.7));
    const ty = Math.min(1, Math.max(0, (ref.y - 0.15) / 0.6));
    const k = Math.hypot(tx - sx, ty - sy) > 0.05 ? 0.5 : 0.25;      // rapide si grand geste, stable sinon
    sx += (tx - sx) * k; sy += (ty - sy) * k;
  }
  cur.style.left = sx * innerWidth + "px"; cur.style.top = sy * innerHeight + "px";

  // Pince pouce-index : clic court / glisser si tenu
  if (g === "pinch") {
    if (!pinch) pinch = { t: now, x: sx, y: sy, drag: false };
    else if (!pinch.drag && now - pinch.t > 350) { pinch.drag = true; act("down"); }
  } else if (pinch) {
    if (pinch.drag) act("up"); else act("click");
    pinch = null;
  }
  cur.classList.toggle("pinch", !!pinch);
  cur.classList.toggle("drag", !!pinch?.drag);

  // Clic droit
  if (g === "rpinch" && !rpinch && now - lastFire > 500) { rpinch = true; lastFire = now; act("right"); }
  if (g !== "rpinch") rpinch = false;

  // Défilement à deux doigts
  if (g === "vee") {
    const y = (h[8].y + h[12].y) / 2;
    if (scrollY != null) {
      scrollAcc += (scrollY - y) * 40;            // main qui monte = remonter
      const step = Math.trunc(scrollAcc);
      if (step) { scrollAcc -= step; act("scroll", { amount: step }); }
    }
    scrollY = y;
  } else { scrollY = null; scrollAcc = 0; }

  // Main ouverte : balayage ou immobilité
  if (g === "palm") {
    const wx = 1 - h[9].x;
    palmTrail.push([now, wx, h[9].y]);
    while (palmTrail.length && now - palmTrail[0][0] > 400) palmTrail.shift();
    const dx = wx - palmTrail[0][1];
    if (Math.abs(dx) > 0.22 && now - lastFire > 900) {
      lastFire = now; palmTrail = []; hold.fired = true;
      act(dx > 0 ? "forward" : "back");
    } else {
      const span = Math.max(...palmTrail.map((p) => p[1])) - Math.min(...palmTrail.map((p) => p[1]));
      if (span < 0.04 && held("palm", 1200, now)) act("listen");
      else if (span >= 0.04) hold.t = now;
    }
  } else palmTrail = [];

  // Gestes tenus
  if (g === "fist") { if (held("fist", 500, now)) act("stop"); }
  else if (g === "thumb") { if (held("thumb", 700, now)) act("playpause"); }
  else if (g === "three") { if (held("three", 700, now)) act("switch"); }
  else if (g !== "palm") hold.g = g;

  // Étiquette du geste
  if (now - flashT > 700) cur.dataset.g = LABEL[g] || "";

  // Mouvement de la souris du PC (~25 fois / s)
  if (mode === "pc" && (g === "point" || g === "pinch" || g === "rpinch") && now - lastSend > 40) {
    lastSend = now; send({ action: "move" });
  }
  requestAnimationFrame(loop);
}

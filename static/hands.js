// JARVIS — contrôle par les mains (caméra + MediaPipe, 100 % local)
// Bouton ✋ : OFF → HUD (pilote l'interface) → PC (pilote la souris de Windows) → OFF
const V = "/static/vendor/mediapipe";
const MODEL_LOCAL = `${V}/hand_landmarker.task`;
const MODEL_WEB = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const btn = document.getElementById("btn-hands");
const cam = document.getElementById("cam");
const fx = document.getElementById("handfx");
const ctx = fx.getContext("2d");
const cur = document.getElementById("cursor");
const MODES = ["off", "hud", "pc"];
let mode = "off", landmarker = null, stream = null, pinched = false, sx = 0.5, sy = 0.5, lastSend = 0;

async function load() {
  const { HandLandmarker, FilesetResolver } = await import(`${V}/vision_bundle.mjs`);
  const files = await FilesetResolver.forVisionTasks(V);
  const opts = (path) => ({ baseOptions: { modelAssetPath: path, delegate: "GPU" }, runningMode: "VIDEO", numHands: 1 });
  try { return await HandLandmarker.createFromOptions(files, opts(MODEL_LOCAL)); }
  catch { return await HandLandmarker.createFromOptions(files, opts(MODEL_WEB)); }
}

async function start() {
  try {
    landmarker ||= await load();
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    cam.srcObject = stream; await cam.play();
    cur.hidden = false; requestAnimationFrame(loop);
    window.jarvis.line(mode === "pc" ? "Mains : contrôle de la souris du PC." : "Mains : contrôle de l'interface. Pincez pour cliquer.", "log");
  } catch (e) { window.jarvis.line("Caméra / suivi des mains indisponible : " + e.message, "log"); setMode("off"); }
}
function stop() {
  stream?.getTracks().forEach((t) => t.stop()); stream = null;
  cur.hidden = true; ctx.clearRect(0, 0, fx.width, fx.height);
}
function setMode(m) {
  mode = m; btn.classList.toggle("on", m !== "off");
  btn.textContent = m === "pc" ? "🖱" : "✋";
  if (m === "off") stop(); else if (!stream) start();
  else window.jarvis.line(m === "pc" ? "Mains : souris du PC." : "Mains : interface.", "log");
}
btn.onclick = () => setMode(MODES[(MODES.indexOf(mode) + 1) % 3]);

function loop() {
  if (!stream) return;
  fx.width = innerWidth; fx.height = innerHeight;
  ctx.clearRect(0, 0, fx.width, fx.height);
  const res = landmarker.detectForVideo(cam, performance.now());
  const h = res.landmarks?.[0];
  if (h) {
    // Hologramme de la main
    ctx.fillStyle = "rgba(62,230,255,.55)";
    for (const p of h) { ctx.beginPath(); ctx.arc((1 - p.x) * fx.width, p.y * fx.height, 3, 0, 7); ctx.fill(); }
    // Curseur = index (lissé), zone utile réduite pour atteindre les bords
    const tx = Math.min(1, Math.max(0, ((1 - h[8].x) - 0.15) / 0.7));
    const ty = Math.min(1, Math.max(0, (h[8].y - 0.15) / 0.6));
    sx += (tx - sx) * 0.35; sy += (ty - sy) * 0.35;
    const X = sx * innerWidth, Y = sy * innerHeight;
    cur.style.left = X + "px"; cur.style.top = Y + "px";
    // Pincement pouce–index = clic
    const d = Math.hypot(h[4].x - h[8].x, h[4].y - h[8].y) / Math.hypot(h[0].x - h[9].x, h[0].y - h[9].y);
    const now = d < 0.28, click = now && !pinched;
    pinched = d < (pinched ? 0.4 : 0.28);
    cur.classList.toggle("pinch", pinched);
    if (mode === "hud" && click) {
      const el = document.elementFromPoint(X, Y);
      (el?.closest("button,input,.pill") || el)?.click?.();
      el?.focus?.();
    }
    if (mode === "pc" && (click || performance.now() - lastSend > 40)) {
      lastSend = performance.now();
      window.jarvis.api("/api/pointer", { method: "POST", body: JSON.stringify({ x: sx, y: sy, click }) }).catch(() => {});
    }
  }
  requestAnimationFrame(loop);
}

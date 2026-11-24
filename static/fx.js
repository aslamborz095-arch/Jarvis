// JARVIS — effets visuels : fond hexagonal, réacteur animé, courbe CPU
(() => {
  const FX = (window.FX = { state: "idle", level: 0, cpu: [] });
  const COLORS = { idle: [53, 224, 255], listening: [168, 244, 255], thinking: [255, 154, 60], speaking: [77, 255, 200] };
  let col = COLORS.idle.slice();
  const rgba = (a, c = col) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const DPR = Math.min(devicePixelRatio || 1, 2);
  const FPS = 40, STEP = 1000 / FPS;

  // ---------- Fond ----------
  const bg = document.getElementById("bg"), bx = bg.getContext("2d");
  let W, H, hexLayer, hexes = [], parts = [];
  function sizeBg() {
    W = innerWidth; H = innerHeight;
    bg.width = W * DPR; bg.height = H * DPR; bx.setTransform(DPR, 0, 0, DPR, 0, 0);
    hexLayer = document.createElement("canvas");
    hexLayer.width = W * DPR; hexLayer.height = H * DPR;
    const hx = hexLayer.getContext("2d"); hx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const r = 26, w = Math.sqrt(3) * r; hexes = [];
    hx.strokeStyle = "rgba(53,224,255,.07)"; hx.lineWidth = 1;
    for (let y = -r, row = 0; y < H + r; y += r * 1.5, row++)
      for (let x = (row % 2) * w / 2 - w; x < W + w; x += w) {
        hexes.push([x, y]);
        hx.beginPath();
        for (let i = 0; i < 6; i++) { const a = Math.PI / 3 * i + Math.PI / 6; hx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)); }
        hx.closePath(); hx.stroke();
      }
    parts = Array.from({ length: Math.min(90, (W * H) / 16000) }, () => ({
      x: Math.random() * W, y: Math.random() * H, v: 0.15 + Math.random() * 0.5, s: Math.random() * 1.6 + 0.3, a: Math.random() }));
  }
  const lit = [];
  function drawBg(t) {
    bx.clearRect(0, 0, W, H);
    bx.globalAlpha = 0.9; bx.drawImage(hexLayer, 0, 0, W, H); bx.globalAlpha = 1;
    if (Math.random() < 0.15) lit.push({ h: hexes[(Math.random() * hexes.length) | 0], life: 1 });
    for (let i = lit.length - 1; i >= 0; i--) {
      const L = lit[i], [x, y] = L.h; L.life -= 0.012;
      if (L.life <= 0) { lit.splice(i, 1); continue; }
      bx.beginPath();
      for (let k = 0; k < 6; k++) { const a = Math.PI / 3 * k + Math.PI / 6; bx.lineTo(x + 25 * Math.cos(a), y + 25 * Math.sin(a)); }
      bx.closePath(); bx.fillStyle = rgba(0.07 * L.life); bx.fill(); bx.strokeStyle = rgba(0.35 * L.life); bx.stroke();
    }
    // balayage radar
    const cx = W / 2, cy = H * 0.47, R = Math.hypot(W, H) * 0.6;
    if (bx.createConicGradient) {
      const g = bx.createConicGradient(t / 2600, cx, cy);
      g.addColorStop(0, rgba(0.09)); g.addColorStop(0.07, rgba(0)); g.addColorStop(1, rgba(0));
      bx.fillStyle = g; bx.beginPath(); bx.arc(cx, cy, R, 0, 7); bx.fill();
    }
    for (const p of parts) {
      p.y -= p.v * (FX.state === "thinking" ? 3 : 1); p.a += 0.02;
      if (p.y < -5) { p.y = H + 5; p.x = Math.random() * W; }
      bx.fillStyle = rgba(0.25 + 0.35 * Math.abs(Math.sin(p.a)));
      bx.fillRect(p.x, p.y, p.s, p.s);
    }
  }

  // ---------- Réacteur ----------
  const core = document.getElementById("core"), cx2 = core.getContext("2d");
  let S = 0;
  function sizeCore() {
    S = core.clientWidth; core.width = S * DPR; core.height = S * DPR; cx2.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  const wave = new Float32Array(120);
  function drawCore(t) {
    const c = cx2, m = S / 2, R = S / 2 * 0.96, st = FX.state;
    c.clearRect(0, 0, S, S);
    c.save(); c.translate(m, m); c.lineCap = "round";
    const sp = st === "thinking" ? 4 : st === "listening" ? 1.8 : 1;
    const ang = (t / 1000) * sp;

    // graduations extérieures
    c.save(); c.rotate(ang * 0.05);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2, big = i % 10 === 0, len = big ? R * 0.06 : R * 0.025;
      c.strokeStyle = rgba(big ? 0.85 : 0.35); c.lineWidth = big ? 2 : 1;
      c.beginPath(); c.moveTo(Math.cos(a) * R, Math.sin(a) * R); c.lineTo(Math.cos(a) * (R - len), Math.sin(a) * (R - len)); c.stroke();
    }
    c.restore();

    // arcs segmentés
    c.shadowColor = rgba(1); c.shadowBlur = 14;
    c.lineWidth = Math.max(2, R * 0.022);
    for (let k = 0; k < 3; k++) {
      const a0 = ang * 0.6 + (k * Math.PI * 2) / 3;
      c.strokeStyle = rgba(0.95); c.beginPath(); c.arc(0, 0, R * 0.87, a0, a0 + 1.15); c.stroke();
    }
    c.lineWidth = 1.5; c.setLineDash([R * 0.02, R * 0.03]);
    c.strokeStyle = rgba(0.55); c.beginPath(); c.arc(0, 0, R * 0.8, -ang * 0.4, -ang * 0.4 + Math.PI * 2); c.stroke();
    c.setLineDash([]);

    // balayage « analyse »
    if (st === "thinking") {
      c.lineWidth = R * 0.05; c.strokeStyle = rgba(0.9);
      c.beginPath(); c.arc(0, 0, R * 0.76, ang * 2.5, ang * 2.5 + 0.7); c.stroke();
    }

    // anneau d'onde (réagit à la voix)
    const lvl = FX.level;
    for (let i = 0; i < wave.length; i++) {
      let target = 0.04 + 0.02 * Math.sin(t / 700 + i * 0.4);
      if (st === "listening") target = 0.03 + lvl * (0.5 + 0.5 * Math.sin(i * 1.7 + t / 90)) * 0.35;
      else if (st === "speaking") target = 0.05 + 0.12 * Math.abs(Math.sin(t / 120 + i * 0.35)) * Math.abs(Math.sin(t / 330));
      else if (st === "thinking") target = 0.03 + 0.06 * Math.abs(Math.sin(t / 150 + i));
      wave[i] += (target - wave[i]) * 0.25;
      const a = (i / wave.length) * Math.PI * 2, r0 = R * 0.66, r1 = r0 + wave[i] * R;
      c.strokeStyle = rgba(0.75); c.lineWidth = Math.max(1.5, R * 0.012);
      c.beginPath(); c.moveTo(Math.cos(a) * r0, Math.sin(a) * r0); c.lineTo(Math.cos(a) * r1, Math.sin(a) * r1); c.stroke();
    }

    // points en orbite
    for (let k = 0; k < 3; k++) {
      const a = -ang * 1.3 + (k * Math.PI * 2) / 3;
      c.fillStyle = rgba(1); c.beginPath(); c.arc(Math.cos(a) * R * 0.6, Math.sin(a) * R * 0.6, R * 0.014, 0, 7); c.fill();
    }

    // bobines du réacteur
    c.save(); c.rotate(-ang * 0.25);
    for (let k = 0; k < 10; k++) {
      const a0 = (k / 10) * Math.PI * 2 + 0.06, a1 = a0 + Math.PI * 2 / 10 - 0.12;
      c.beginPath(); c.arc(0, 0, R * 0.52, a0, a1); c.arc(0, 0, R * 0.42, a1, a0, true); c.closePath();
      c.fillStyle = rgba(0.12 + 0.1 * Math.sin(t / 400 + k)); c.fill();
      c.strokeStyle = rgba(0.8); c.lineWidth = 1.2; c.stroke();
    }
    c.restore();

    // triangle intérieur
    c.save(); c.rotate(ang * 0.15);
    c.strokeStyle = rgba(0.5); c.lineWidth = 1.5; c.beginPath();
    for (let k = 0; k < 3; k++) { const a = (k / 3) * Math.PI * 2 - Math.PI / 2; c.lineTo(Math.cos(a) * R * 0.38, Math.sin(a) * R * 0.38); }
    c.closePath(); c.stroke(); c.restore();

    // cœur lumineux
    const pulse = 1 + (st === "speaking" ? 0.08 : 0.04) * Math.sin(t / (st === "idle" ? 700 : 160)) + lvl * 0.15;
    const g = c.createRadialGradient(0, 0, 0, 0, 0, R * 0.34 * pulse);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.25, rgba(0.95));
    g.addColorStop(0.6, rgba(0.25)); g.addColorStop(1, rgba(0));
    c.shadowBlur = 40; c.fillStyle = g; c.beginPath(); c.arc(0, 0, R * 0.34 * pulse, 0, 7); c.fill();
    c.restore();
  }

  // ---------- Courbe CPU ----------
  const sp = document.getElementById("spark"), sx = sp.getContext("2d");
  FX.pushCpu = (v) => { FX.cpu.push(v); if (FX.cpu.length > 40) FX.cpu.shift(); drawSpark(); };
  function drawSpark() {
    const w = sp.clientWidth, h = sp.clientHeight; if (!w) return;
    sp.width = w * DPR; sp.height = h * DPR; sx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const d = FX.cpu, n = 40; sx.clearRect(0, 0, w, h);
    sx.beginPath();
    d.forEach((v, i) => sx.lineTo(w - (d.length - 1 - i) * (w / (n - 1)), h - (v / 100) * (h - 4) - 2));
    sx.strokeStyle = "#35e0ff"; sx.lineWidth = 1.5; sx.shadowColor = "#35e0ff"; sx.shadowBlur = 6; sx.stroke();
    sx.lineTo(w, h); sx.lineTo(w - (d.length - 1) * (w / (n - 1)), h); sx.closePath();
    const g = sx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, "rgba(53,224,255,.25)"); g.addColorStop(1, "rgba(53,224,255,0)");
    sx.fillStyle = g; sx.shadowBlur = 0; sx.fill();
  }

  // ---------- Boucle ----------
  let last = 0;
  function loop(t) {
    requestAnimationFrame(loop);
    if (document.hidden || t - last < STEP) return;
    last = t;
    const target = COLORS[FX.state] || COLORS.idle;
    for (let i = 0; i < 3; i++) col[i] += (target[i] - col[i]) * 0.08;
    if (!document.body.classList.contains("fx3d")) { drawBg(t); drawCore(t); }
  }
  addEventListener("resize", () => { sizeBg(); sizeCore(); drawSpark(); });
  sizeBg(); sizeCore(); requestAnimationFrame(loop);
})();

// JARVIS — réacteur holographique 3D (three.js, 100 % local) avec lueur (bloom), anneaux gyroscopiques,
// onde vocale, nuée de particules et sol holographique. Repli automatique sur le rendu 2D si WebGL est absent.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const FX = window.FX || (window.FX = { state: "idle", level: 0 });
const MOBILE = matchMedia("(max-width:820px)").matches;
const LOW = MOBILE || (navigator.hardwareConcurrency || 4) <= 4;
const STATE_COL = { idle: 0x35e0ff, listening: 0xbaf6ff, thinking: 0xff9a3c, speaking: 0x4dffc8 };

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false, powerPreference: "high-performance" });
} catch { throw new Error("WebGL indisponible"); }
renderer.setPixelRatio(Math.min(devicePixelRatio, LOW ? 1 : 1.5));
renderer.setClearColor(0x010409, 1);
renderer.domElement.id = "scene";
document.body.prepend(renderer.domElement);
document.body.classList.add("fx3d");

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x010409, 0.045);
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
camera.position.set(0, 0.4, 10);

const accent = new THREE.Color(STATE_COL.idle);
const mats = [];   // matériaux qui prennent la couleur de l'état
const add = (m) => (mats.push(m), m);

// ---------- Réacteur ----------
const reactor = new THREE.Group();
scene.add(reactor);

// cœur + halo
const glowTex = (() => {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
})();
const core = new THREE.Mesh(new THREE.SphereGeometry(0.42, 32, 32), new THREE.MeshBasicMaterial({ color: 0xffffff }));
reactor.add(core);
const halo = new THREE.Sprite(add(new THREE.SpriteMaterial({ map: glowTex, color: accent, transparent: true, opacity: 0.6, depthWrite: false, blending: THREE.AdditiveBlending })));
halo.scale.setScalar(3.2); reactor.add(halo);

const ico = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.85, 1)),
  add(new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.55 })));
reactor.add(ico);

// bobines (10 segments)
const coils = new THREE.Group();
for (let i = 0; i < 10; i++) {
  const a = (i / 10) * Math.PI * 2;
  const m = new THREE.Mesh(new THREE.TorusGeometry(1.22, 0.11, 6, 12, (Math.PI * 2) / 10 - 0.12),
    add(new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.75 })));
  m.rotation.z = a + 0.06; coils.add(m);
}
reactor.add(coils);

// onde vocale (barres radiales)
const BARS = 120;
const bars = new THREE.InstancedMesh(new THREE.BoxGeometry(0.018, 1, 0.018),
  add(new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.9 })), BARS);
reactor.add(bars);
const wave = new Float32Array(BARS), dummy = new THREE.Object3D();

// anneaux
const ring = (r, tube, arc, op) => new THREE.Mesh(new THREE.TorusGeometry(r, tube, 6, 160, arc),
  add(new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: op })));
const ringA = ring(1.75, 0.012, Math.PI * 2, 0.5); reactor.add(ringA);
const arcs = new THREE.Group();
for (let k = 0; k < 3; k++) { const a = ring(2.05, 0.035, 1.2, 0.95); a.rotation.z = (k * Math.PI * 2) / 3; arcs.add(a); }
reactor.add(arcs);
const scan = ring(1.92, 0.07, 0.8, 0.0); reactor.add(scan);   // balayage « analyse »

// graduations
const TICKS = 120;
const ticks = new THREE.InstancedMesh(new THREE.BoxGeometry(0.012, 1, 0.012),
  add(new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.55 })), TICKS);
for (let i = 0; i < TICKS; i++) {
  const a = (i / TICKS) * Math.PI * 2, big = i % 10 === 0, l = big ? 0.22 : 0.09, r = 2.45 - l / 2;
  dummy.position.set(Math.cos(a) * r, Math.sin(a) * r, 0); dummy.rotation.set(0, 0, a - Math.PI / 2);
  dummy.scale.set(big ? 2 : 1, l, 1); dummy.updateMatrix(); ticks.setMatrixAt(i, dummy.matrix);
}
reactor.add(ticks);

// anneaux gyroscopiques (profondeur 3D)
const gyro1 = ring(2.75, 0.01, Math.PI * 2, 0.35); gyro1.rotation.x = 1.25; reactor.add(gyro1);
const gyro2 = ring(2.95, 0.008, Math.PI * 2, 0.25); gyro2.rotation.y = 1.1; reactor.add(gyro2);
const sats = [];
for (let k = 0; k < 3; k++) {
  const s = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 12), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  sats.push(s); reactor.add(s);
}

// ---------- Particules ----------
const N = LOW ? 900 : 2200;
const pg = new THREE.BufferGeometry(), pos = new Float32Array(N * 3), seed = new Float32Array(N);
for (let i = 0; i < N; i++) {
  const r = 3 + Math.random() * 9, a = Math.random() * Math.PI * 2;
  pos[i * 3] = Math.cos(a) * r; pos[i * 3 + 1] = (Math.random() - 0.5) * 6 * Math.random(); pos[i * 3 + 2] = Math.sin(a) * r - 2;
  seed[i] = Math.random();
}
pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
const dust = new THREE.Points(pg, add(new THREE.PointsMaterial({ color: accent, size: 0.035, transparent: true, opacity: 0.8,
  map: glowTex, depthWrite: false, blending: THREE.AdditiveBlending })));
scene.add(dust);

// ---------- Sol holographique ----------
const grid = new THREE.GridHelper(80, 80, 0x35e0ff, 0x35e0ff);
grid.material.transparent = true; grid.material.opacity = 0.12; grid.position.y = -3.6;
scene.add(grid);

// ---------- Post-traitement : lueur ----------
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), LOW ? 0.7 : 0.85, 0.4, 0.22);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ---------- Placement : le réacteur 3D suit le bouton #reactor de l'interface ----------
function place() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h); composer.setSize(w, h);
  bloom.resolution.set(w / (LOW ? 3 : 2), h / (LOW ? 3 : 2));
  camera.aspect = w / h; camera.updateProjectionMatrix();
  const el = document.getElementById("reactor");
  if (!el) return;
  const r = el.getBoundingClientRect();
  const ndc = new THREE.Vector3(((r.left + r.width / 2) / w) * 2 - 1, -((r.top + r.height / 2) / h) * 2 + 1, 0.5).unproject(camera);
  const dir = ndc.sub(camera.position).normalize(), t = -camera.position.z / dir.z;
  reactor.position.copy(camera.position).add(dir.multiplyScalar(t));
  // taille : le diamètre 3D (≈6.2) correspond à la taille du bouton
  const dist = camera.position.distanceTo(reactor.position);
  const worldH = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * dist;
  reactor.scale.setScalar((r.height / h) * worldH / 5.6);
}
addEventListener("resize", place);
setTimeout(place, 50); setTimeout(place, 3200);

// ---------- Parallaxe (souris / gyroscope) ----------
let px = 0, py = 0;
addEventListener("pointermove", (e) => { px = e.clientX / innerWidth - 0.5; py = e.clientY / innerHeight - 0.5; });
addEventListener("deviceorientation", (e) => { if (e.gamma != null) { px = e.gamma / 90; py = (e.beta - 45) / 90; } });

// ---------- Animation ----------
const tmpCol = new THREE.Color();
let last = 0, t0 = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  if (document.hidden || now - last < (LOW ? 33 : 22)) return;
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  const t = (now - t0) / 1000, st = FX.state || "idle", lvl = FX.level || 0;
  const sp = st === "thinking" ? 3.5 : st === "listening" ? 1.6 : 1;

  tmpCol.setHex(STATE_COL[st] || STATE_COL.idle); accent.lerp(tmpCol, 0.08);
  for (const m of mats) m.color.copy(accent);

  arcs.rotation.z += dt * 0.6 * sp; ringA.rotation.z -= dt * 0.15;
  coils.rotation.z -= dt * 0.22 * sp; ticks.rotation.z += dt * 0.04;
  ico.rotation.x += dt * 0.3 * sp; ico.rotation.y += dt * 0.45 * sp;
  gyro1.rotation.z += dt * 0.35 * sp; gyro2.rotation.x += dt * 0.25 * sp;
  scan.material.opacity += ((st === "thinking" ? 0.95 : 0) - scan.material.opacity) * 0.1; scan.rotation.z += dt * 4;
  sats.forEach((s, k) => { const a = -t * 1.2 * sp + (k * Math.PI * 2) / 3; s.position.set(Math.cos(a) * 1.55, Math.sin(a) * 1.55, 0); });

  const pulse = 1 + (st === "speaking" ? 0.1 : 0.05) * Math.sin(t * (st === "idle" ? 1.6 : 7)) + lvl * 0.25;
  core.scale.setScalar(pulse); halo.scale.setScalar(3.2 * pulse + lvl);
  bloom.strength = (LOW ? 0.7 : 0.85) + lvl * 0.7 + (st === "speaking" ? 0.3 : 0);

  for (let i = 0; i < BARS; i++) {
    let target = 0.06 + 0.03 * Math.sin(t * 1.4 + i * 0.4);
    if (st === "listening") target = 0.05 + lvl * (0.5 + 0.5 * Math.sin(i * 1.7 + t * 11)) * 0.55;
    else if (st === "speaking") target = 0.08 + 0.22 * Math.abs(Math.sin(t * 8 + i * 0.35)) * Math.abs(Math.sin(t * 3));
    else if (st === "thinking") target = 0.05 + 0.1 * Math.abs(Math.sin(t * 6 + i));
    wave[i] += (target - wave[i]) * 0.25;
    const a = (i / BARS) * Math.PI * 2, r = 1.5 + wave[i] / 2;
    dummy.position.set(Math.cos(a) * r, Math.sin(a) * r, 0); dummy.rotation.set(0, 0, a - Math.PI / 2);
    dummy.scale.set(1, wave[i], 1); dummy.updateMatrix(); bars.setMatrixAt(i, dummy.matrix);
  }
  bars.instanceMatrix.needsUpdate = true;

  dust.rotation.y += dt * 0.03 * sp;
  grid.position.z = (t * 0.8 * sp) % 1;

  reactor.rotation.y += ((px * 0.5) - reactor.rotation.y) * 0.05;
  reactor.rotation.x += ((py * 0.35) - reactor.rotation.x) * 0.05;
  camera.position.x += ((px * 0.8) - camera.position.x) * 0.03;
  camera.lookAt(0, 0, 0);
  composer.render();
}
requestAnimationFrame(frame);
window.FX3D = { place };

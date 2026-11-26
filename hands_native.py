"""Contrôle de TOUT Windows par les gestes des mains, en arrière-plan (caméra du PC, MediaPipe local).

Tourne dans le serveur Jarvis : marche même si la fenêtre Jarvis est fermée ou réduite.
Un petit voyant toujours visible (coin bas-droit) affiche le geste et l'anneau de maintien.
"""
import math, os, pathlib, threading, time

BASE = pathlib.Path(__file__).parent
MODEL = BASE / "static" / "vendor" / "mediapipe" / "hand_landmarker.task"
HOLD_MS = {"fist": 500, "thumb": 700, "three": 700, "palm": 1200}
KEYS = {"back": ("alt", "left"), "forward": ("alt", "right"), "switch": ("alt", "tab")}
LABEL = {"click": "CLIC", "right": "CLIC DROIT", "down": "GLISSER", "up": "DÉPOSÉ", "stop": "STOP", "listen": "J'ÉCOUTE",
         "playpause": "LECTURE / PAUSE", "back": "◀ PRÉCÉDENT", "forward": "SUIVANT ▶", "switch": "ALT+TAB"}
GNAME = {"point": "☝ CURSEUR", "pinch": "🤏 PINCE", "rpinch": "CLIC DROIT", "vee": "✌ DÉFILER", "fist": "✊ STOP",
         "palm": "🖐 MAIN OUVERTE", "thumb": "👍 PAUSE", "three": "🤟 ALT+TAB", "four": "", "other": "", "none": "AUCUNE MAIN"}
STATE = {"running": False, "error": None, "fps": 0, "gesture": "none", "last": "", "camera": None}
_stop = threading.Event()
_thread = None


def fetch_model():
    """Télécharge une fois le modèle de suivi des mains (usage hors ligne ensuite)."""
    if MODEL.exists() and MODEL.stat().st_size > 1_000_000:
        return
    try:
        import httpx
        r = httpx.get("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                      timeout=60, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 1_000_000:
            MODEL.write_bytes(r.content)
    except Exception:
        pass


def _d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def classify(h, prev):
    palm = _d(h[0], h[9]) or 1e-3
    ext = lambda t, p, m: _d(h[t], h[0]) > _d(h[p], h[0]) * 1.08 and _d(h[t], h[m]) / palm > 0.55
    f = [ext(8, 6, 5), ext(12, 10, 9), ext(16, 14, 13), ext(20, 18, 17)]
    n = sum(f)
    thumb_out = _d(h[4], h[9]) / palm > 0.65 and _d(h[4], h[2]) / palm > 0.5
    thumb_up = thumb_out and h[4].y < h[2].y - palm * 0.35 and h[4].y < h[6].y
    pi, pm = _d(h[4], h[8]) / palm, _d(h[4], h[12]) / palm
    if pi < (0.45 if prev == "pinch" else 0.32) and not f[2] and _d(h[8], h[5]) / palm > 0.45:
        return "pinch"
    if pm < 0.3 and pi > 0.45 and f[0] and _d(h[12], h[9]) / palm > 0.5:
        return "rpinch"
    if n == 0:
        return "thumb" if thumb_up else "fist"
    if n == 4:
        return "palm" if thumb_out else "four"
    if f[0] and f[1] and f[2] and not f[3]:
        return "three"
    if f[0] and f[1] and not f[2] and not f[3]:
        return "vee"
    if f[0] and not f[1] and not f[2]:
        return "point"
    return "other"


# ---------- Voyant toujours au premier plan ----------
class Badge:
    def __init__(self):
        self.text, self.color, self.prog, self.alive = "MAINS", "#35e0ff", 0.0, True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import tkinter as tk
        except Exception:
            return
        r = tk.Tk()
        r.overrideredirect(True); r.attributes("-topmost", True)
        try:
            r.attributes("-alpha", 0.88)
        except Exception:
            pass
        W, H = 230, 54
        r.geometry(f"{W}x{H}+{r.winfo_screenwidth() - W - 16}+{r.winfo_screenheight() - H - 60}")
        c = tk.Canvas(r, width=W, height=H, bg="#03121c", highlightthickness=1, highlightbackground="#0e4a5e")
        c.pack()

        def tick():
            if not self.alive:
                r.destroy(); return
            c.delete("all")
            col = self.color
            c.create_oval(10, 9, 46, 45, outline="#0e4a5e", width=3)
            if self.prog > 0:
                c.create_arc(10, 9, 46, 45, start=90, extent=-359.9 * min(1, self.prog), style="arc", outline=col, width=3)
            c.create_oval(24, 23, 32, 31, fill=col, outline="")
            c.create_text(58, 16, anchor="w", text="J.A.R.V.I.S · MAINS", fill="#5f8fa0", font=("Bahnschrift", 8))
            c.create_text(58, 35, anchor="w", text=self.text, fill=col, font=("Bahnschrift", 12, "bold"))
            r.attributes("-topmost", True)
            r.after(60, tick)
        tick()
        r.mainloop()

    def set(self, text, color, prog=0.0):
        self.text, self.color, self.prog = text, color, prog


def _run():
    import cv2, mediapipe as mp, pyautogui
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
    pyautogui.FAILSAFE, pyautogui.PAUSE = False, 0
    if not MODEL.exists():
        fetch_model()
    lm = HandLandmarker.create_from_options(HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.45, min_hand_presence_confidence=0.45, min_tracking_confidence=0.45))
    cam = None
    for idx in range(3):
        cam = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
        if cam.isOpened() and cam.read()[0]:
            STATE["camera"] = idx; break
        cam.release(); cam = None
    if cam is None:
        raise RuntimeError("aucune caméra disponible (fermée ailleurs ?)")
    # Optimisations : MJPG (décodage léger), 320×240 (le modèle travaille en 192/224 px de toute façon),
    # tampon d'1 image (pas de retard accumulé)
    cv2.setNumThreads(1)
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 320); cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cam.set(cv2.CAP_PROP_FPS, 30); cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    W, H = pyautogui.size()
    # Curseur fluide : un fil dédié déplace la souris à ~120 Hz vers la cible donnée par la caméra
    target = {"x": None, "y": None}
    try:
        import ctypes
        _setpos = ctypes.windll.user32.SetCursorPos
    except Exception:
        _setpos = lambda x, y: pyautogui.moveTo(x, y)

    def mover():
        cx = cy = None
        while not _stop.is_set():
            tx, ty = target["x"], target["y"]
            if tx is not None:
                if cx is None:
                    cx, cy = tx, ty
                d = math.hypot(tx - cx, ty - cy)
                k = 0.18 if d < 0.01 else 0.32          # stable de près, rapide sur les grands gestes
                cx += (tx - cx) * k; cy += (ty - cy) * k
                if d > 0.0008:
                    _setpos(int(cx * (W - 1)), int(cy * (H - 1)))
            time.sleep(0.008)
    threading.Thread(target=mover, daemon=True).start()
    badge = Badge()
    sx = sy = 0.5
    sm, votes, gesture = None, [], "none"
    pinch, rpinch, hold = None, False, {"g": "", "t": 0, "fired": False}
    last_fire, trail, scroll_y, scroll_acc, lost, frames, fps_t, flash_t = 0, [], None, 0.0, 0, 0, time.time(), 0
    t0 = time.time()

    def act(a, amount=0):
        nonlocal flash_t
        STATE["last"] = LABEL.get(a, a); flash_t = time.time()
        if a == "stop":
            try:
                import autopilot, voice
                autopilot.screen_stop(); voice.stop_local()
            except Exception:
                pass
        elif a == "listen":
            import wake
            wake.STATE["force"] = True
        elif a == "playpause":
            pyautogui.press("playpause")
        elif a == "click":
            pyautogui.click()
        elif a == "right":
            pyautogui.rightClick()
        elif a == "down":
            pyautogui.mouseDown()
        elif a == "up":
            pyautogui.mouseUp()
        elif a == "scroll":
            pyautogui.scroll(amount * 60)
        elif a in KEYS:
            pyautogui.hotkey(*KEYS[a])

    try:
        while not _stop.is_set():
            ok, img = cam.read()
            if not ok:
                time.sleep(0.05); continue
            now = time.time()
            if lost and now - lost > 4:      # personne devant la caméra : 4 analyses/s seulement (économie CPU)
                time.sleep(0.2)
            frames += 1
            if now - fps_t >= 1:
                STATE["fps"], frames, fps_t = frames, 0, now
            res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)),
                                      int((now - t0) * 1000))
            raw = res.hand_landmarks[0] if res.hand_landmarks else None
            if raw is None:
                sm, votes, gesture = None, [], "none"
                lost = lost or now
                target["x"] = None
                if pinch and now - lost > 0.5:
                    if pinch["drag"]:
                        act("up")
                    pinch = None
                hold["g"], scroll_y, trail = "", None, []
                STATE["gesture"] = "none"
                badge.set(STATE["last"] if now - flash_t < 0.8 else "AUCUNE MAIN", "#5f8fa0")
                continue
            lost = 0
            if sm is None:
                sm = [[p.x, p.y] for p in raw]
            else:
                for i, p in enumerate(raw):
                    k = min(0.9, (0.4 if STATE["fps"] >= 15 else 0.65) + math.hypot(p.x - sm[i][0], p.y - sm[i][1]) * 12)
                    sm[i][0] += (p.x - sm[i][0]) * k; sm[i][1] += (p.y - sm[i][1]) * k
            h = [type("P", (), {"x": a, "y": b}) for a, b in sm]
            n_v = 5 if STATE["fps"] >= 15 else 3            # moins d'images à voter quand le PC est lent
            votes = (votes + [classify(h, gesture)])[-n_v:]
            best = max(set(votes), key=votes.count)
            if votes.count(best) >= (n_v // 2 + 1):
                gesture = best
            g = gesture
            STATE["gesture"] = g

            if g in ("point", "pinch", "rpinch"):
                ref = h[8] if g == "point" else type("P", (), {"x": (h[4].x + h[8].x) / 2, "y": (h[4].y + h[8].y) / 2})
                tx = min(1, max(0, ((1 - ref.x) - 0.2) / 0.6)); ty = min(1, max(0, (ref.y - 0.15) / 0.55))
                sx, sy = tx, ty
                target["x"], target["y"] = tx, ty

            if g == "pinch":
                if not pinch:
                    pinch = {"t": now, "drag": False}
                elif not pinch["drag"] and now - pinch["t"] > 0.4:
                    pinch["drag"] = True; act("down")
            elif pinch:
                act("up" if pinch["drag"] else "click"); pinch = None

            if g == "rpinch" and not rpinch and now - last_fire > 0.6:
                rpinch, last_fire = True, now; act("right")
            if g != "rpinch":
                rpinch = False

            if g == "vee":
                y = (h[8].y + h[12].y) / 2
                if scroll_y is not None:
                    scroll_acc += (scroll_y - y) * 45
                    s = int(scroll_acc)
                    if s:
                        scroll_acc -= s; act("scroll", s)
                scroll_y = y
            else:
                scroll_y, scroll_acc = None, 0.0

            prog = 0.0

            def held(name):
                nonlocal hold, last_fire
                if hold["g"] != name:
                    hold = {"g": name, "t": now, "fired": False}; return 0.0
                if hold["fired"]:
                    return 1.0
                p = (now - hold["t"]) * 1000 / HOLD_MS[name]
                if p >= 1 and now - last_fire > 0.9:
                    hold["fired"], last_fire = True, now; return 2.0
                return min(p, 0.99)

            if g == "palm":
                wx = 1 - h[9].x
                trail = [t for t in trail + [(now, wx)] if now - t[0] <= 0.45]
                dx = wx - trail[0][1]
                if abs(dx) > 0.2 and now - last_fire > 0.9:
                    last_fire, trail = now, []
                    hold = {"g": "palm", "t": now, "fired": True}
                    act("forward" if dx > 0 else "back")
                else:
                    xs = [t[1] for t in trail]
                    if max(xs) - min(xs) > 0.05:
                        hold = {"g": "palm", "t": now, "fired": False}
                    r = held("palm")
                    if r == 2:
                        act("listen")
                    else:
                        prog = r
            else:
                trail = []
            if g in ("fist", "thumb", "three"):
                r = held(g)
                if r == 2:
                    act({"fist": "stop", "thumb": "playpause", "three": "switch"}[g])
                else:
                    prog = r
            elif g != "palm":
                hold["g"] = g

            color = {"fist": "#ff3d5a", "pinch": "#4dffb5", "thumb": "#ff9a3c", "three": "#ff9a3c"}.get(g, "#35e0ff")
            if pinch and pinch["drag"]:
                color = "#4dffb5"
            text = STATE["last"] if now - flash_t < 0.8 else (GNAME.get(g) or "MAIN DÉTECTÉE")
            badge.set(text, color, prog if prog < 1 else 0)
    finally:
        if pinch and pinch.get("drag"):
            pyautogui.mouseUp()
        badge.alive = False
        cam.release()
        lm.close()


def _ensure_deps():
    """Installe mediapipe + opencv au premier usage si la mise à jour ne l'a pas fait."""
    try:
        import cv2, mediapipe  # noqa
        return
    except ImportError:
        pass
    import subprocess, sys
    STATE["error"] = "installation de mediapipe… (1-3 min)"
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([exe, "-m", "pip", "install", "-q", "mediapipe", "opencv-python"], capture_output=True, text=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode:
        raise RuntimeError("pip : " + (r.stderr or r.stdout)[-300:])
    import importlib
    importlib.invalidate_caches()
    STATE["error"] = None


def _loop():
    STATE["running"], STATE["error"] = True, None
    try:
        _ensure_deps()
        _run()
    except Exception as e:
        STATE["error"] = str(e)[:200]
    finally:
        STATE["running"] = False


def start():
    global _thread
    if _thread and _thread.is_alive():
        return "Contrôle par les mains déjà actif."
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    time.sleep(3)
    if STATE["error"] and "installation" in STATE["error"]:
        return "Installation du module des mains en cours (1-3 min), réessaie ensuite."
    return f"Erreur mains : {STATE['error']}" if STATE["error"] else "Contrôle par les mains actif sur tout le PC."


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=3)
    return "Contrôle par les mains arrêté."


def hand_control(on: bool = True):
    """Active ou coupe le contrôle de tout le PC par les gestes des mains (caméra)."""
    return start() if on else stop()


SPECS = [("hand_control", "Active (on=true) ou coupe (on=false) le contrôle de tout le PC par les gestes des mains via la caméra.",
          {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]})]
FUNCS = {"hand_control": hand_control}

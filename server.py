import re
"""Serveur Jarvis : interface HUD + API (PC et téléphone)."""
import os, sys, pathlib, tempfile

# pythonw (démarrage caché) n'a pas de console : journal dans un fichier
if sys.stdout is None or sys.stderr is None:
    _log = open(pathlib.Path(__file__).parent / "jarvis.log", "a", encoding="utf-8")
    sys.stdout = sys.stderr = _log

from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).parent / ".env")

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, Response, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

import brain, tools, updater, stt, wake

TOKEN = os.getenv("JARVIS_TOKEN", "")
BASE = pathlib.Path(__file__).parent
app = FastAPI(title="JARVIS")


from fastapi.responses import JSONResponse
@app.exception_handler(Exception)
async def _oops(request, exc):
    # toujours du JSON lisible pour l'interface, jamais « Internal Server Error »
    import repair
    repair.capture(str(request.url.path), exc)
    return JSONResponse({"reply": f"Erreur interne : {str(exc)[:200]}", "log": []}, status_code=200)


def auth(t, req: Request = None):
    """Code exigé sauf sur le PC lui-même (accès direct, pas via Tailscale)."""
    if req is not None and req.client and req.client.host in ("127.0.0.1", "::1") \
            and "x-forwarded-for" not in req.headers and "tailscale-user-login" not in req.headers:
        return
    if TOKEN and t != TOKEN:
        raise HTTPException(401, "Code d'accès invalide")


class Msg(BaseModel):
    message: str

class Confirm(BaseModel):
    id: str
    approve: bool

class Pointer(BaseModel):
    x: float          # 0..1
    y: float          # 0..1
    click: bool = False
    action: str = ""  # move, click, right, down, up, scroll, hotkey, stop
    amount: int = 0
    keys: str = ""


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/chat")
def chat(request: Request, m: Msg, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return brain.ask(m.message)


@app.post("/api/confirm")
def confirm(request: Request, c: Confirm, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return brain.resume(c.id, c.approve)


@app.get("/api/status")
def status(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    net = brain.online()
    return {
        "online": net,
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")) and net,
        "groq": net and any(p["status"] == "ok" for p in __import__("providers").state()),
        "brains": __import__("providers").state(),
        "local": brain.ollama_ok(),
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "battery": bat.percent if bat else None,
        "plugged": bat.power_plugged if bat else None,
        "version": (updater.current() or "")[:7],
        "update": updater.STATE["status"],
        "wake": wake.STATE["enabled"],
        "wake_mic": wake.STATE.get("device"),
        "wake_level": wake.STATE.get("level"),
        "wake_score": wake.STATE.get("score"),
        "wake_error": wake.STATE["error"],
        "wake_dead": wake.STATE.get("mic_dead"),
        "wake_probe": wake.STATE.get("probe"),
        "wake_heard": wake.STATE.get("heard"),
        "mic_fix": wake.STATE.get("mic_fix"),
        "autopilot": {k: __import__("autopilot").STATE[k] for k in ("running", "goal", "step", "last")},
    }


@app.get("/api/top")
def top(request: Request, x_jarvis_token: str = Header("")):
    """Programmes qui consomment le plus de mémoire (diagnostic PC lent)."""
    auth(x_jarvis_token, request)
    agg = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            n = p.info["name"]; agg[n] = agg.get(n, 0) + p.info["memory_info"].rss
        except Exception:
            pass
    return [{"name": n, "mo": round(v / 2**20)} for n, v in sorted(agg.items(), key=lambda x: -x[1])[:12]]


@app.post("/api/autopilot/stop")
def autopilot_stop(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return {"reply": __import__("autopilot").screen_stop()}


class EvoIn(BaseModel):
    name: str = ""
    approve: bool = True


@app.get("/api/evolution")
def evolution(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import evolve
    return {"state": evolve.STATE, "pending": [{k: v for k, v in p.items() if k != "code"} for p in evolve.pending()],
            "journal": evolve._read(evolve.JOURNAL, [])[-20:], "metrics": __import__("metrics").summary()}


class SuggestIn(BaseModel):
    key: str
    approve: bool = True


@app.post("/api/suggest")
def suggest(s: SuggestIn, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return {"reply": __import__("anticipate").decide(s.key, s.approve)}


@app.get("/api/missions")
def missions_view(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return {"missions": __import__("missions")._read()[-10:], "projects": __import__("projects")._read()}


@app.get("/api/metrics")
def metrics_view(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return __import__("metrics").summary()


@app.post("/api/evolution/run")
def evolution_run(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import evolve, threading
    threading.Thread(target=evolve.evolve_now, daemon=True).start()
    return {"ok": True}


@app.post("/api/evolution/apply")
def evolution_apply(e: EvoIn, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import evolve
    return {"reply": evolve.evolution_apply(e.name) if e.approve else evolve.evolution_reject(e.name)}


@app.get("/api/events")
def events(request: Request, after: int = 0, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    return {"events": wake.events_after(after), "last": wake._counter[0]}


@app.post("/api/update")
def update_now(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import threading
    changed = updater.check_and_apply(restart=False)
    if changed:
        threading.Timer(2, updater._restart).start()
    return {"changed": changed, "status": updater.STATE["status"]}


@app.get("/api/mics")
def mics(request: Request):
    auth("", request)
    import sounddevice as sd
    return [{"id": i, "name": d["name"], "default": i == sd.default.device[0]}
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


@app.get("/api/log")
def log_tail(request: Request, n: int = 80):
    auth("", request)   # PC uniquement
    p = BASE / "jarvis.log"
    return {"log": "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]) if p.exists() else ""}


@app.get("/tableau")
def tableau_page():
    return FileResponse(BASE / "static" / "tableau.html")


@app.get("/api/tableau")
def tableau(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import proactive
    return proactive.dashboard()


@app.get("/api/briefing")
def briefing(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import proactive
    return {"reply": proactive.spoken_briefing()}


@app.get("/api/voices")
def voices(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import voice
    st = voice.settings()
    return {"voices": voice.VOICES, "current": voice.current(), "pitch": st["pitch"], "rate": st["rate"], "eleven": bool(st["eleven_key"])}


class VoiceIn(BaseModel):
    voice: str = ""
    pitch: int | None = None
    rate: int | None = None
    eleven_key: str | None = None


@app.post("/api/voices")
def voice_set(v: VoiceIn, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import voice
    if v.voice in voice.VOICES:
        voice.set_voice(v.voice)
    voice.save_settings(pitch=v.pitch, rate=v.rate, eleven_key=(v.eleven_key.strip() if v.eleven_key else None))
    voice._eleven_off[0] = 0
    return {"current": voice.current(), **{k: x for k, x in voice.settings().items() if k != "eleven_key"}}


@app.get("/api/tts")
def tts(request: Request, t: str = "", v: str = "", x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import voice
    f = voice.tts(t, v or None)
    if not f:
        return Response(status_code=503)
    return FileResponse(f, media_type="audio/mpeg")


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...), x_jarvis_token: str = Header("")):
    """Reconnaissance vocale locale (fonctionne hors ligne)."""
    auth(x_jarvis_token, request)
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(await audio.read())
    import asyncio
    text = await asyncio.to_thread(stt.transcribe, f.name)
    os.unlink(f.name)
    return {"text": text}


class Config(BaseModel):
    anthropic_key: str = ""
    groq_key: str = ""
    claude_model: str = ""


def _set_env(key, value):
    p = BASE / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    lines = [l for l in lines if not l.startswith(key + "=")] + [f"{key}={value}"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


@app.post("/api/config")
def config(c: Config, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    if c.claude_model:
        _set_env("CLAUDE_MODEL", c.claude_model.strip())
        brain.CLAUDE_MODEL = c.claude_model.strip()
    if c.anthropic_key:
        key = c.anthropic_key.strip()
        try:
            import anthropic
            anthropic.Anthropic(api_key=key).messages.create(
                model=brain.CLAUDE_MODEL, max_tokens=5, messages=[{"role": "user", "content": "ok"}])
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
        _set_env("ANTHROPIC_API_KEY", key)
    if c.groq_key:
        import providers
        providers.add("groq", c.groq_key)
    return {"ok": True, "has_key": bool(os.getenv("ANTHROPIC_API_KEY")), "has_groq": bool(os.getenv("GROQ_API_KEY")),
            "model": brain.CLAUDE_MODEL}


class GClient(BaseModel):
    json: str


@app.get("/api/google")
def google_status(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import google_apps
    return google_apps.status()


@app.post("/api/google")
def google_client(g: GClient, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import google_apps
    try:
        google_apps.save_client(g.json)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True}


@app.get("/api/google/auth")
def google_auth(request: Request):
    auth("", request)   # uniquement depuis le PC
    import google_apps
    return RedirectResponse(google_apps.auth_url())


@app.get("/api/google/callback")
def google_callback(request: Request, code: str = "", error: str = ""):
    auth("", request)
    import google_apps
    if error or not code:
        return HTMLResponse(f"<h2>Connexion Google annulée : {error}</h2>")
    google_apps.callback(code)
    try:
        import memory_ext, threading
        threading.Thread(target=memory_ext.offload, daemon=True).start()
    except Exception:
        pass
    return HTMLResponse("<body style='background:#010409;color:#35e0ff;font-family:sans-serif;text-align:center;padding-top:20vh'>"
                        "<h1>✔ Google connecté à Jarvis</h1><p>Vous pouvez fermer cet onglet.</p></body>")


class Brain(BaseModel):
    id: str
    key: str
    model: str = ""


@app.get("/api/providers")
def providers_list(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import providers
    return {"active": providers.state(), "presets": providers.PRESETS, "claude": bool(os.getenv("ANTHROPIC_API_KEY"))}


@app.post("/api/providers")
def providers_add(b: Brain, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import providers
    p = providers.PRESETS.get(b.id)
    if not p:
        return {"ok": False, "error": "Fournisseur inconnu"}
    test = {"id": b.id, "base": p["base"], "model": b.model or p["model"], "key": b.key.strip()}
    try:
        providers.call(test, [{"role": "user", "content": "Réponds juste OK."}], None, max_tokens=5)
    except providers.ProviderError as e:
        if e.status in (401, 403):
            why = re.sub(r"\s+", " ", str(e))[-220:]
            return {"ok": False, "error": f"Clé refusée ({e.status}) : {why}"}
        if e.status != 429:   # 429 = clé valide mais quota momentanément atteint
            return {"ok": False, "error": str(e)[:200]}
    providers.add(b.id, b.key, b.model)
    return {"ok": True, "active": providers.state()}


@app.delete("/api/providers/{pid}")
def providers_del(pid: str, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import providers
    providers.remove(pid)
    return {"ok": True, "active": providers.state()}


class SyncIn(BaseModel):
    notes: list = []
    history: list = []


@app.get("/api/sync")
def sync_get(request: Request, x_jarvis_token: str = Header("")):
    """Mémoire commune : le téléphone récupère notes + conversation (+ clé Groq pour le mode autonome)."""
    auth(x_jarvis_token, request)
    import providers
    g = next((p for p in providers.load() if p["id"] == "groq"), None)
    return {"notes": tools.load_notes(), "history": brain.HISTORY[-30:], "groq_key": g["key"] if g else os.getenv("GROQ_API_KEY", ""),
            "brains": [{k: p[k] for k in ("id", "base", "model", "key")} for p in providers.load()]}


@app.post("/api/sync")
def sync_post(d: SyncIn, request: Request, x_jarvis_token: str = Header("")):
    """Le téléphone renvoie ce qu'il a appris et dit en mode autonome."""
    auth(x_jarvis_token, request)
    tools.merge_notes(d.notes)
    for m in d.history:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            brain.HISTORY.append({"role": m["role"], "content": m["content"][:4000]})
    del brain.HISTORY[:-60]
    brain.save_history()
    return {"ok": True}


@app.get("/sw.js")
def service_worker():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


class Pair(BaseModel):
    host: str
    code: str = ""


@app.get("/api/phone")
def phone_status(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import phone
    return phone.status()


@app.post("/api/phone")
def phone_link(p: Pair, request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import phone
    if p.host.lower() == "usb":
        out = phone.usb_to_wifi()
    else:
        out = phone.pair(p.host, p.code) if p.code else phone.connect(p.host)
    return {"output": out, **phone.status()}


HAND_KEYS = {"alt+tab": ("alt", "tab"), "alt+left": ("alt", "left"), "alt+right": ("alt", "right"),
             "win+tab": ("win", "tab"), "win+d": ("win", "d"), "esc": ("esc",), "playpause": ("playpause",)}


@app.post("/api/pointer")
def pointer(request: Request, p: Pointer, x_jarvis_token: str = Header("")):
    """Contrôle du PC par les gestes des mains (caméra)."""
    auth(x_jarvis_token, request)
    a = p.action or ("click" if p.click else "move")
    import hands_native
    if hands_native.STATE["running"] and a != "stop":
        return {"ok": True, "native": True}   # la caméra du PC pilote déjà la souris
    if a == "stop":
        import autopilot
        autopilot.screen_stop()
        return {"ok": True}
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    if a == "hotkey":
        keys = HAND_KEYS.get(p.keys)
        if not keys:
            return {"ok": False, "error": "raccourci non autorisé"}
        pyautogui.hotkey(*keys)
        return {"ok": True}
    w, h = pyautogui.size()
    x = int(min(1, max(0, p.x)) * (w - 1)); y = int(min(1, max(0, p.y)) * (h - 1))
    if a == "scroll":
        pyautogui.scroll(max(-20, min(20, p.amount)) * 60)
        return {"ok": True}
    pyautogui.moveTo(x, y)
    if a == "click":
        pyautogui.click()
    elif a == "right":
        pyautogui.rightClick()
    elif a == "down":
        pyautogui.mouseDown()
    elif a == "up":
        pyautogui.mouseUp()
    return {"ok": True}


class Hands(BaseModel):
    on: bool


@app.get("/api/hands")
def hands_status(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import hands_native
    return hands_native.STATE


@app.post("/api/hands")
def hands_set(request: Request, p: Hands, x_jarvis_token: str = Header("")):
    """Contrôle de tout Windows par la caméra du PC (marche fenêtre Jarvis fermée)."""
    auth(x_jarvis_token, request)
    import hands_native
    return {"reply": hands_native.hand_control(p.on), **hands_native.STATE}


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn, threading
    import hands_native
    threading.Thread(target=hands_native.fetch_model, daemon=True).start()
    if os.getenv("AUTO_UPDATE", "true").lower() == "true":
        updater.start_background()
    brain.warmup()
    import memory_ext, proactive
    memory_ext.start_background()
    proactive.start()
    import evolve
    evolve.start()
    __import__("missions").start()
    __import__("anticipate").start()
    if os.getenv("WAKE_WORD", "true").lower() == "true":
        wake.start()
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8765")))

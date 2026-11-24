"""Serveur Jarvis : interface HUD + API (PC et téléphone)."""
import os, sys, pathlib, tempfile

# pythonw (démarrage caché) n'a pas de console : journal dans un fichier
if sys.stdout is None or sys.stderr is None:
    _log = open(pathlib.Path(__file__).parent / "jarvis.log", "a", encoding="utf-8")
    sys.stdout = sys.stderr = _log

from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).parent / ".env")

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

import brain, tools, updater

TOKEN = os.getenv("JARVIS_TOKEN", "")
BASE = pathlib.Path(__file__).parent
app = FastAPI(title="JARVIS")
_whisper = None


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
        "local": brain.ollama_ok(),
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "battery": bat.percent if bat else None,
        "plugged": bat.power_plugged if bat else None,
        "version": (updater.current() or "")[:7],
        "update": updater.STATE["status"],
    }


@app.post("/api/update")
def update_now(request: Request, x_jarvis_token: str = Header("")):
    auth(x_jarvis_token, request)
    import threading
    changed = updater.check_and_apply(restart=False)
    if changed:
        threading.Timer(2, updater._restart).start()
    return {"changed": changed, "status": updater.STATE["status"]}


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...), x_jarvis_token: str = Header("")):
    """Reconnaissance vocale locale (fonctionne hors ligne)."""
    auth(x_jarvis_token, request)
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="auto", compute_type="int8")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
        f.write(await audio.read())
    segs, _ = _whisper.transcribe(f.name, language="fr", vad_filter=True)
    os.unlink(f.name)
    return {"text": " ".join(s.text for s in segs).strip()}


@app.post("/api/pointer")
def pointer(request: Request, p: Pointer, x_jarvis_token: str = Header("")):
    """Contrôle de la souris du PC par les mains (caméra)."""
    auth(x_jarvis_token, request)
    import pyautogui
    pyautogui.FAILSAFE = False
    w, h = pyautogui.size()
    pyautogui.moveTo(int(p.x * w), int(p.y * h))
    if p.click:
        pyautogui.click()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    if os.getenv("AUTO_UPDATE", "true").lower() == "true":
        updater.start_background()
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8765")))

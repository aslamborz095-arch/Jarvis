"""Conscience de l'activité : Jarvis sait ce qui est ouvert au premier plan, sans capture d'écran.

- Toutes les 10 s (Windows) : application + titre de la fenêtre active, temps d'inactivité clavier/souris.
- Temps passé par application et par jour → data/activity/<date>.json (inactivité > 2 min ignorée).
- context(message) : si la demande désigne « ça / cette page / l'écran / ici… », ajoute
  « Fenêtre active : <app> — <titre> » pour que Jarvis comprenne de quoi on parle.
- activity_today : temps par application aujourd'hui (aussi ajouté au bilan du soir).
Coût : quelques appels Windows, aucune IA, aucune image.
"""
import re, sys, json, time, threading, pathlib, datetime

BASE = pathlib.Path(__file__).parent
DIR = BASE / "data" / "activity"
TICK, IDLE_MAX = 10, 120
STATE = {"app": "", "title": "", "idle": 0, "since": None}
_day = {"date": None, "apps": {}}
_lock = threading.Lock()
DEICTIC = re.compile(r"\b(ça|ca|ceci|cela|cette|cet|ce (?:mail|document|fichier|site|texte|code|truc)|l'?[ée]cran|ici|la page|cette page|la fen[êe]tre|ce que je (?:vois|regarde|lis))\b", re.I)
NAMES = {"chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "code": "VS Code", "explorer": "Explorateur",
         "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "notepad": "Bloc-notes", "claude": "Claude",
         "spotify": "Spotify", "csrss": "Écran verrouillé", "lockapp": "Écran verrouillé", "logonui": "Écran verrouillé", "discord": "Discord", "whatsapp": "WhatsApp", "vlc": "VLC", "obs64": "OBS"}


def _foreground():
    import ctypes, ctypes.wintypes as w
    u = ctypes.windll.user32
    h = u.GetForegroundWindow()
    n = u.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, buf, n + 1)
    pid = w.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    app = ""
    try:
        import psutil
        app = psutil.Process(pid.value).name().rsplit(".", 1)[0].lower()
    except Exception:
        pass
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LII(); li.cbSize = ctypes.sizeof(LII)
    idle = 0
    if u.GetLastInputInfo(ctypes.byref(li)):
        idle = (ctypes.windll.kernel32.GetTickCount() - li.dwTime) // 1000
    return NAMES.get(app, app or "?"), buf.value, idle


def _file(d):
    return DIR / f"{d}.json"


def _load(d):
    try:
        return json.loads(_file(d).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save():
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        _file(_day["date"]).write_text(json.dumps(_day["apps"], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _tick():
    app, title, idle = _foreground()
    today = datetime.date.today().isoformat()
    with _lock:
        if _day["date"] != today:
            if _day["date"]:
                _save()
            _day.update(date=today, apps=_load(today))
        if app != STATE["app"] or title != STATE["title"]:
            STATE["since"] = datetime.datetime.now().isoformat(timespec="seconds")
        STATE.update(app=app, title=title[:160], idle=idle)
        if idle < IDLE_MAX and app not in ("?", "Écran verrouillé"):
            _day["apps"][app] = _day["apps"].get(app, 0) + TICK


def context(message):
    """Ligne de contexte courte, seulement si la demande désigne quelque chose à l'écran."""
    if STATE["app"] in ("", "?", "Écran verrouillé") or not DEICTIC.search(message or ""):
        return []
    t = STATE["title"][:100]
    return [f"Fenêtre active sur le PC : {STATE['app']}" + (f" — « {t} »" if t else "")
            + " (pour voir son contenu : outil screen_look)"]


def activity_today(day: str = ""):
    """Temps passé par application (aujourd'hui, ou day=AAAA-MM-JJ)."""
    d = day or datetime.date.today().isoformat()
    with _lock:
        apps = dict(_day["apps"]) if _day["date"] == d else _load(d)
    if not apps:
        return "Aucune activité enregistrée pour ce jour."
    tot = sum(apps.values())
    top = sorted(apps.items(), key=lambda x: -x[1])[:8]
    fmt = lambda s: f"{s // 3600} h {s % 3600 // 60:02d}" if s >= 3600 else f"{max(1, s // 60)} min"
    return f"Temps actif sur le PC : {fmt(tot)}. " + ", ".join(f"{a} {fmt(s)}" for a, s in top) + "."


def status():
    return dict(STATE)


def start():
    if sys.platform != "win32":
        return
    def loop():
        n = 0
        while True:
            try:
                _tick()
                n += 1
                if n % 6 == 0:
                    with _lock:
                        _save()
            except Exception:
                pass
            time.sleep(TICK)
    threading.Thread(target=loop, daemon=True).start()


SPECS = [("activity_today", "Temps passé par application sur le PC aujourd'hui (ou un jour donné AAAA-MM-JJ) et fenêtre active.",
          {"type": "object", "properties": {"day": {"type": "string"}}, "required": []})]
FUNCS = {"activity_today": activity_today}
DANGEROUS = set()

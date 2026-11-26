"""Outils que Jarvis peut exécuter sur le PC."""
import json, os, platform, subprocess, webbrowser, datetime, pathlib, re

import psutil

IS_WIN = platform.system() == "Windows"
BASE = pathlib.Path(__file__).parent
NOTES = BASE / "data" / "notes.json"
NOTES.parent.mkdir(exist_ok=True)

# Outils qui demandent ta validation (si CONFIRM_DANGEROUS=true)
DANGEROUS = {"run_command", "write_file", "phone_shell"}


def _trunc(s, n=8000):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n…[tronqué, {len(s)} caractères]"


def run_command(command: str):
    import tempfile
    if IS_WIN:   # passe par un fichier .ps1 : plus aucun problème de guillemets
        f = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig")
        f.write("$ProgressPreference='SilentlyContinue'\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\n" + command); f.close()
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f.name]
    else:
        args = ["bash", "-lc", command]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace", creationflags=0x08000000 if IS_WIN else 0)
        return _trunc(f"code={r.returncode}\n{r.stdout}\n{r.stderr}".strip())
    except subprocess.TimeoutExpired:
        return "Erreur : délai dépassé (180 s)."


def open_target(target: str):
    """Ouvre une application, un fichier, un dossier ou une URL."""
    if re.match(r"^https?://", target):
        webbrowser.open(target)
        return f"URL ouverte : {target}"
    if IS_WIN:
        try:
            os.startfile(target)
        except OSError:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", f"Start-Process '{target}'"])
    else:
        subprocess.Popen(["xdg-open", target])
    return f"Ouvert : {target}"


def read_file(path: str):
    return _trunc(pathlib.Path(os.path.expanduser(path)).read_text(encoding="utf-8", errors="replace"))


def write_file(path: str, content: str):
    p = pathlib.Path(os.path.expanduser(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Écrit : {p} ({len(content)} caractères)"


def list_dir(path: str = "~"):
    p = pathlib.Path(os.path.expanduser(path))
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:300]
    return "\n".join(("📁 " if i.is_dir() else "📄 ") + i.name for i in items)


def system_status():
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    disk = psutil.disk_usage("C:\\" if IS_WIN else "/")
    return json.dumps({
        "heure": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "cpu_pct": psutil.cpu_percent(interval=0.3),
        "ram_pct": psutil.virtual_memory().percent,
        "disque_pct": disk.percent,
        "batterie_pct": bat.percent if bat else None,
        "secteur": bat.power_plugged if bat else None,
        "systeme": platform.platform(),
    }, ensure_ascii=False)


def web_search(query: str):
    try:
        from ddgs import DDGS
    except ImportError:
        return "Recherche web indisponible (pip install ddgs)."
    try:
        res = DDGS().text(query, max_results=6, region="fr-fr")
        return _trunc("\n\n".join(f"{r['title']}\n{r['href']}\n{r['body']}" for r in res))
    except Exception as e:
        return f"Recherche impossible (hors ligne ?) : {e}"


def fetch_url(url: str):
    import httpx
    try:
        html = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 Jarvis"}).text
    except Exception as e:
        return f"Échec : {e}"
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return _trunc(re.sub(r"\s+", " ", text))


def keyboard(text: str = "", hotkey: str = ""):
    """Tape du texte ou un raccourci (ex: 'ctrl+c', 'win+d')."""
    import pyautogui
    if hotkey:
        pyautogui.hotkey(*[k.strip() for k in hotkey.split("+")])
    if text:
        pyautogui.write(text, interval=0.01)
    return "Clavier : OK"


def mouse(x: int, y: int, click: bool = True):
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.2)
    if click:
        pyautogui.click()
    return f"Souris : ({x},{y}) clic={click}"


def merge_notes(new):
    """Fusionne des notes venues du téléphone (mode autonome) sans doublons."""
    notes = load_notes()
    known = {n["note"] for n in notes}
    for n in new:
        if n.get("note") and n["note"] not in known:
            notes.append({"date": n.get("date", datetime.date.today().isoformat()), "note": n["note"]})
    NOTES.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")


def remember(note: str):
    notes = load_notes()
    notes.append({"date": datetime.date.today().isoformat(), "note": note})
    NOTES.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    return "Mémorisé."


def load_notes():
    try:
        return json.loads(NOTES.read_text(encoding="utf-8"))
    except Exception:
        return []


def _p(props, req=None):
    return {"type": "object", "properties": props, "required": req or list(props)}

S = {"type": "string"}
SPECS = [
    ("run_command", "Exécute une commande PowerShell (Windows) ou bash sur le PC. Pour toute tâche système : installer, gérer fichiers, lancer scripts, réglages.", _p({"command": S})),
    ("open_target", "Ouvre une application (ex: 'notepad', 'spotify:'), un fichier, un dossier ou une URL.", _p({"target": S})),
    ("read_file", "Lit un fichier texte.", _p({"path": S})),
    ("write_file", "Crée ou remplace un fichier texte.", _p({"path": S, "content": S})),
    ("list_dir", "Liste un dossier.", _p({"path": S})),
    ("system_status", "Heure, CPU, RAM, disque, batterie.", _p({}, [])),
    ("web_search", "Recherche sur internet.", _p({"query": S})),
    ("fetch_url", "Lit le texte d'une page web.", _p({"url": S})),
    ("keyboard", "Tape du texte et/ou un raccourci clavier dans la fenêtre active.", _p({"text": S, "hotkey": S}, [])),
    ("mouse", "Déplace la souris et clique à des coordonnées écran.", _p({"x": {"type": "integer"}, "y": {"type": "integer"}, "click": {"type": "boolean"}}, ["x", "y"])),
    ("remember", "Mémorise durablement une info sur l'utilisateur ou une préférence.", _p({"note": S})),
]
FUNCS = {n: globals()[n] for n, _, _ in SPECS}

import phone, vision, google_apps, media, learning, proactive, autopilot, hands_native
SPECS += hands_native.SPECS + phone.SPECS + vision.SPECS + autopilot.SPECS + google_apps.SPECS + media.SPECS + learning.SPECS + proactive.SPECS
for m in (hands_native, phone, vision, autopilot, google_apps, media, learning, proactive):
    FUNCS.update(m.FUNCS)
DANGEROUS |= google_apps.DANGEROUS | learning.DANGEROUS | autopilot.DANGEROUS
learning.load_skills()   # compétences écrites par Jarvis


def delegate(task: str, level: str = "simple"):
    import brain
    return brain.delegate(task, level)


SPECS.append(("delegate", "Confie une sous-tâche autonome à un sous-agent. level = simple (rapide, économe) ou complex (puissant, réservé aux tâches difficiles).",
              {"type": "object", "properties": {"task": {"type": "string"}, "level": {"type": "string"}}, "required": ["task"]}))
FUNCS["delegate"] = delegate


def execute(name, args):
    import inspect
    try:
        f = FUNCS[name]
        ok = inspect.signature(f).parameters
        args = {k: v for k, v in (args or {}).items() if k in ok}   # ignore les arguments inventés
        return str(f(**args))
    except Exception as e:
        return f"Erreur {type(e).__name__} : {e}"

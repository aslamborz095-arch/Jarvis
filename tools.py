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


HOME = pathlib.Path.home()
ALIASES = {"téléchargements": "Downloads", "telechargements": "Downloads", "downloads": "Downloads",
           "documents": "Documents", "mes documents": "Documents", "bureau": "Desktop", "desktop": "Desktop",
           "images": "Pictures", "photos": "Pictures", "pictures": "Pictures", "vidéos": "Videos", "videos": "Videos",
           "musique": "Music", "music": "Music"}


def _path(path):
    """Chemin réel : ~, noms français (Téléchargements, Bureau…), mauvais nom d'utilisateur corrigé."""
    raw = (path or "~").strip().strip('"').strip("'")
    first, _, rest = raw.replace("\\", "/").partition("/")
    if first.lower() in ALIASES:
        raw = str(HOME / ALIASES[first.lower()] / rest)
    p = pathlib.Path(os.path.expanduser(raw))
    if not p.exists():
        m = re.match(r"(?i)^[a-z]:[\\/]users[\\/][^\\/]+[\\/]?(.*)$", str(p))
        if m and (HOME / m.group(1)).exists():
            p = HOME / m.group(1)
    if not p.exists() and p.parent.exists():   # « Téléchargements » au milieu d'un chemin
        q = p.parent / ALIASES.get(p.name.lower(), p.name)
        p = q if q.exists() else p
    return p


def find_files(name: str = "", folder: str = "~", ext: str = "", limit: int = 20):
    """Cherche des fichiers par nom partiel et/ou extension (ex. ext="pdf,docx"), récent en premier."""
    import time
    root, t0 = _path(folder), time.time()
    exts = {"." + e.strip(" .").lower() for e in ext.split(",") if e.strip(" .")}
    nm, hits = (name or "").lower(), []
    skip = {"appdata", "node_modules", ".git", ".venv", "$recycle.bin", "windows", "program files", "program files (x86)"}
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith(".")]
        for f in files:
            if (not nm or nm in f.lower()) and (not exts or os.path.splitext(f)[1].lower() in exts):
                fp = os.path.join(dp, f)
                try:
                    hits.append((os.path.getmtime(fp), fp))
                except OSError:
                    pass
        if time.time() - t0 > 8 or len(hits) > 2000:
            break
    if not hits:
        return f"Aucun fichier trouvé dans {root}."
    hits.sort(reverse=True)
    return f"{len(hits)} trouvé(s) dans {root} (plus récents) :\n" + "\n".join(h[1] for h in hits[:max(1, min(int(limit or 20), 50))])


def _doc_text(p, pages=40):
    """Texte d'un PDF / Word / Excel / PowerPoint (bibliothèques facultatives)."""
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(p))
        return f"[PDF, {len(r.pages)} pages]\n" + "\n".join((pg.extract_text() or "") for pg in r.pages[:pages])
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        return "\n".join(x.text for x in d.paragraphs if x.text.strip())
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:5]:
            out.append(f"[Feuille {ws.title}]")
            for row in ws.iter_rows(max_row=200 if pages <= 40 else 2000, values_only=True):
                if any(c is not None for c in row):
                    out.append(" | ".join("" if c is None else str(c) for c in row))
        return "\n".join(out)
    if ext == ".pptx":
        from pptx import Presentation
        out = []
        for i, sl in enumerate(Presentation(str(p)).slides, 1):
            out.append(f"[Diapo {i}] " + " ".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame))
        return "\n".join(out)
    return None


def read_file(path: str):
    """Lit un fichier texte, PDF, Word, Excel ou PowerPoint ; un dossier → son contenu."""
    p = _path(path)
    if p.is_dir():
        return f"{p} est un dossier :\n" + list_dir(str(p))
    if not p.exists():
        near = [x.name for x in p.parent.iterdir() if p.stem.lower()[:4] in x.name.lower()][:10] if p.parent.is_dir() else []
        return f"Fichier introuvable : {p}" + (". Proches : " + ", ".join(near) if near else "")
    try:
        t = _doc_text(p)
    except ImportError as e:
        return f"Lecture de {p.suffix} impossible : module manquant ({e.name}). Il s'installera à la prochaine mise à jour."
    return _trunc(t if t is not None else p.read_text(encoding="utf-8", errors="replace"))


def write_file(path: str, content: str):
    p = pathlib.Path(os.path.expanduser(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Écrit : {p} ({len(content)} caractères)"


def list_dir(path: str = "~"):
    p = _path(path)
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
    ("find_files", "Cherche des fichiers sur le PC par nom partiel et/ou extension (ext=\"pdf,docx\"), dans folder (défaut : dossier personnel ; accepte Téléchargements, Documents, Bureau…).",
     {"type": "object", "properties": {"name": S, "folder": S, "ext": S, "limit": {"type": "integer"}}, "required": []}),
    ("read_file", "Lit un fichier (texte, PDF, Word, Excel, PowerPoint) ; un dossier renvoie son contenu.", _p({"path": S})),
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

import phone, vision, google_apps, media, learning, proactive, autopilot, hands_native, evolve, metrics, team, missions, projects, anticipate, routines, health, awareness, docs
SPECS += hands_native.SPECS + phone.SPECS + vision.SPECS + autopilot.SPECS + google_apps.SPECS + media.SPECS + learning.SPECS + proactive.SPECS + evolve.SPECS + metrics.SPECS + team.SPECS + missions.SPECS + projects.SPECS + anticipate.SPECS + routines.SPECS + health.SPECS + awareness.SPECS + docs.SPECS
for m in (hands_native, phone, vision, autopilot, google_apps, media, learning, proactive, evolve, metrics, team, missions, projects, anticipate, routines, health, awareness, docs):
    FUNCS.update(m.FUNCS)
DANGEROUS |= {"phone_sms"} | google_apps.DANGEROUS | learning.DANGEROUS | autopilot.DANGEROUS | evolve.DANGEROUS
learning.load_skills()   # compétences écrites par Jarvis


def delegate(task: str, level: str = "simple"):
    import brain
    return brain.delegate(task, level)


SPECS.append(("delegate", "Confie une sous-tâche autonome à un sous-agent. level = simple (rapide, économe) ou complex (puissant, réservé aux tâches difficiles).",
              {"type": "object", "properties": {"task": {"type": "string"}, "level": {"type": "string"}}, "required": ["task"]}))
FUNCS["delegate"] = delegate


def execute(name, args):
    import time
    t0 = time.time()
    out = _execute(name, args)
    try:
        metrics.record_tool(name, out, (time.time() - t0) * 1000)
    except Exception:
        pass
    return out


def _execute(name, args):
    import inspect
    try:
        f = FUNCS[name]
        ok = inspect.signature(f).parameters
        args = {k: v for k, v in (args or {}).items() if k in ok}   # ignore les arguments inventés
        out = str(f(**args))
        if name.startswith("skill_") and out.lower().startswith("erreur"):
            evolve.record_error(name, out)
        return out
    except Exception as e:
        if name.startswith("skill_"):
            evolve.record_error(name, f"{type(e).__name__} : {e}")
        else:
            import repair
            repair.capture("outil " + name, e)
        return f"Erreur {type(e).__name__} : {e}"

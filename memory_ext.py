"""Mémoire externe sur Google Drive (dossier « Jarvis-Memoire »), consultable de partout.
Local (prioritaire) : notes, leçons, compétences, 300 derniers échanges.
Externe : archives plus anciennes + sauvegarde complète. La recherche (recall) interroge les deux."""
import json, time, threading, pathlib, datetime

import httpx

BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
KEEP_LOCAL = 300
D = "https://www.googleapis.com/drive/v3/files"
U = "https://www.googleapis.com/upload/drive/v3/files"
_folder, _cache = None, {"t": 0, "lines": []}


def _h():
    import google_apps
    return {"Authorization": f"Bearer {google_apps._token()}"}


def ready():
    import google_apps
    return google_apps.TOKEN.exists() and "drive.file" in google_apps.TOKEN.read_text()


def _folder_id():
    global _folder
    if _folder:
        return _folder
    q = "name='Jarvis-Memoire' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    f = httpx.get(D, params={"q": q, "fields": "files(id)"}, headers=_h(), timeout=20).json().get("files", [])
    _folder = f[0]["id"] if f else httpx.post(D, json={"name": "Jarvis-Memoire", "mimeType": "application/vnd.google-apps.folder"},
                                              headers=_h(), timeout=20).json()["id"]
    return _folder


def _find(name):
    q = f"name='{name}' and '{_folder_id()}' in parents and trashed=false"
    f = httpx.get(D, params={"q": q, "fields": "files(id)"}, headers=_h(), timeout=20).json().get("files", [])
    return f[0]["id"] if f else None


def _get(fid):
    return httpx.get(f"{D}/{fid}", params={"alt": "media"}, headers=_h(), timeout=60).text


def _put(name, text):
    fid = _find(name)
    if fid:
        httpx.patch(f"{U}/{fid}", params={"uploadType": "media"}, content=text.encode(), headers=_h(), timeout=60).raise_for_status()
    else:
        b = "jarvis"
        body = (f"--{b}\r\nContent-Type: application/json\r\n\r\n" + json.dumps({"name": name, "parents": [_folder_id()]}) +
                f"\r\n--{b}\r\nContent-Type: text/plain\r\n\r\n" + text + f"\r\n--{b}--").encode()
        httpx.post(U, params={"uploadType": "multipart"}, content=body,
                   headers={**_h(), "Content-Type": f"multipart/related; boundary={b}"}, timeout=60).raise_for_status()


def offload():
    """Déplace les vieux échanges vers Drive et sauvegarde la mémoire importante."""
    if not ready():
        return "Mémoire externe non connectée (⚙ → CONNECTER GOOGLE)."
    arc = DATA / "archive.jsonl"
    moved = 0
    if arc.exists():
        lines = arc.read_text(encoding="utf-8").splitlines()
        old, keep = lines[:-KEEP_LOCAL], lines[-KEEP_LOCAL:]
        if old:
            name = f"archive-{datetime.date.today():%Y-%m}.jsonl"
            fid = _find(name)
            prev = _get(fid) if fid else ""
            _put(name, (prev.rstrip("\n") + "\n" if prev.strip() else "") + "\n".join(old) + "\n")
            arc.write_text("\n".join(keep) + "\n", encoding="utf-8")
            moved = len(old)
    for f in ("notes.json", "lessons.json", "history.json"):
        p = DATA / f
        if p.exists():
            _put("sauvegarde-" + f, p.read_text(encoding="utf-8"))
    skills = DATA / "skills"
    if skills.exists():
        _put("sauvegarde-competences.json", json.dumps({f.name: f.read_text(encoding="utf-8") for f in skills.glob("*.py")}, ensure_ascii=False))
    _cache["t"] = 0
    return f"Mémoire externe à jour ({moved} anciens échanges déplacés, sauvegarde faite)."


def lines():
    """Lignes d'archive externes (cache 10 min)."""
    if not ready():
        return []
    if time.time() - _cache["t"] > 600:
        q = f"'{_folder_id()}' in parents and name contains 'archive-' and trashed=false"
        files = httpx.get(D, params={"q": q, "fields": "files(id,name)"}, headers=_h(), timeout=20).json().get("files", [])
        _cache["lines"] = [l for f in files for l in _get(f["id"]).splitlines() if l.strip()]
        _cache["t"] = time.time()
    return _cache["lines"]


def start_background(hours=6):
    def loop():
        time.sleep(300)
        while True:
            try:
                offload()
            except Exception:
                pass
            time.sleep(hours * 3600)
    threading.Thread(target=loop, daemon=True).start()

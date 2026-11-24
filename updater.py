"""Mise à jour automatique de Jarvis depuis GitHub (sans git)."""
import io, os, sys, json, shutil, hashlib, zipfile, threading, subprocess, time, pathlib

import httpx

BASE = pathlib.Path(__file__).parent
REPO = os.getenv("JARVIS_REPO", "aslamborz095-arch/jarvis")
BRANCH = os.getenv("JARVIS_BRANCH", "main")
VERSION_FILE = BASE / "data" / "version.txt"
KEEP = {".env", "data", ".venv", "jarvis.log", "install.log", "CODE-ACCES.txt", "jarvis-hidden.vbs"}
STATE = {"version": None, "last_check": None, "status": "jamais vérifié"}


def current():
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return None


def _req_hash():
    p = BASE / "requirements.txt"
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else ""


def _pip_install():
    # pythonw.exe n'a pas de console : pip doit passer par python.exe
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([exe, "-m", "pip", "install", "-q", "-r", str(BASE / "requirements.txt")],
                       capture_output=True, text=True, creationflags=0x08000000 if os.name == "nt" else 0)
    (BASE / "data").mkdir(exist_ok=True)
    (BASE / "data" / "pip.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")


def check_and_apply(restart=True):
    STATE["last_check"] = time.strftime("%d/%m %H:%M")
    try:
        r = httpx.get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", timeout=15,
                      headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            STATE["status"] = f"dépôt injoignable ({r.status_code})"
            return False
        sha = r.json()["sha"]
        STATE["version"] = sha[:7]
        if sha == current():
            STATE["status"] = "à jour"
            return False
        z = httpx.get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", timeout=300,
                      follow_redirects=True)
        z.raise_for_status()
        before = _req_hash()
        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
            root = zf.namelist()[0].split("/")[0] + "/"
            for name in zf.namelist():
                rel = name[len(root):]
                if not rel or rel.split("/")[0] in KEEP:
                    continue
                dest = BASE / rel
                if name.endswith("/"):
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))
        if _req_hash() != before:
            _pip_install()
        VERSION_FILE.parent.mkdir(exist_ok=True)
        VERSION_FILE.write_text(sha)
        STATE["status"] = f"mis à jour → {sha[:7]}"
        if restart:
            _restart()
        return True
    except Exception as e:
        STATE["status"] = f"échec : {e}"
        return False


def _restart():
    """Relance le serveur dans un nouveau processus puis quitte celui-ci."""
    exe = sys.executable
    code = ("import time,subprocess,sys;time.sleep(4);"
            "subprocess.Popen([sys.argv[1],'server.py'],cwd=sys.argv[2])")
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED | NEW_GROUP
    subprocess.Popen([exe, "-c", code, exe, str(BASE)], cwd=str(BASE), creationflags=flags)
    os._exit(0)


def start_background(interval_h=6):
    def loop():
        time.sleep(60)
        while True:
            check_and_apply()
            time.sleep(interval_h * 3600)
    threading.Thread(target=loop, daemon=True).start()

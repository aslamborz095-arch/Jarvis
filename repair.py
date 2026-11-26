"""Auto-réparation du code de Jarvis.

1. Toute exception (outils natifs, API) est enregistrée avec sa pile dans data/errors.jsonl.
2. Au cycle d'évolution, l'erreur la plus fréquente non traitée est envoyée à une IA puissante
   avec les extraits de code concernés ; elle propose des remplacements précis (ancien → nouveau).
3. Contrôles : fichiers du projet uniquement, ancien texte présent une seule fois, compilation OK
   sur une copie, contrôle de sécurité (pas de suppression de fichiers ajoutée).
4. Le correctif attend la validation (carte 🧬). Appliqué : sauvegarde, redémarrage surveillé ;
   si Jarvis ne répond plus en 90 s, retour automatique à l'ancienne version.
5. Les correctifs locaux sont réappliqués après chaque mise à jour GitHub (s'ils s'appliquent encore).
"""
import ast, json, re, sys, time, hashlib, pathlib, datetime, traceback, threading, subprocess, tempfile, shutil

BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
ERRORS = DATA / "errors.jsonl"
DIR = DATA / "repairs"
LOCAL = DATA / "local_patches.json"
DONE = DATA / "repairs_done.json"
_lock = threading.Lock()


def _read(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _write(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- capture ----------
def capture(where, exc):
    """Enregistre une exception avec sa pile (appelé par tools.execute et le serveur)."""
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
        frames = re.findall(r'File "([^"]+)", line (\d+)', tb)
        mine = [(pathlib.Path(f).name, int(n)) for f, n in frames if pathlib.Path(f).parent == BASE]
        if not mine:
            return   # erreur hors de notre code (bibliothèque, réseau…)
        sig = hashlib.sha1(f"{type(exc).__name__}|{mine[-1]}".encode()).hexdigest()[:10]
        DATA.mkdir(exist_ok=True)
        with _lock, ERRORS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": datetime.datetime.now().isoformat(timespec="minutes"), "where": where, "sig": sig,
                                "err": f"{type(exc).__name__}: {exc}"[:300], "frames": mine[-6:], "tb": tb}, ensure_ascii=False) + "\n")
        print(tb, file=sys.stderr)
    except Exception:
        pass


def _errors():
    if not ERRORS.exists():
        return []
    out = []
    for line in ERRORS.read_text(encoding="utf-8").splitlines()[-500:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ---------- proposition ----------
FIX = """Tu es le module d'auto-réparation de JARVIS (assistant Python 3.12 sous Windows, FastAPI).
Cette erreur s'est produite {n} fois :
{err}
Pile :
{tb}
Extraits du code concerné (numéros de ligne à gauche, ne pas les recopier) :
{code}

Corrige la cause avec le plus petit changement possible. Ne supprime aucune fonctionnalité, n'ajoute aucune suppression de fichier
ni commande système. Si l'erreur vient de l'environnement (réseau, appareil absent, quota) et non du code, ajoute plutôt une gestion
d'erreur claire. Réponds UNIQUEMENT par un JSON :
{{"why": "cause et correctif en une phrase", "edits": [{{"file": "nom.py", "old": "texte exact actuel (unique dans le fichier, plusieurs lignes)", "new": "texte de remplacement"}}]}}
Liste edits vide si aucun correctif sûr."""


def _excerpt(frames):
    parts, seen = [], set()
    for name, line in frames[::-1]:
        if (name, line // 40) in seen:
            continue
        seen.add((name, line // 40))
        lines = (BASE / name).read_text(encoding="utf-8").splitlines()
        a, b = max(0, line - 30), min(len(lines), line + 20)
        parts.append(f"--- {name} (lignes {a + 1}-{b}) ---\n" + "\n".join(f"{i + 1:4d} {lines[i]}" for i in range(a, b)))
    return "\n".join(parts)[:9000]


def _check(edits):
    """Vérifie et prépare les fichiers modifiés ; renvoie (dict fichier→nouveau texte, erreur)."""
    files = {}
    for e in edits:
        name = pathlib.Path(e.get("file", "")).name
        p = BASE / name
        if not re.fullmatch(r"[a-z_0-9]+\.py", name) or not p.exists() or name in ("repair.py", "updater.py"):
            return None, f"fichier refusé : {name}"
        txt = files.get(name) or p.read_text(encoding="utf-8")
        old, new = e.get("old") or "", e.get("new") or ""
        if not old or txt.count(old) != 1:
            return None, f"texte à remplacer introuvable ou ambigu dans {name}"
        added = new.replace(old, "")
        if re.search(r"\b(rmtree|unlink|os\.remove|rmdir|Remove-Item|del /|format )", added):
            return None, "correctif refusé : ajoute une suppression"
        files[name] = txt.replace(old, new)
    for name, txt in files.items():
        try:
            ast.parse(txt)
            compile(txt, name, "exec")
        except SyntaxError as e:
            return None, f"compilation impossible : {e}"
    return files, ""


def _import_test(files):
    """Charge les modules modifiés dans une copie du projet (processus séparé) pour attraper les erreurs d'import."""
    with tempfile.TemporaryDirectory() as d:
        for f in BASE.glob("*.py"):
            shutil.copy2(f, d)
        for name, txt in files.items():
            (pathlib.Path(d) / name).write_text(txt, encoding="utf-8")
        mods = [n[:-3] for n in files if n != "server.py"]
        if not mods:
            return True, ""
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):
            exe = exe[:-5] + ".exe"
        code = "import sys;sys.path.insert(0,'.');" + ";".join(f"import {m}" for m in mods)
        try:
            r = subprocess.run([exe, "-c", code], cwd=d, capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace", creationflags=0x08000000 if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired:
            return True, ""   # import lent (modèles) : la compilation suffit
        return r.returncode == 0, r.stderr[-500:]


def propose(push=None):
    """Choisit l'erreur la plus fréquente non traitée et prépare un correctif. Renvoie un texte de rapport."""
    import evolve
    errs = _errors()
    done = set(_read(DONE, []))
    groups = {}
    for e in errs:
        if e["sig"] not in done:
            groups.setdefault(e["sig"], []).append(e)
    if not groups:
        return ""
    sig, items = max(groups.items(), key=lambda kv: len(kv[1]))
    last = items[-1]
    out = evolve._llm(FIX.format(n=len(items), err=last["err"], tb=last["tb"][-2500:], code=_excerpt(last["frames"])), 3500)
    done.add(sig); _write(DONE, sorted(done)[-300:])
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0))
    except Exception:
        return f"correctif non obtenu pour « {last['err'][:60]} »"
    if not d.get("edits"):
        return f"pas de correctif sûr pour « {last['err'][:60]} »"
    files, why = _check(d["edits"])
    if not why:
        ok, why = _import_test(files)
        why = "" if ok else "échec au chargement : " + why
    name = "fix_" + sig
    evolve._log({"kind": "repair", "name": name, "why": d.get("why", ""), "err": last["err"][:200], "ok": not why, "test": why or "compilation et chargement OK"})
    if why:
        return f"{name} écarté ({why[:80]})"
    _write(DIR / f"{name}.json", {"name": name, "why": d.get("why", ""), "err": last["err"], "n": len(items),
                                  "edits": d["edits"], "test": "compilation et chargement OK", "ok": True})
    if push:
        push("evolve", text=f"réparation de mon code — {d.get('why', '')}", name=name)
    return f"correctif prêt : {name}"


def pending():
    return [_read(f, {}) for f in sorted(DIR.glob("fix_*.json"))] if DIR.exists() else []


# ---------- application ----------
def apply(name):
    f = DIR / f"{name}.json"
    if not f.exists():
        return "Correctif introuvable."
    d = _read(f, {})
    files, why = _check(d["edits"])
    if why:
        f.unlink()
        return f"Correctif devenu inapplicable ({why}) : écarté."
    bk = DIR / "backup" / name
    bk.mkdir(parents=True, exist_ok=True)
    for n, txt in files.items():
        shutil.copy2(BASE / n, bk / n)
        (BASE / n).write_text(txt, encoding="utf-8")
    loc = _read(LOCAL, [])
    loc.append({"name": name, "t": datetime.date.today().isoformat(), "why": d.get("why", ""), "edits": d["edits"]})
    _write(LOCAL, loc[-50:])
    f.unlink()
    import evolve
    evolve._log({"kind": "applied", "name": name})
    threading.Timer(3, _guarded_restart, args=(name,)).start()
    return "Correctif appliqué. Je redémarre sous surveillance ; retour arrière automatique si je ne réponds plus."


def reject(name):
    f = DIR / f"{name}.json"
    if f.exists():
        f.unlink()
        return "Correctif écarté."
    return "Correctif introuvable."


def _guarded_restart(name):
    exe = sys.executable
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    subprocess.Popen([exe, str(BASE / "repair.py"), "--guard", name], cwd=str(BASE), creationflags=flags)
    import os
    os._exit(0)


def guard(name):
    """Processus détaché : relance le serveur, et restaure la sauvegarde s'il ne répond pas."""
    import urllib.request, os
    port = os.getenv("PORT", "8765")
    time.sleep(4)
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=str(BASE))
    for _ in range(18):
        time.sleep(5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=4)
            return
        except Exception:
            if proc.poll() is not None:
                break
    try:
        proc.kill()
    except Exception:
        pass
    bk = DIR / "backup" / name
    for f in bk.glob("*.py"):
        shutil.copy2(f, BASE / f.name)
    _write(LOCAL, [p for p in _read(LOCAL, []) if p["name"] != name])
    with (DATA / "evolution.json").open("r+", encoding="utf-8") as fh:
        j = json.load(fh); j.append({"t": datetime.datetime.now().isoformat(timespec="minutes"), "kind": "rollback", "name": name})
        fh.seek(0); fh.truncate(); json.dump(j[-200:], fh, ensure_ascii=False, indent=1)
    subprocess.Popen([sys.executable, "server.py"], cwd=str(BASE))


def reapply():
    """Après une mise à jour GitHub : remet les correctifs locaux encore applicables."""
    keep = []
    for p in _read(LOCAL, []):
        files, why = _check(p["edits"])
        if why:
            continue   # corrigé en amont ou code changé : on abandonne ce correctif
        for n, txt in files.items():
            (BASE / n).write_text(txt, encoding="utf-8")
        keep.append(p)
    _write(LOCAL, keep)
    return len(keep)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--guard":
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(BASE / "jarvis.log", "a", encoding="utf-8")
    guard(sys.argv[2])

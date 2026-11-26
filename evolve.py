"""Auto-évolution de Jarvis.

Toutes les 6 h (en ligne, PC pas saturé) ou sur demande :
1. Signaux : erreurs d'outils, échecs, compétences qui plantent, idées de compétences.
2. Une IA puissante propose jusqu'à 2 améliorations (nouvelle compétence ou réparation).
3. Chaque compétence proposée passe un contrôle de sécurité du code puis un test réel isolé
   (processus séparé, 20 s max). Les leçons sont consolidées automatiquement.
4. Les compétences réussies attendent dans data/evolution/ : activation = validation AUTORISER.
"""
import ast, json, re, sys, time, threading, pathlib, datetime, subprocess, tempfile

BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
EVO = DATA / "evolution"
JOURNAL = DATA / "evolution.json"
ERRS = DATA / "skill_errors.json"
PERIOD = 6 * 3600
_lock = threading.Lock()
STATE = {"running": False, "last": None, "next": None}


def _read(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _write(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


def _log(entry):
    j = _read(JOURNAL, [])
    j.append({"t": datetime.datetime.now().isoformat(timespec="minutes"), **entry})
    _write(JOURNAL, j[-200:])


# ---------- signaux ----------
def record_error(name, msg):
    """Appelé par tools.execute quand une compétence apprise échoue."""
    e = _read(ERRS, {})
    x = e.setdefault(name, {"n": 0, "last": ""})
    x["n"] += 1; x["last"] = str(msg)[:300]
    _write(ERRS, e)


FAIL = re.compile(r"erreur|impossible|je ne peux pas|refus|indisponible|introuvable|échec|echec|délai dépassé", re.I)


def signals():
    out = {"echecs": [], "skills_ko": _read(ERRS, {}), "idees": _read(DATA / "skill_ideas.json", [])[-8:]}
    arch = DATA / "archive.jsonl"
    if arch.exists():
        for line in arch.read_text(encoding="utf-8").splitlines()[-300:]:
            try:
                e = json.loads(line)
            except Exception:
                continue
            bad = [a for a in e.get("actions", []) if FAIL.search(a)]
            if bad or FAIL.search(e.get("reply", "")[:200]):
                out["echecs"].append({"demande": e["user"][:160], "actions": bad[:3], "reponse": e["reply"][:160]})
    out["echecs"] = out["echecs"][-15:]
    return out


# ---------- contrôle du code ----------
BANNED_CALLS = {"remove", "unlink", "rmdir", "rmtree", "system", "popen", "eval", "exec", "compile", "__import__",
                "format_disk", "kill", "terminate", "shutdown", "chmod", "chown", "rename", "rmdir_all"}
BANNED_MODS = {"ctypes", "winreg", "_winapi", "socket", "shutil", "subprocess", "multiprocessing", "pty"}


def audit(code):
    """Refuse le code qui supprime, lance des programmes, touche au registre ou au réseau bas niveau."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntaxe : {e}"
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for m in mods:
                if m.split(".")[0] in BANNED_MODS:
                    return f"module interdit : {m}"
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if nm in BANNED_CALLS:
                return f"appel interdit : {nm}"
            if nm == "open" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and \
                    any(c in str(n.args[1].value) for c in "wax+"):
                return "écriture de fichier interdite (utiliser l'outil write_file)"
        if isinstance(n, ast.Attribute) and n.attr in ("write_text", "write_bytes"):
            return "écriture de fichier interdite"
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        return "pas de fonction run()"
    return ""


RUNNER = r'''
import json, sys, inspect
sys.stdout.reconfigure(encoding="utf-8")
src, args = sys.argv[1], json.loads(sys.argv[2])
ns = {"__name__": "skill_test"}
exec(compile(open(src, encoding="utf-8").read(), src, "exec"), ns)
ps = inspect.signature(ns["run"]).parameters
if not any(p.kind == p.VAR_KEYWORD for p in ps.values()):
    args = {k: v for k, v in args.items() if k in ps}   # comme tools.execute
r = ns["run"](**args)
print("@@OK@@" + json.dumps(str(r)[:1500], ensure_ascii=False))
'''


def test_skill(code, args):
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "skill.py"; src.write_text(code, encoding="utf-8")
        run = pathlib.Path(d) / "runner.py"; run.write_text(RUNNER, encoding="utf-8")
        try:
            exe = sys.executable
            if exe.lower().endswith("pythonw.exe") and pathlib.Path(exe[:-5] + ".exe").exists():
                exe = exe[:-5] + ".exe"   # pythonw n'a pas de sortie standard fiable
            r = subprocess.run([exe, "-I", str(run), str(src), json.dumps(args or {})], cwd=d,
                               capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
                               creationflags=0x08000000 if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired:
            return False, "délai dépassé (20 s)"
        m = re.search(r"@@OK@@(.*)", r.stdout, re.S)
        if r.returncode == 0 and m:
            out = json.loads(m.group(1))
            return (not re.match(r"\s*erreur", out, re.I)), out
        return False, (r.stderr or r.stdout)[-600:]


# ---------- IA ----------
def _llm(prompt, max_tokens=3500):
    import providers
    tiers = {"top": 0, "mid": 1, "fast": 2}
    av = sorted(providers.available(), key=lambda p: tiers.get(providers.PRESETS.get(p["id"], {}).get("tier"), 1))
    for p in av:
        try:
            m = providers.call(p, [{"role": "user", "content": prompt}], None, max_tokens=max_tokens)
            if m.get("content"):
                return m["content"]
        except providers.ProviderError as e:
            providers.cool(e)
    return ""


PROPOSE = """Tu es le module d'auto-évolution de JARVIS, assistant personnel sur un PC Windows (Python 3.12).
Voici ses signaux récents (échecs, compétences qui plantent, idées) :
{sig}
Compétences déjà actives : {have}
Outils natifs existants (ne pas les refaire) : {native}

Propose AU PLUS 2 améliorations utiles, sous forme de compétences Python (nouvelles, ou version réparée d'une compétence qui plante, même nom).
Contraintes du code : bibliothèque standard + httpx, psutil, pyautogui ; une fonction def run(...) -> str ; pas de suppression de fichiers,
pas de subprocess/os.system/shutil/ctypes/winreg/socket, pas d'écriture de fichier ; gérer les erreurs (try/except) et renvoyer un texte clair en français.
test_args = arguments sûrs et sans effet de bord pour tester run().
Réponds UNIQUEMENT par un JSON : {{"improvements": [{{"name": "...", "why": "une phrase", "description": "...",
"parameters": {{"type":"object","properties":{{...}},"required":[...]}}, "code": "...", "test_args": {{...}}}}]}}
Liste vide si rien de vraiment utile."""


FIX = """Ce code Python de compétence échoue à son test. Corrige-le (mêmes contraintes : pas de subprocess/shutil/socket/ctypes,
pas de suppression ni d'écriture de fichier, def run(...) -> str, try/except, texte en français).
Les noms des paramètres de run doivent correspondre exactement aux test_args.
Code :
{code}
test_args : {args}
Erreur : {err}
Réponds UNIQUEMENT par un JSON : {{"code": "...", "parameters": {{...}}, "test_args": {{...}}}}"""


CONSOLIDATE = """Voici les leçons apprises par l'assistant JARVIS (une par ligne). Fusionne les doublons, supprime les contradictoires
ou inutiles, garde les plus concrètes. Au plus 60 leçons. Réponds UNIQUEMENT par un JSON : {{"lessons": ["...", ...]}}
{ls}"""


def consolidate_lessons():
    import learning
    ls = learning._read(learning.LESSONS, [])
    if len(ls) < 120:
        return 0
    out = _llm(CONSOLIDATE.format(ls="\n".join(l["lesson"] for l in ls)), 4000)
    m = re.search(r"\{.*\}", out, re.S)
    try:
        new = [x for x in json.loads(m.group(0))["lessons"] if 15 < len(x) < 400]
    except Exception:
        return 0
    if 10 <= len(new) < len(ls):
        today = datetime.date.today().isoformat()
        learning._write(learning.LESSONS, [{"t": today, "lesson": x} for x in new])
        return len(ls) - len(new)
    return 0


# ---------- cycle ----------
def cycle(push=None):
    if not _lock.acquire(blocking=False):
        return "Une évolution est déjà en cours."
    STATE["running"] = True
    try:
        import tools, learning
        report = []
        gone = consolidate_lessons()
        if gone:
            report.append(f"{gone} leçons fusionnées")
        try:
            import repair
            r = repair.propose(push)
            if r:
                report.append(r)
        except Exception as e:
            report.append(f"auto-réparation en erreur ({e})")
        sig = signals()
        if not (sig["echecs"] or sig["skills_ko"] or sig["idees"]):
            report.append("aucun point faible détecté")
            _log({"kind": "cycle", "result": " ; ".join(report)})
            return "Évolution : " + " ; ".join(report) + "."
        have = [n for n in tools.FUNCS if n.startswith("skill_")]
        native = [n for n in tools.FUNCS if not n.startswith("skill_")]
        out = _llm(PROPOSE.format(sig=json.dumps(sig, ensure_ascii=False)[:5000], have=have or "aucune", native=", ".join(native)))
        m = re.search(r"\{.*\}", out, re.S)
        try:
            props = json.loads(m.group(0)).get("improvements", [])[:2]
        except Exception:
            props = []
        EVO.mkdir(parents=True, exist_ok=True)
        for p in props:
            name = learning._safe_name(p.get("name", "x")); code = p.get("code", "")
            why = audit(code)
            ok, res = (False, "refusé par le contrôle : " + why) if why else test_skill(code, p.get("test_args") or {})
            if not ok and not why:   # une tentative d'auto-réparation avec l'erreur
                fix = _llm(FIX.format(code=code, args=json.dumps(p.get("test_args") or {}), err=res[-800:]), 3000)
                m2 = re.search(r"\{.*\}", fix, re.S)
                try:
                    f = json.loads(m2.group(0)); code2 = f.get("code") or ""
                    if code2 and not audit(code2):
                        ok, res = test_skill(code2, f.get("test_args") or p.get("test_args") or {})
                        if ok:
                            code = code2; p["parameters"] = f.get("parameters") or p.get("parameters")
                except Exception:
                    pass
            entry = {"name": name, "why": p.get("why", ""), "description": p.get("description", ""), "test": res[:400], "ok": ok}
            if ok:
                _write(EVO / f"{name}.json", {**entry, "parameters": p.get("parameters") or {}, "code": code})
                report.append(f"compétence prête : {name}")
                if push:
                    push("evolve", text=f"{name} — {entry['why']}", name=name)
            else:
                report.append(f"{name} écartée ({res[:80]})")
            _log({"kind": "proposal", **entry})
        if not props:
            report.append("pas d'amélioration jugée utile")
        _log({"kind": "cycle", "result": " ; ".join(report)})
        return "Évolution : " + " ; ".join(report) + "."
    except Exception as e:
        return f"Évolution interrompue : {e}"
    finally:
        STATE["running"] = False
        STATE["last"] = datetime.datetime.now().isoformat(timespec="minutes")
        _lock.release()


def pending():
    import repair
    return ([_read(f, {}) for f in sorted(EVO.glob("skill_*.json"))] if EVO.exists() else []) + repair.pending()


# ---------- outils ----------
def evolve_now():
    """Lance tout de suite un cycle d'auto-amélioration."""
    import wake
    return cycle(push=wake.push)


def evolution_report():
    """Améliorations en attente et dernières évolutions."""
    p = pending()
    lines = ["En attente de validation :"] + [f"- {x['name']} : {x['why']} (test : {x['test'][:80]})" for x in p] if p \
        else ["Aucune amélioration en attente."]
    j = [x for x in _read(JOURNAL, []) if x.get("kind") == "cycle"][-5:]
    lines += ["Derniers cycles :"] + [f"- {x['t']} : {x['result']}" for x in j] if j else []
    return "\n".join(lines)


def evolution_apply(name: str):
    """Active une amélioration en attente (après validation de l'utilisateur)."""
    import learning, repair
    if name.strip().startswith("fix_"):
        return repair.apply(name.strip())
    nm = learning._safe_name(name)
    f = EVO / f"{nm}.json"
    if not f.exists():
        return "Amélioration introuvable. " + evolution_report()
    d = _read(f, {})
    if audit(d.get("code", "")):
        return "Refusé : le code ne passe plus le contrôle de sécurité."
    r = learning.create_skill(nm, d["description"], json.dumps(d.get("parameters") or {}), d["code"])
    f.unlink()
    e = _read(ERRS, {}); e.pop(nm, None); _write(ERRS, e)
    _log({"kind": "applied", "name": nm})
    return r


def evolution_reject(name: str):
    import learning, repair
    if name.strip().startswith("fix_"):
        return repair.reject(name.strip())
    f = EVO / f"{learning._safe_name(name)}.json"
    if f.exists():
        f.unlink(); _log({"kind": "rejected", "name": f.stem})
        return "Amélioration écartée."
    return "Amélioration introuvable."


def start():
    def loop():
        time.sleep(900)   # laisse le PC démarrer
        while True:
            STATE["next"] = (datetime.datetime.now() + datetime.timedelta(seconds=PERIOD)).isoformat(timespec="minutes")
            try:
                import brain, psutil, wake
                if brain.online() and psutil.virtual_memory().percent < 85:
                    cycle(push=wake.push)
            except Exception:
                pass
            time.sleep(PERIOD)
    threading.Thread(target=loop, daemon=True).start()


S = {"type": "string"}
E = {"type": "object", "properties": {}, "required": []}
SPECS = [
    ("evolve_now", "Lance maintenant un cycle d'auto-amélioration (analyse des échecs, réparation de ton propre code, création et test de nouvelles compétences).", E),
    ("evolution_report", "Montre les améliorations en attente de validation et l'historique d'évolution.", E),
    ("evolution_apply", "Active une amélioration en attente (nom donné par evolution_report).",
     {"type": "object", "properties": {"name": S}, "required": ["name"]}),
    ("evolution_reject", "Écarte une amélioration en attente.", {"type": "object", "properties": {"name": S}, "required": ["name"]}),
]
FUNCS = {"evolve_now": evolve_now, "evolution_report": evolution_report, "evolution_apply": evolution_apply,
         "evolution_reject": evolution_reject}
DANGEROUS = {"evolution_apply"}

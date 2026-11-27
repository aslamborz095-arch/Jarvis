"""Santé de Jarvis : surveillance toutes les 15 min + réparations automatiques sans risque.

Contrôles → actions :
- RAM > 88 % et cerveau local chargé alors qu'on est en ligne → décharge Ollama (≈ 2 Go rendus).
- Journal jarvis.log > 20 Mo → garde les 2 derniers Mo.
- archive.jsonl > 15 Mo → garde les 4 000 dernières lignes (le reste part dans archive_old.jsonl.gz).
- Disque C: < 5 Go libres → alerte.
- Toutes les IA en ligne en pause → alerte (le cerveau local prend le relais).
- Mot d'éveil activé mais micro muet → relance fix_mic() (1 fois par heure max).
- Mission bloquée en « planning » depuis > 20 min → relance du moteur de missions.
Chaque action est notée dans data/health.json ; health_check donne l'état ; GET /api/health.
"""
import json, os, sys, gzip, time, threading, pathlib, datetime

BASE = pathlib.Path(__file__).parent
FILE = BASE / "data" / "health.json"
STATE = {"last": None, "issues": [], "actions": []}
_mic_fix_at = [0]


def _journal(action):
    STATE["actions"] = (STATE["actions"] + [{"t": datetime.datetime.now().isoformat(timespec="minutes"), "action": action}])[-30:]
    try:
        FILE.parent.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(STATE, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _trim_log():
    p = BASE / "jarvis.log"
    if not p.exists() or p.stat().st_size < 20 * 2**20:
        return None
    with open(p, "rb") as f:
        f.seek(-2 * 2**20, 2)
        tail = f.read()
    out = sys.stdout
    if getattr(out, "name", "") and pathlib.Path(out.name).resolve() == p.resolve():   # fichier ouvert par nous : on le vide sur place
        out.flush(); out.seek(0); out.truncate(); out.write(tail.decode("utf-8", "replace")); out.flush()
    else:
        p.write_bytes(tail)
    return "journal réduit à 2 Mo"


def _trim_archive():
    p = BASE / "data" / "archive.jsonl"
    if not p.exists() or p.stat().st_size < 15 * 2**20:
        return None
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    old, keep = lines[:-4000], lines[-4000:]
    with gzip.open(BASE / "data" / "archive_old.jsonl.gz", "at", encoding="utf-8") as g:
        g.write("\n".join(old) + "\n")
    p.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return f"archive allégée ({len(old)} anciens échanges compressés)"


def check(repair=True):
    import psutil
    issues, acts = [], []
    ram = psutil.virtual_memory().percent
    try:
        import brain, httpx
        if ram > 88 and brain.online() and brain.ollama_ok():
            ps = httpx.get(f"{brain.OLLAMA_URL}/api/ps", timeout=3).json().get("models", [])
            if ps and repair:
                for m in ps:
                    httpx.post(f"{brain.OLLAMA_URL}/api/generate", timeout=20, json={"model": m["name"], "keep_alive": 0})
                acts.append("cerveau local déchargé (RAM saturée)")
    except Exception:
        pass
    if ram > 92:
        issues.append(f"mémoire vive à {ram:.0f} %")
    try:
        free = psutil.disk_usage("C:\\" if os.name == "nt" else "/").free / 2**30
        if free < 5:
            issues.append(f"disque presque plein ({free:.1f} Go libres)")
    except Exception:
        pass
    try:
        import providers
        st = providers.state()
        if st and all(p["status"] != "ok" for p in st):
            issues.append("toutes les IA en ligne sont en pause (quota) : cerveau local en relais")
    except Exception:
        pass
    try:
        import wake
        if wake.STATE.get("enabled") and wake.STATE.get("mic_dead"):
            issues.append("micro muet pour le mot d'éveil")
            if repair and time.time() - _mic_fix_at[0] > 3600:
                _mic_fix_at[0] = time.time()
                wake.fix_mic()
                acts.append("micro relancé")
    except Exception:
        pass
    try:
        import missions
        now = datetime.datetime.now()
        stuck = [m for m in missions._read() if m["status"] == "planning"
                 and now - datetime.datetime.fromisoformat(m["start"]) > datetime.timedelta(minutes=20)]
        if stuck and repair and not (missions._run["thread"] and missions._run["thread"].is_alive()):
            missions._kick()
            acts.append("moteur de missions relancé")
    except Exception:
        pass
    if repair:
        for f in (_trim_log, _trim_archive):
            try:
                a = f()
                if a:
                    acts.append(a)
            except Exception:
                pass
    STATE["last"] = datetime.datetime.now().isoformat(timespec="minutes")
    STATE["issues"] = issues
    STATE["ram"] = ram
    for a in acts:
        _journal(a)
    if issues:
        try:
            import wake
            new = [i for i in issues if i not in STATE.get("notified", [])]
            if new:
                wake.push("health", text="Santé : " + " ; ".join(new))
            STATE["notified"] = issues
        except Exception:
            pass
    else:
        STATE["notified"] = []
    return issues, acts


def health_check():
    issues, acts = check(repair=True)
    txt = "Tout va bien." if not issues else "Points à surveiller : " + " ; ".join(issues) + "."
    if acts:
        txt += " Réparé : " + " ; ".join(acts) + "."
    recent = [a["action"] for a in STATE["actions"][-3:] if a["action"] not in acts]
    if recent:
        txt += " Dernières réparations : " + " ; ".join(recent) + "."
    return txt


def start():
    def loop():
        time.sleep(5 * 60)
        while True:
            try:
                check()
            except Exception:
                pass
            time.sleep(15 * 60)
    threading.Thread(target=loop, daemon=True).start()


SPECS = [("health_check", "État de santé de Jarvis et du PC (mémoire, disque, IA, micro, missions) avec réparations automatiques.",
          {"type": "object", "properties": {}, "required": []})]
FUNCS = {"health_check": health_check}
DANGEROUS = set()

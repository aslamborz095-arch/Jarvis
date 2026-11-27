"""Missions : objectifs longs que Jarvis mène seul en arrière-plan, étape par étape.

mission_start(goal) → une IA puissante découpe l'objectif en ≤ 8 étapes vérifiables ;
un fil d'exécution réalise chaque étape avec un sous-agent (actions sensibles refusées),
passe le résultat de chaque étape à la suivante, ré-essaie une fois une étape ratée
(en reformulant), et prévient l'utilisateur à chaque étape et à la fin (évènement « mission »).
Les missions survivent au redémarrage (data/missions.json) et reprennent là où elles étaient.
Une seule mission tourne à la fois (PC 8 Go).
"""
import json, re, time, uuid, threading, pathlib, datetime

FILE = pathlib.Path(__file__).parent / "data" / "missions.json"
_lock = threading.Lock()
_run = {"thread": None, "stop": set()}
MAX_STEPS = 8
# En arrière-plan, sans l'utilisateur : lecture, préparation et brouillons seulement (rien n'est envoyé ni cliqué)
SAFE = {"web_search", "fetch_url", "recall", "read_file", "list_dir", "system_status", "gmail_read", "gmail_search",
        "gmail_draft", "calendar_list", "tasks_list", "task_add", "reminders_list", "remind", "remember", "briefing",
        "phone_status", "phone_notifications", "performance_report", "project_recall", "project_note"}


def _allowed():
    import tools
    return SAFE | {n for n in tools.FUNCS if n.startswith("skill_")}

PLAN = """Tu es le planificateur de JARVIS (assistant sur PC Windows + téléphone Android, outils : web, fichiers en lecture,
mémoire, Gmail/Agenda en lecture, état du PC, compétences apprises). Découpe cet objectif en 3 à {n} étapes concrètes,
chacune réalisable seule par un sous-agent et vérifiable. Pas d'action irréversible (envoi, suppression, achat) :
pour celles-ci, l'étape prépare un brouillon que l'utilisateur validera.
Pas de mail, SMS ni brouillon sauf si l'objectif le demande : le livrable final est rendu dans la synthèse.
Le moins d'étapes possible (une recherche groupée vaut mieux que trois).
Objectif : {goal}
Réponds uniquement en JSON : {{"steps": [{{"do": "consigne précise", "level": "simple|complex", "check": "critère de réussite"}}]}}"""


def _read():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write(ms):
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(ms[-30:], ensure_ascii=False, indent=1), encoding="utf-8")


def _update(mid, **kw):
    with _lock:
        ms = _read()
        for m in ms:
            if m["id"] == mid:
                m.update(kw)
                if "step_result" in kw:
                    i, res = kw.pop("step_result")
                    m.pop("step_result", None)
                    m["steps"][i]["result"] = res
                    m["steps"][i]["done"] = True
        _write(ms)
        return next((m for m in ms if m["id"] == mid), None)


def _push(**data):
    try:
        import wake
        wake.push("mission", **data)
    except Exception:
        pass


def _plan(goal):
    import evolve
    out = evolve._llm(PLAN.format(goal=goal, n=MAX_STEPS), 1000, fast=True)
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        steps = json.loads(m.group(0))["steps"][:MAX_STEPS]
        return [{"do": s["do"], "level": s.get("level", "simple"), "check": s.get("check", ""), "done": False, "result": ""}
                for s in steps if s.get("do")]
    except Exception:
        return []


def _worker():
    import brain, metrics
    while True:
        todo = next((m for m in _read() if m["status"] in ("planning", "running")), None)
        if not todo:
            return
        mid = todo["id"]
        if todo["status"] == "planning":
            steps = _plan(todo["goal"])
            if not steps:
                _update(mid, status="failed", end="planification impossible (aucune IA ?)")
                _push(id=mid, text=f"Mission « {todo['goal'][:60]} » : planification impossible.")
                continue
            todo = _update(mid, status="running", steps=steps)
            _push(id=mid, text=f"Mission lancée en {len(steps)} étapes : {todo['goal'][:80]}")
        for i, s in enumerate(todo["steps"]):
            if s["done"]:
                continue
            if mid in _run["stop"]:
                _run["stop"].discard(mid)
                _update(mid, status="stopped")
                _push(id=mid, text="Mission arrêtée.")
                break
            before = "\n".join(f"Étape {j + 1} : {x['result'][:600]}" for j, x in enumerate(todo["steps"][:i]) if x["result"])
            task = (f"Mission : {todo['goal']}\nRésultats des étapes précédentes :\n{before or '(aucun)'}\n\n"
                    f"Ton étape ({i + 1}/{len(todo['steps'])}) : {s['do']}\nCritère de réussite : {s['check']}\n"
                    "Réalise-la avec tes outils et rends un résultat court et concret.")
            t0 = time.time()
            res = brain.delegate(task, s["level"], allowed=_allowed(), max_rounds=5)
            if metrics.tool_failed(res.split("] ", 1)[-1]) or "Aucune IA" in res:
                res = brain.delegate(task + "\nUne première tentative a échoué : " + res[:300] + "\nProcède autrement.", "complex", allowed=_allowed())
            ok = not metrics.tool_failed(res.split("] ", 1)[-1])
            metrics.record_role("mission_etape", ok, (time.time() - t0) * 1000)
            todo = _update(mid, step_result=(i, res[:3000]))
            _push(id=mid, text=f"Étape {i + 1}/{len(todo['steps'])} {'faite' if ok else 'difficile'} : {s['do'][:70]}")
        else:
            final = brain.delegate("Rédige le LIVRABLE FINAL de cette mission pour l'utilisateur : le contenu concret et complet "
                                   "(pas un renvoi vers un mail ou un brouillon), clair, sans remplissage, 2500 caractères max.\nObjectif : "
                                   + todo["goal"] + "\nRésultats des étapes :\n" + "\n".join(f"- {x['do']} → {x['result'][:1200]}" for x in todo["steps"]),
                                   "complex", allowed=set())
            final = final.split("] ", 1)[-1]
            _update(mid, status="done", end=datetime.datetime.now().isoformat(timespec="minutes"), summary=final[:3000])
            try:
                import projects
                projects.attach_mission(todo["goal"], final)
            except Exception:
                pass
            _push(id=mid, text="Mission terminée : " + final[:300] + (" … (suite dans 🎯 Missions)" if len(final) > 300 else ""))


def _kick():
    if not (_run["thread"] and _run["thread"].is_alive()):
        _run["thread"] = threading.Thread(target=_worker, daemon=True)
        _run["thread"].start()


def mission_start(goal: str):
    mid = uuid.uuid4().hex[:6]
    with _lock:
        ms = _read()
        ms.append({"id": mid, "goal": goal, "status": "planning", "start": datetime.datetime.now().isoformat(timespec="minutes"), "steps": []})
        _write(ms)
    busy = any(m["status"] == "running" for m in ms[:-1])
    _kick()
    return f"Mission {mid} enregistrée" + (" ; elle démarrera après la mission en cours." if busy else " ; je m'en occupe en arrière-plan et vous préviens à chaque étape.")


def mission_status(id: str = ""):
    ms = _read()
    if id:
        ms = [m for m in ms if m["id"] == id]
    if not ms:
        return "Aucune mission."
    out = []
    for m in ms[-5:]:
        d = sum(s["done"] for s in m["steps"])
        line = f"{m['id']} [{m['status']}] {d}/{len(m['steps'])} étapes : {m['goal'][:80]}"
        if m.get("summary"):
            line += " — " + m["summary"][:300]
        out.append(line)
    return "\n".join(out)


def mission_stop(id: str):
    m = next((m for m in _read() if m["id"] == id), None)
    if not m:
        return "Mission introuvable."
    if m["status"] == "planning":
        _update(id, status="stopped")
    else:
        _run["stop"].add(id)
    return f"Arrêt de la mission {id} demandé."


def start():
    """Au démarrage : reprend une mission interrompue par un redémarrage."""
    if any(m["status"] in ("planning", "running") for m in _read()):
        threading.Timer(90, _kick).start()


S = {"type": "string"}
SPECS = [
    ("mission_start", "Lance une mission longue en arrière-plan (objectif en plusieurs étapes : préparer, rechercher, organiser, suivre…). "
     "Jarvis planifie, exécute chaque étape seul et prévient à chaque étape.", {"type": "object", "properties": {"goal": S}, "required": ["goal"]}),
    ("mission_status", "État des missions (id facultatif).", {"type": "object", "properties": {"id": S}, "required": []}),
    ("mission_stop", "Arrête une mission.", {"type": "object", "properties": {"id": S}, "required": ["id"]}),
]
FUNCS = {"mission_start": mission_start, "mission_status": mission_status, "mission_stop": mission_stop}
DANGEROUS = set()

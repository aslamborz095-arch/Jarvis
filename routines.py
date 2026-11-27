"""Routines : missions qui se relancent seules selon un horaire (« tous les jours 08:00 », « lundi,jeudi 18:30 »).

- routine_add(goal, when) / routine_list() / routine_remove(id)
- Vérifiées chaque minute ; une routine due lance mission_start(goal) (outils sûrs uniquement).
- Une exécution manquée (PC éteint) est rattrapée au démarrage si elle date de moins de 6 h.
Stockage : data/routines.json.
"""
import json, re, time, uuid, threading, pathlib, datetime, unicodedata

FILE = pathlib.Path(__file__).parent / "data" / "routines.json"
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_lock = threading.Lock()


def _plain(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _read():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write(r):
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def parse(when):
    """→ (jours 0-6, "HH:MM") ou None. Accepte : tous les jours / chaque jour / semaine / week-end / noms de jours + heure (8h, 08:30, 18h30)."""
    w = _plain(when)
    m = re.search(r"(\d{1,2})\s*(?:h|:)\s*(\d{2})?", w)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh > 23 or mm > 59:
        return None
    if re.search(r"tous les jours|chaque jour|quotidien|daily", w):
        days = list(range(7))
    elif "week-end" in w or "weekend" in w:
        days = [5, 6]
    elif re.search(r"\bsemaine\b|jours ouvr|en semaine", w):
        days = list(range(5))
    else:
        days = [i for i, d in enumerate(DAYS) if _plain(d) in w]
    return (days, f"{hh:02d}:{mm:02d}") if days else None


def routine_add(goal: str, when: str):
    p = parse(when)
    if not p:
        return "Horaire non compris. Exemples : « tous les jours 8h », « lundi,jeudi 18h30 », « en semaine 07:45 »."
    rid = uuid.uuid4().hex[:5]
    with _lock:
        r = _read()
        x = {"id": rid, "goal": goal.strip()[:400], "days": p[0], "time": p[1], "when": when, "last": "", "on": True}
        d = _due(x, datetime.datetime.now())   # pas de déclenchement immédiat pour une heure déjà passée aujourd'hui
        x["last"] = d.isoformat(timespec="minutes") if d else ""
        r.append(x)
        _write(r)
    jours = "tous les jours" if len(p[0]) == 7 else ", ".join(DAYS[d] for d in p[0])
    return f"Routine {rid} créée : {jours} à {p[1]} — {goal[:80]}"


def routine_list():
    r = _read()
    if not r:
        return "Aucune routine."
    return "\n".join(f"{x['id']} : {x['when']} → {x['goal'][:90]}" + ("" if x.get("on", True) else " (en pause)") for x in r)


def routine_remove(id: str):
    with _lock:
        r = _read()
        n = len(r)
        r = [x for x in r if x["id"] != id]
        _write(r)
    return "Routine supprimée." if len(r) < n else "Routine introuvable."


def _due(x, now):
    """Dernière échéance passée de la routine (datetime) dans les 6 dernières heures, sinon None."""
    hh, mm = map(int, x["time"].split(":"))
    for back in (0, 1):
        d = (now - datetime.timedelta(days=back)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d.weekday() in x["days"] and d <= now and now - d < datetime.timedelta(hours=6):
            return d
    return None


def tick():
    now = datetime.datetime.now()
    with _lock:
        r = _read()
        fire = []
        for x in r:
            d = _due(x, now) if x.get("on", True) else None
            if d and x.get("last", "") < d.isoformat(timespec="minutes"):
                x["last"] = d.isoformat(timespec="minutes")
                fire.append(x)
        if fire:
            _write(r)
    for x in fire:
        try:
            import missions, wake
            missions.mission_start(f"[Routine {x['id']}] {x['goal']}")
            wake.push("mission", id=x["id"], text=f"Routine lancée : {x['goal'][:80]}")
        except Exception:
            pass


def start():
    def loop():
        time.sleep(60)
        while True:
            try:
                tick()
            except Exception:
                pass
            time.sleep(60)
    threading.Thread(target=loop, daemon=True).start()


S = {"type": "string"}
SPECS = [
    ("routine_add", "Programme une mission récurrente. when = jours + heure, ex : « tous les jours 8h », « lundi,jeudi 18h30 », « en semaine 07:45 », « week-end 10h ».",
     {"type": "object", "properties": {"goal": S, "when": S}, "required": ["goal", "when"]}),
    ("routine_list", "Liste les routines programmées.", {"type": "object", "properties": {}, "required": []}),
    ("routine_remove", "Supprime une routine (id).", {"type": "object", "properties": {"id": S}, "required": ["id"]}),
]
FUNCS = {"routine_add": routine_add, "routine_list": routine_list, "routine_remove": routine_remove}
DANGEROUS = set()

"""Jarvis proactif : briefing du jour et rappels à heure fixe."""
import json, time, threading, pathlib, datetime

import httpx

BASE = pathlib.Path(__file__).parent
REM = BASE / "data" / "reminders.json"
LAT, LON, CITY = 48.8566, 2.3522, "Paris"
WMO = {0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert", 45: "brouillard", 48: "brouillard givrant",
       51: "bruine", 53: "bruine", 55: "forte bruine", 61: "pluie faible", 63: "pluie", 65: "forte pluie", 71: "neige faible",
       73: "neige", 75: "forte neige", 80: "averses", 81: "averses", 82: "fortes averses", 95: "orage", 96: "orage avec grêle"}


def weather():
    try:
        d = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": LAT, "longitude": LON, "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max", "timezone": "Europe/Paris", "forecast_days": 1}).json()
        c, dl = d["current"], d["daily"]
        return (f"{CITY} : {round(c['temperature_2m'])} °C, {WMO.get(c['weather_code'], 'temps variable')}, "
                f"entre {round(dl['temperature_2m_min'][0])} et {round(dl['temperature_2m_max'][0])} °C, "
                f"{dl['precipitation_probability_max'][0]} % de risque de pluie")
    except Exception:
        return ""


def briefing():
    """Point du jour : météo, agenda, mails non lus, état PC/téléphone."""
    parts = []
    w = weather()
    if w:
        parts.append("Météo — " + w)
    try:
        import google_apps
        if google_apps.TOKEN.exists():
            cal = google_apps.calendar_list(1)
            parts.append("Agenda — " + ("rien de prévu" if cal.startswith("Aucun") else cal.replace("\n", " ; ")))
            mails = google_apps.gmail_search("is:unread newer_than:2d", 5)
            parts.append("Mails non lus — " + ("aucun" if mails.startswith("Aucun") else mails))
    except Exception:
        pass
    try:
        import tools, phone
        s = json.loads(tools.system_status())
        parts.append(f"PC — processeur {s['cpu_pct']} %, mémoire {s['ram_pct']} %, disque {s['disque_pct']} %")
        ps = phone.status()
        if ps.get("connected"):
            parts.append(f"Téléphone — batterie {ps.get('battery')} %")
    except Exception:
        pass
    for r in pending():
        parts.append(f"Rappel prévu — {r['when'][11:16]} : {r['text']}")
    return "\n".join(parts) or "Rien à signaler."


def spoken_briefing():
    """Version courte et parlée, rédigée par l'IA (sinon texte brut)."""
    raw = briefing()
    try:
        import learning
        txt = learning._llm("Tu es JARVIS. Fais un briefing parlé en français, 3 à 5 phrases, ton calme et britannique, "
                            "commence par saluer monsieur selon l'heure (" + datetime.datetime.now().strftime("%H:%M") +
                            "). Seulement l'essentiel, pas de liste, pas de markdown :\n" + raw, max_tokens=2500)
        return txt.strip() or raw
    except Exception:
        return raw


# ---------- rappels ----------
def _load():
    try:
        return json.loads(REM.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(r):
    REM.parent.mkdir(exist_ok=True)
    REM.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def pending():
    return [r for r in _load() if not r.get("done")]


def remind(text: str, when: str):
    """when : AAAA-MM-JJTHH:MM (heure de Paris), ou « +30m » / « +2h »."""
    now = datetime.datetime.now()
    w = when.strip()
    if w.startswith("+"):
        n, u = int(w[1:-1]), w[-1]
        dt = now + (datetime.timedelta(minutes=n) if u == "m" else datetime.timedelta(hours=n))
    else:
        dt = datetime.datetime.fromisoformat(w)
    r = _load(); r.append({"text": text, "when": dt.isoformat(timespec="minutes"), "done": False}); _save(r)
    return f"Rappel enregistré pour {dt:%d/%m à %H:%M} : {text}"


def reminders_list():
    p = pending()
    return "\n".join(f"{r['when'].replace('T', ' ')} — {r['text']}" for r in p) or "Aucun rappel."


def start():
    def loop():
        while True:
            try:
                now = datetime.datetime.now().isoformat(timespec="minutes")
                r, changed = _load(), False
                for x in r:
                    if not x.get("done") and x["when"] <= now:
                        x["done"], changed = True, True
                        import wake
                        wake.push("reminder", text=x["text"])
                        threading.Thread(target=wake.speak, args=(f"Monsieur, je vous rappelle : {x['text']}",), daemon=True).start()
                if changed:
                    _save(r)
            except Exception:
                pass
            time.sleep(20)
    threading.Thread(target=loop, daemon=True).start()


# ---------- tâches ----------
TASKS = BASE / "data" / "tasks.json"


def _tl():
    try:
        return json.loads(TASKS.read_text(encoding="utf-8"))
    except Exception:
        return []


def task_add(text: str, due: str = ""):
    """Ajoute une tâche (due = AAAA-MM-JJ facultatif)."""
    t = _tl(); t.append({"id": int(time.time() * 1000) % 10**9, "text": text, "due": due, "done": False})
    TASKS.parent.mkdir(exist_ok=True); TASKS.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"Tâche ajoutée : {text}"


def task_done(text: str):
    """Coche la tâche qui contient ce texte."""
    t = _tl()
    for x in t:
        if not x["done"] and text.lower() in x["text"].lower():
            x["done"] = True
            TASKS.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
            return f"Terminé : {x['text']}"
    return "Tâche introuvable."


def tasks_list():
    return "\n".join(f"- {x['text']}" + (f" (pour le {x['due']})" if x['due'] else "") for x in _tl() if not x["done"]) or "Aucune tâche."


def dashboard():
    """Mails, agenda, tâches et rappels classés par urgence (1 = urgent, 2 = important, 3 = plus tard)."""
    raw = {"mails": "", "agenda": "", "taches": tasks_list(), "rappels": reminders_list()}
    try:
        import google_apps
        if google_apps.TOKEN.exists():
            raw["mails"] = google_apps.gmail_search("is:unread newer_than:7d", 15)
            raw["agenda"] = google_apps.calendar_list(7)
    except Exception as e:
        raw["mails"] = f"(Google indisponible : {e})"
    items = []
    try:
        import learning, re as _re
        out = learning._llm("Classe chaque élément par urgence pour Aslambek (aujourd'hui : " + datetime.datetime.now().strftime("%A %d/%m %H:%M") +
                            "). Ignore pubs et newsletters sauf si action requise. Réponds UNIQUEMENT en JSON : "
                            '[{"type":"mail|agenda|tache|rappel","titre":"…","detail":"… (court)","urgence":1|2|3,"pourquoi":"… (5 mots)"}]\n'
                            + json.dumps(raw, ensure_ascii=False)[:9000], max_tokens=3000)
        m = _re.search(r"\[.*\]", out, _re.S)
        items = json.loads(m.group(0)) if m else []
    except Exception:
        pass
    if not items:   # pas d'IA : liste brute
        for k, v in raw.items():
            for l in (v or "").splitlines():
                if l.strip() and not l.startswith(("Aucun", "(")):
                    items.append({"type": k.rstrip("s"), "titre": l.strip()[:140], "detail": "", "urgence": 2, "pourquoi": ""})
    return {"items": sorted(items, key=lambda x: x.get("urgence", 3)), "at": datetime.datetime.now().strftime("%d/%m %H:%M")}


S = {"type": "string"}
SPECS = [
    ("briefing", "Point du jour : météo, agenda, mails non lus, état PC/téléphone, rappels.", {"type": "object", "properties": {}, "required": []}),
    ("remind", "Crée un rappel parlé. when = AAAA-MM-JJTHH:MM (heure de Paris) ou +30m / +2h.",
     {"type": "object", "properties": {"text": S, "when": S}, "required": ["text", "when"]}),
    ("reminders_list", "Liste les rappels à venir.", {"type": "object", "properties": {}, "required": []}),
    ("task_add", "Ajoute une tâche à la liste (due = AAAA-MM-JJ facultatif).", {"type": "object", "properties": {"text": S, "due": S}, "required": ["text"]}),
    ("task_done", "Coche une tâche (texte partiel).", {"type": "object", "properties": {"text": S}, "required": ["text"]}),
    ("tasks_list", "Liste les tâches en cours.", {"type": "object", "properties": {}, "required": []}),
]
FUNCS = {"briefing": briefing, "remind": remind, "reminders_list": reminders_list, "task_add": task_add, "task_done": task_done, "tasks_list": tasks_list}

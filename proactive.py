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


S = {"type": "string"}
SPECS = [
    ("briefing", "Point du jour : météo, agenda, mails non lus, état PC/téléphone, rappels.", {"type": "object", "properties": {}, "required": []}),
    ("remind", "Crée un rappel parlé. when = AAAA-MM-JJTHH:MM (heure de Paris) ou +30m / +2h.",
     {"type": "object", "properties": {"text": S, "when": S}, "required": ["text", "when"]}),
    ("reminders_list", "Liste les rappels à venir.", {"type": "object", "properties": {}, "required": []}),
]
FUNCS = {"briefing": briefing, "remind": remind, "reminders_list": reminders_list}

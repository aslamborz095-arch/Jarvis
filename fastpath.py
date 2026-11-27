"""Réponses instantanées (0 IA, < 50 ms) pour les demandes triviales et sans ambiguïté.
Tout ce qui n'est pas reconnu avec certitude part vers les IA."""
import re, datetime, unicodedata

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _p(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^\s*(\[[^\]]*\]\s*)?((hey|he|eh|ok)\s+)?jarvis[\s,]*", "", s)
    return re.sub(r"[^a-z0-9' ]+", " ", s).strip()


def _heure():
    n = datetime.datetime.now()
    return f"Il est {n.hour} h {n.minute:02d}, monsieur." if n.minute else f"Il est {n.hour} h pile, monsieur."


def _date():
    n = datetime.date.today()
    return f"Nous sommes le {JOURS[n.weekday()]} {n.day} {MOIS[n.month - 1]} {n.year}."


def _etat():
    import psutil
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    t = f"Processeur à {psutil.cpu_percent(interval=0.2):.0f} %, mémoire à {psutil.virtual_memory().percent:.0f} %"
    if bat:
        t += f", batterie à {bat.percent:.0f} %" + (" sur secteur" if bat.power_plugged else "")
    return t + "."


RULES = [
    (re.compile(r"^(quelle heure (est il|il est)|il est quelle heure|l heure( s il te plait)?|tu as l heure)$"), _heure),
    (re.compile(r"^(on est|nous sommes) quel jour( aujourd hui)?$|^quel jour (on est|sommes nous|est on)( aujourd hui)?$|^(quelle est la|la) date( d aujourd hui)?$"), _date),
    (re.compile(r"^(etat|statut) du (pc|systeme|ordinateur)$|^comment va (le pc|l ordinateur|le systeme)$"), _etat),
    (re.compile(r"^(merci|merci beaucoup|merci jarvis)$"), lambda: "À votre service, monsieur."),
    (re.compile(r"^(salut|bonjour|bonsoir|coucou)$"), lambda: ("Bonsoir" if datetime.datetime.now().hour >= 18 else "Bonjour") + ", monsieur. Que puis-je faire pour vous ?"),
]


def answer(message):
    m = _p(message)
    if not m or len(m.split()) > 8:
        return None
    for rx, f in RULES:
        if rx.search(m):
            return f()
    return None

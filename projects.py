"""Mémoire par projet : Jarvis garde le fil de chaque projet (décisions, avancées, résultats de missions).

- project_note(project, note) : ajoute une info au projet (créé s'il n'existe pas).
- project_recall(project) : l'historique du projet.
- Quand un message cite un projet connu (nom ou alias), son contexte récent est ajouté à la demande.
- Une mission terminée laisse automatiquement sa synthèse dans le projet qu'elle concerne.
Stockage : data/projects.json.
"""
import json, re, pathlib, datetime, unicodedata, threading

FILE = pathlib.Path(__file__).parent / "data" / "projects.json"
_lock = threading.Lock()


def _plain(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", _plain(s)).strip("-")[:40] or "divers"


def _read():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(p):
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def _find(p, name):
    s, n = _slug(name), _plain(name)
    if s in p:
        return s
    for k, v in p.items():
        if n in [_plain(a) for a in v.get("aliases", [])] or n == _plain(v["name"]):
            return k
    return None


def project_note(project: str, note: str, aliases: str = ""):
    with _lock:
        p = _read()
        k = _find(p, project) or _slug(project)
        x = p.setdefault(k, {"name": project.strip(), "aliases": [], "notes": []})
        for a in [a.strip() for a in aliases.split(",") if a.strip()]:
            if a not in x["aliases"]:
                x["aliases"].append(a)
        if any(n["note"] == note.strip()[:600] for n in x["notes"][-10:]):
            return f"Déjà noté dans le projet {x['name']}."
        x["notes"] = (x["notes"] + [{"t": datetime.date.today().isoformat(), "note": note.strip()[:600]}])[-80:]
        _write(p)
    return f"Noté dans le projet {x['name']}."


def project_recall(project: str = ""):
    p = _read()
    if not project:
        return overview() or "Aucun projet suivi."
    k = _find(p, project)
    if not k:
        return f"Projet « {project} » inconnu. Projets suivis : " + (", ".join(v["name"] for v in p.values()) or "aucun")
    x = p[k]
    return f"{x['name']} :\n" + "\n".join(f"- {n['t']} : {n['note']}" for n in x["notes"][-25:])


def overview():
    p = _read()
    return "\n".join(f"- {v['name']} : {v['notes'][-1]['note'][:120] if v['notes'] else '(vide)'}" for v in p.values())


def context_for(message, k=8):
    """Contexte des projets cités dans le message (nom ou alias, mot entier)."""
    m = " " + re.sub(r"[^a-z0-9]+", " ", _plain(message)) + " "
    out = []
    for v in _read().values():
        names = [v["name"]] + v.get("aliases", [])
        if any(" " + re.sub(r"[^a-z0-9]+", " ", _plain(n)).strip() + " " in m for n in names if len(n) >= 3):
            out.append(f"Projet {v['name']} — " + " | ".join(n["note"][:200] for n in v["notes"][-k:]))
    return out[:2]


def attach_mission(goal, summary):
    """Range la synthèse d'une mission dans le projet cité dans son objectif (sinon « missions »)."""
    p = _read()
    m = " " + re.sub(r"[^a-z0-9]+", " ", _plain(goal)) + " "
    target = next((v["name"] for v in p.values()
                   if any(" " + re.sub(r"[^a-z0-9]+", " ", _plain(n)).strip() + " " in m for n in [v["name"]] + v.get("aliases", []) if len(n) >= 3)),
                  "missions")
    project_note(target, f"Mission « {goal[:120]} » terminée : {summary[:400]}")


S = {"type": "string"}
SPECS = [
    ("project_note", "Ajoute une info durable à un projet de l'utilisateur (décision, avancée, résultat). aliases = autres noms, séparés par des virgules.",
     {"type": "object", "properties": {"project": S, "note": S, "aliases": S}, "required": ["project", "note"]}),
    ("project_recall", "Historique d'un projet (vide = liste de tous les projets suivis).",
     {"type": "object", "properties": {"project": S}, "required": []}),
]
FUNCS = {"project_note": project_note, "project_recall": project_recall}
DANGEROUS = set()

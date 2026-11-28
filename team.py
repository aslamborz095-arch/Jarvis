"""Équipe de sous-agents spécialisés : chercheur → rédacteur → relecteur (une révision au besoin).

Chaque rôle a son niveau d'IA (le juste nécessaire) et ses outils autorisés :
- chercheur  : simple, lecture seule (web, pages, mémoire, fichiers, état PC) ;
- rédacteur  : complexe, sans outil ;
- relecteur  : simple, sans outil ; répond OK ou liste les corrections.
Les réussites de chaque rôle sont mesurées (metrics.roles).
"""
import time

import metrics

READ_ONLY = {"web_search", "fetch_url", "recall", "project_recall", "read_file", "list_dir", "system_status", "skill_get_weather", "find_files", "activity_today", "search_in_files", "summarize_file", "index_status"}

ROLES = {
    "chercheur": ("simple", READ_ONLY,
                  "Tu es le CHERCHEUR de l'équipe Jarvis. Rassemble les faits utiles et vérifiables pour : {goal}\n"
                  "Utilise web_search, fetch_url, recall si besoin. Rends une liste de faits courts avec leurs sources. Rien d'inventé."),
    "redacteur": ("complex", set(),
                  "Tu es le RÉDACTEUR de l'équipe Jarvis. Objectif : {goal}\n{extra}\n"
                  "Produis le livrable final en français, clair, précis, sans remplissage. N'invente aucun fait absent des notes."),
    "relecteur": ("simple", set(),
                  "Tu es le RELECTEUR de l'équipe Jarvis. Objectif : {goal}\nNotes du chercheur :\n{notes}\n\nLivrable :\n{draft}\n\n"
                  "Vérifie : répond à l'objectif, fidèle aux notes, aucune erreur. Si tout va bien réponds exactement OK. "
                  "Sinon liste les corrections nécessaires, une par ligne."),
}


def _run(role, **kw):
    lvl, allowed, tpl = ROLES[role]
    import brain
    t = time.time()
    out = brain.delegate(tpl.format(**kw), lvl, allowed=allowed)
    text = out.split("] ", 1)[1] if out.startswith("[sous-agent") else out
    metrics.record_role(role, not metrics.tool_failed(text) and not text.startswith(("Aucune IA", "Sous-agent en erreur")),
                        (time.time() - t) * 1000)
    return text


def team_task(goal: str, research: bool = True):
    """Fait travailler l'équipe sur un livrable (texte, synthèse, plan, comparatif…)."""
    notes = _run("chercheur", goal=goal) if research else "(pas de recherche demandée)"
    draft = _run("redacteur", goal=goal, extra="Notes du chercheur :\n" + notes)
    review = _run("relecteur", goal=goal, notes=notes[:4000], draft=draft[:6000])
    if review.strip().upper().rstrip(".") != "OK" and not review.startswith(("Aucune IA", "Sous-agent en erreur")):
        draft = _run("redacteur", goal=goal,
                     extra=f"Notes du chercheur :\n{notes}\n\nTon brouillon :\n{draft}\n\nCorrections du relecteur à appliquer :\n{review}")
        verdict = "révisé après relecture"
    else:
        verdict = "validé par le relecteur"
    return f"[équipe : {verdict}]\n{draft}"


SPECS = [("team_task", "Confie un livrable (synthèse, texte, plan, comparatif, recherche approfondie) à l'équipe chercheur → rédacteur → relecteur. "
          "research=false si aucune recherche n'est utile.",
          {"type": "object", "properties": {"goal": {"type": "string"}, "research": {"type": "boolean"}}, "required": ["goal"]})]
FUNCS = {"team_task": team_task}
DANGEROUS = set()

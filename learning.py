"""Auto-apprentissage de Jarvis.

1. Leçons : après chaque tâche, Jarvis analyse ce qui a marché ou échoué et en tire des règles,
   réinjectées automatiquement quand une demande similaire revient.
2. Mémoire longue : toutes les conversations sont archivées et cherchables (outil recall).
3. Faits : ce que l'utilisateur dit de lui-même est retenu sans qu'il le demande.
4. Compétences : Jarvis écrit ses propres outils Python ; chacun est validé par l'utilisateur avant activation.
"""
import re, json, time, threading, pathlib, datetime, unicodedata

BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
LESSONS = DATA / "lessons.json"
ARCHIVE = DATA / "archive.jsonl"
SKILLS = DATA / "skills"
IDEAS = DATA / "skill_ideas.json"
_lock = threading.Lock()


def _read(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _write(p, v):
    DATA.mkdir(exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


def _plain(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


STOP = set("pour avec dans cette mais plus tout tous elle elles nous vous leur sont etre avoir fait faire mon mes ton tes son ses une des les est que qui quoi comment quand sur par pas".split())


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", _plain(s)) if w not in STOP}


def _score(q, text):
    a, b = _words(q), _words(text)
    return len(a & b) / (1 + len(a) ** 0.5) if a and b else 0


# ---------- mémoire longue ----------
def archive(user, reply, log):
    DATA.mkdir(exist_ok=True)
    with _lock, ARCHIVE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": datetime.datetime.now().isoformat(timespec="minutes"), "user": user,
                            "reply": reply, "actions": [l[:120] for l in log][:8]}, ensure_ascii=False) + "\n")


def recall(query: str):
    """Cherche dans tout ce que Jarvis a vécu et appris (conversations passées, notes, leçons)."""
    hits = []
    if ARCHIVE.exists():
        for line in ARCHIVE.read_text(encoding="utf-8").splitlines()[-5000:]:
            try:
                e = json.loads(line)
            except Exception:
                continue
            s = _score(query, e["user"] + " " + e["reply"])
            if s > 0:
                hits.append((s, f"[{e['t']}] Lui : {e['user'][:200]} → Jarvis : {e['reply'][:250]}"))
    try:   # mémoire externe (Google Drive)
        import memory_ext
        for line in memory_ext.lines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            s = _score(query, e["user"] + " " + e["reply"])
            if s > 0:
                hits.append((s - 0.1, f"[externe {e['t']}] Lui : {e['user'][:200]} → Jarvis : {e['reply'][:250]}"))
    except Exception:
        pass
    import tools
    for n in tools.load_notes():
        s = _score(query, n["note"])
        if s > 0:
            hits.append((s + 0.5, f"[note {n['date']}] {n['note']}"))
    for l in _read(LESSONS, []):
        s = _score(query, l["lesson"])
        if s > 0:
            hits.append((s + 0.3, f"[leçon] {l['lesson']}"))
    hits.sort(key=lambda x: -x[0])
    return "\n".join(h for _, h in hits[:10]) or "Rien trouvé dans ma mémoire."


# ---------- leçons ----------
def relevant_lessons(query, k=6):
    ls = _read(LESSONS, [])
    ranked = sorted(((_score(query, l["lesson"]), l) for l in ls), key=lambda x: -x[0])
    return [l["lesson"] for s, l in ranked[:k] if s > 0]


def _add_lessons(new):
    ls = _read(LESSONS, [])
    known = {_plain(l["lesson"]) for l in ls}
    for x in new:
        x = (x or "").strip()
        if 15 < len(x) < 400 and _plain(x) not in known:
            ls.append({"t": datetime.date.today().isoformat(), "lesson": x})
            known.add(_plain(x))
    _write(LESSONS, ls[-300:])


def _add_facts(new):
    import tools
    tools.merge_notes([{"note": f.strip()} for f in new if f and 8 < len(f.strip()) < 300])


REFLECT = """Tu analyses une interaction de l'assistant JARVIS pour qu'il s'améliore tout seul.
Demande de l'utilisateur : {user}
Actions effectuées : {log}
Réponse finale : {reply}

Réponds UNIQUEMENT par un JSON :
{{"lessons": [0 à 2 règles courtes, concrètes et réutilisables pour mieux réussir ce genre de tâche sur ce PC Windows / ce téléphone Android (ex : commande qui marche, erreur à éviter, meilleure méthode)],
 "facts": [0 à 2 faits durables que l'utilisateur a lui-même donnés sur lui (préférences, habitudes, proches, projets)],
 "skill_idea": "si cette tâche est répétitive et mériterait un outil dédié, décris l'outil en une phrase ; sinon chaîne vide"}}
N'invente rien. Listes vides si rien d'utile."""


def _llm(prompt):
    import providers
    for p in providers.available():
        try:
            m = providers.call(p, [{"role": "user", "content": prompt}], None, max_tokens=500)
            return m.get("content") or ""
        except providers.ProviderError as e:
            providers.cool(e)
    return ""   # pas d'IA en ligne : on n'occupe pas le cerveau local


def reflect_async(user, reply, log, push=None):
    if not log and len(user) < 25:
        return   # échange trivial : rien à apprendre, on économise le quota

    def run():
        try:
            out = _llm(REFLECT.format(user=user[:800], log="\n".join(log)[:1500] or "(aucune)", reply=reply[:800]))
            m = re.search(r"\{.*\}", out, re.S)
            if not m:
                return
            d = json.loads(m.group(0))
            _add_lessons(d.get("lessons") or [])
            _add_facts(d.get("facts") or [])
            idea = (d.get("skill_idea") or "").strip()
            if idea and len(idea) > 10:
                ideas = _read(IDEAS, [])
                if _plain(idea) not in {_plain(i) for i in ideas}:
                    ideas.append(idea); _write(IDEAS, ideas[-30:])
                    if push:
                        push("idea", text=idea)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


# ---------- compétences écrites par Jarvis ----------
SKILL_TEMPLATE = '''"""{description}"""
SPEC = {spec}


{code}
'''


def _safe_name(n):
    n = re.sub(r"[^a-z0-9_]", "_", _plain(n))[:40].strip("_")
    return "skill_" + n if not n.startswith("skill_") else n


def create_skill(name: str, description: str, parameters: str, code: str):
    """Crée une compétence : code Python définissant `def run(...) -> str`. Validée par l'utilisateur avant activation."""
    nm = _safe_name(name)
    try:
        params = json.loads(parameters) if parameters.strip() else {"type": "object", "properties": {}, "required": []}
    except Exception:
        return "Erreur : parameters doit être un schéma JSON."
    if "def run(" not in code:
        return "Erreur : le code doit définir une fonction run(...) qui renvoie du texte."
    try:
        compile(code, nm, "exec")
    except SyntaxError as e:
        return f"Erreur de syntaxe : {e}"
    SKILLS.mkdir(parents=True, exist_ok=True)
    (SKILLS / f"{nm}.py").write_text(SKILL_TEMPLATE.format(description=description.replace('"""', "'"),
                                     spec=json.dumps({"name": nm, "description": description, "parameters": params}, ensure_ascii=False),
                                     code=code), encoding="utf-8")
    load_skills()
    return f"Compétence « {nm} » créée et active. Je peux l'utiliser dès maintenant."


def list_skills():
    files = sorted(SKILLS.glob("skill_*.py")) if SKILLS.exists() else []
    ideas = _read(IDEAS, [])
    out = [f"- {f.stem}" for f in files] or ["(aucune compétence)"]
    if ideas:
        out += ["Idées en attente :"] + [f"  • {i}" for i in ideas[-8:]]
    return "\n".join(out)


def delete_skill(name: str):
    f = SKILLS / f"{_safe_name(name)}.py"
    if f.exists():
        f.unlink()
        load_skills()
        return "Compétence supprimée."
    return "Compétence introuvable."


def load_skills():
    """Charge les compétences dans la liste des outils de Jarvis."""
    import tools, importlib.util
    for n in [n for n in tools.FUNCS if n.startswith("skill_")]:
        tools.FUNCS.pop(n, None)
    tools.SPECS[:] = [s for s in tools.SPECS if not s[0].startswith("skill_")]
    if not SKILLS.exists():
        return
    for f in sorted(SKILLS.glob("skill_*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            s = mod.SPEC
            tools.SPECS.append((s["name"], "[compétence apprise] " + s["description"], s["parameters"]))
            tools.FUNCS[s["name"]] = mod.run
        except Exception:
            continue


S = {"type": "string"}
SPECS = [
    ("recall", "Cherche dans ta mémoire longue (conversations passées, notes, leçons). À utiliser quand l'utilisateur évoque le passé.",
     {"type": "object", "properties": {"query": S}, "required": ["query"]}),
    ("create_skill", "Crée une nouvelle compétence (outil Python réutilisable) quand il te manque un outil pour une tâche répétitive. "
     "code = Python complet définissant def run(**params) -> str (bibliothèque standard, httpx, psutil, pyautogui disponibles). "
     "parameters = schéma JSON des paramètres de run.",
     {"type": "object", "properties": {"name": S, "description": S, "parameters": S, "code": S}, "required": ["name", "description", "code"]}),
    ("list_skills", "Liste les compétences apprises et les idées de compétences.", {"type": "object", "properties": {}, "required": []}),
    ("delete_skill", "Supprime une compétence apprise.", {"type": "object", "properties": {"name": S}, "required": ["name"]}),
]
FUNCS = {"recall": recall, "create_skill": create_skill, "list_skills": list_skills, "delete_skill": delete_skill}
DANGEROUS = {"create_skill", "delete_skill"}

"""Cerveau de Jarvis : cascade d'IA en ligne (Claude puis gratuites), Ollama en local en dernier recours."""
import json, os, socket, uuid, datetime

import httpx
import tools, providers

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
CONFIRM = os.getenv("CONFIRM_DANGEROUS", "true").lower() == "true"
MAX_STEPS = 25
# Modèle gardé en mémoire + contexte fixe : le début du prompt (consignes + outils) reste en cache
OLLAMA_OPTS = {"keep_alive": -1, "options": {"num_ctx": int(os.getenv("OLLAMA_CTX", "6144")), "num_predict": 600}}

import pathlib
HIST_FILE = pathlib.Path(__file__).parent / "data" / "history.json"
try:
    HISTORY = json.loads(HIST_FILE.read_text(encoding="utf-8"))   # mémoire de conversation persistante
except Exception:
    HISTORY = []          # [{role, content}] texte seulement, partagé PC + téléphone


def save_history():
    try:
        HIST_FILE.parent.mkdir(exist_ok=True)
        HIST_FILE.write_text(json.dumps(HISTORY[-60:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
PENDING = {}          # id -> état d'une tâche en attente de validation


def online():
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=2).close()
        return True
    except OSError:
        return False


def ollama_ok():
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


def start_ollama(wait=25):
    """Lance Ollama s'il ne tourne pas (ex : juste après le démarrage du PC)."""
    import subprocess, time, shutil
    exe = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
    try:
        subprocess.Popen([exe, "serve"], creationflags=0x08000000 if os.name == "nt" else 0,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    for _ in range(wait):
        time.sleep(1)
        if ollama_ok():
            return True
    return False


GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


COMPLEX = ("analyse", "analyser", "code", "programme", "script", "cree", "creer", "competence", "strategie", "plan", "redige",
           "rediger", "compare", "resume", "explique", "organise", "range", "plusieurs", "ensuite", "puis", "automatis", "projet")


def level(message):
    """simple / complexe : choisit le niveau d'IA juste nécessaire."""
    m = _plain(message)
    return "complex" if len(m.split()) > 35 or sum(k in m for k in COMPLEX) >= 1 else "simple"


def chain(lvl="complex"):
    """Ordre d'essai selon le niveau : simple → IA rapides/économes d'abord ; complexe → les plus puissantes d'abord.
    Si une IA n'a plus de quota, on passe à la suivante ; le cerveau local en dernier."""
    out = []
    if online():
        av = providers.available()
        tiers = {"top": 0, "mid": 1, "fast": 2}
        key = (lambda p: tiers.get(providers.PRESETS.get(p["id"], {}).get("tier"), 1)) if lvl == "complex" \
            else (lambda p: -tiers.get(providers.PRESETS.get(p["id"], {}).get("tier"), 1))
        claude_ok = os.getenv("ANTHROPIC_API_KEY") and providers.COOL.get("claude", (0,))[0] < __import__("time").time()
        if claude_ok and lvl == "complex":
            out.append("claude")
        out += ["oa:" + p["id"] for p in sorted(av, key=key)]
        if claude_ok and lvl == "simple":
            out.append("claude")
    if ollama_ok() or start_ollama():
        out.append("ollama")
    return out


def pick_backend():
    c = chain()
    return c[0] if c else None


def system_prompt():
    notes = "\n".join(f"- {n['note']}" for n in tools.load_notes()[-50:]) or "(aucune)"
    return (
        "Tu es JARVIS, l'assistant personnel d'Aslambek, sur son PC Windows. "
        "Réponds en français, le plus court possible : l'essentiel seulement, une à trois phrases, ton calme et légèrement britannique. "
        "Si une demande est impossible avec tes outils, ne refuse pas : crée la compétence nécessaire avec create_skill, puis réalise la tâche. "
        "Pour une tâche lourde décomposable, délègue les sous-tâches simples avec delegate (niveau simple) et garde le niveau complexe pour l'essentiel. "
        "Pour run_command, écris du PowerShell valide (guillemets simples de préférence) ; si une commande échoue, corrige-la au lieu de la relancer à l'identique. "
        "Tes réponses sont lues à voix haute : pas de markdown, pas de listes longues. "
        "Tu contrôles son PC (outils sans préfixe) et son téléphone Android Redmi (outils phone_*). "
        "Pour agir dans une appli du téléphone : phone_open, puis phone_screen pour voir l'écran, puis phone_tap / phone_type. "
        "Tu gères aussi Gmail (gmail_*), Google Agenda (calendar_*) et la musique (media_control, music_search) sur le PC ou le téléphone. "
        "Tu apprends en continu : recall pour chercher dans ta mémoire longue ; si une tâche revient souvent ou qu'il te manque un outil, "
        "propose puis crée une compétence avec create_skill (l'utilisateur la valide). "
        "Tu as des yeux : screen_look (écran du PC) et phone_look (écran du téléphone) quand il faut voir une image, une vidéo ou une interface. "
        "Tu exécutes réellement les tâches avec tes outils ; enchaîne autant d'étapes que nécessaire, "
        "vérifie le résultat, puis rends compte en une ou deux phrases. "
        f"Ce que tu sais de l'utilisateur :\n{notes}"
    )


GROUPS = {
    "phone": (("telephone", "mobile", "redmi", "portable", "phone", "sms", "notif", "appel", "whatsapp", "insta", "tiktok", "snap"),
              lambda n: n.startswith("phone_")),
    "google": (("mail", "courrier", "agenda", "rendez", "rdv", "calendrier", "evenement", "reunion", "brouillon"),
               lambda n: n.startswith(("gmail_", "calendar_"))),
    "media": (("musique", "spotify", "chanson", "volume", "pause", "lecture", "suivant", "precedent", "morceau", "titre", "artiste", "playlist", "son "),
              lambda n: n in ("media_control", "music_search")),
}


def _plain(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def select_tools(messages):
    """Envoie seulement les outils utiles (requêtes plus légères = plus rapides, limites Groq respectées)."""
    recent = " ".join(_plain(m["content"]) for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str))[-1500:]
    special = [f for _, (kw, f) in GROUPS.items()]
    wanted = [f for kw, f in GROUPS.values() if any(k in recent for k in kw)]
    return [s for s in tools.SPECS if not any(f(s[0]) for f in special) or any(f(s[0]) for f in wanted)]


def _claude_tools():
    t = [{"name": n, "description": d, "input_schema": s} for n, d, s in tools.SPECS]
    t[-1]["cache_control"] = {"type": "ephemeral"}
    return t


def _ollama_tools():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": s}}
            for n, d, s in tools.SPECS]


def _call_model(st):
    """Appelle le modèle ; remplit st['queue'] ou renvoie le texte final."""
    if st["backend"] == "claude":
        import anthropic
        try:
            r = anthropic.Anthropic().messages.create(
                model=CLAUDE_MODEL, max_tokens=4096,
                system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
                tools=_claude_tools(), messages=st["messages"])
        except anthropic.APIStatusError as e:
            raise providers.ProviderError("claude", e.status_code, str(e), e.response.headers.get("retry-after"))
        except anthropic.APIConnectionError as e:
            raise providers.ProviderError("claude", 503, str(e))
        st["messages"].append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
        calls = [{"id": b.id, "name": b.name, "args": b.input} for b in r.content if b.type == "tool_use"]
        text = " ".join(b.text for b in r.content if b.type == "text").strip()
    elif st["backend"].startswith("oa:"):
        p = next((x for x in providers.load() if x["id"] == st["backend"][3:]), None)
        specs = select_tools(st["messages"])
        otools = [{"type": "function", "function": {"name": n, "description": d, "parameters": s}} for n, d, s in specs]
        msg = providers.call(p, [{"role": "system", "content": system_prompt()}] + st["messages"], otools)
        msg = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
        msg["role"] = "assistant"
        st["messages"].append(msg)
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            calls.append({"id": c["id"], "name": c["function"]["name"], "args": args})
        text = (msg.get("content") or "").strip()
    else:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
            "model": OLLAMA_MODEL, "stream": False, "tools": _ollama_tools(), **OLLAMA_OPTS,
            "messages": [{"role": "system", "content": system_prompt()}] + st["messages"]}).json()
        msg = r.get("message", {})
        st["messages"].append(msg)
        calls = [{"id": uuid.uuid4().hex, "name": c["function"]["name"],
                  "args": c["function"].get("arguments") or {}} for c in msg.get("tool_calls") or []]
        text = (msg.get("content") or "").strip()
    st["queue"], st["results"] = calls, []
    return None if calls else text


def _flush(st):
    if st["backend"] == "claude":
        st["messages"].append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c["id"], "content": out} for c, out in st["results"]]})
    elif st["backend"].startswith("oa:"):
        for c, out in st["results"]:
            st["messages"].append({"role": "tool", "tool_call_id": c["id"], "content": out[:6000]})
    else:
        for c, out in st["results"]:
            st["messages"].append({"role": "tool", "content": out, "tool_name": c["name"]})


def _loop(st):
    while True:
        while st["queue"]:
            c = st["queue"][0]
            if CONFIRM and c["name"] in tools.DANGEROUS and not c.get("approved"):
                pid = uuid.uuid4().hex[:10]
                PENDING[pid] = st
                return {"confirm": {"id": pid, "tool": c["name"], "args": c["args"]},
                        "log": st["log"], "backend": st["backend"]}
            st["queue"].pop(0)
            out = tools.execute(c["name"], c["args"])
            st["log"].append(f"{c['name']} → {out[:160]}")
            st["results"].append((c, out))
        if st["results"]:
            _flush(st)
        st["steps"] += 1
        if st["steps"] > MAX_STEPS:
            return _finish(st, "J'ai atteint la limite d'étapes. Dites-moi si je continue.")
        text = _call_model(st)
        if text is not None:
            return _finish(st, text)


def _finish(st, text):
    HISTORY.append({"role": "assistant", "content": text})
    del HISTORY[:-60]
    save_history()
    return {"reply": text, "log": st["log"], "backend": st["backend"]}


def ask(message):
    order = chain(level(message))
    if not order:
        return {"reply": "Mon cerveau local démarre encore. Réessayez dans une minute, monsieur.",
                "backend": None, "log": []}
    now = datetime.datetime.now()
    jour = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][now.weekday()]
    HISTORY.append({"role": "user", "content": f"[{jour} {now:%d/%m/%Y %H:%M}] {message}"})
    log, err = [], ""
    import learning
    lessons = learning.relevant_lessons(message)
    for backend in order:
        keep = 30 if backend in ("claude", "ollama") else 12
        msgs = [dict(m) for m in HISTORY[-keep:]]
        if lessons:
            msgs[-1]["content"] = "[Leçons apprises lors de tâches similaires : " + " | ".join(lessons) + "]\n" + msgs[-1]["content"]
        st = {"backend": backend, "messages": msgs, "queue": [], "results": [], "steps": 0, "log": log}
        try:
            text = _call_model(st)
            res = _finish(st, text) if text is not None else _loop(st)
            res["backend"] = backend
            if not res.get("confirm"):
                learn(message, res)
            return res
        except providers.ProviderError as e:
            providers.cool(e)
            err = str(e)
            log.append(f"{backend.replace('oa:', '')} indisponible ({e.status}) → IA suivante")
        except Exception as e:
            err = str(e)
            log.append(f"{backend.replace('oa:', '')} en erreur → IA suivante")
    return {"reply": f"Toutes mes IA sont indisponibles pour le moment, monsieur. ({err[:150]})", "backend": None, "log": log}


def delegate(task: str, level: str = "simple"):
    """Sous-agent : exécute une sous-tâche avec le niveau d'IA demandé (simple = rapide/économe, complex = puissant)."""
    order = chain("complex" if level.startswith("c") else "simple")
    for backend in order:
        st = {"backend": backend, "messages": [{"role": "user", "content": task}], "queue": [], "results": [],
              "steps": 12, "log": [], "sub": True}
        try:
            text = _call_model(st)
            while text is None:
                for c in st["queue"]:
                    out = "Refusé : un sous-agent ne peut pas faire d'action sensible." if c["name"] in tools.DANGEROUS or c["name"] == "delegate" \
                        else tools.execute(c["name"], c["args"])
                    st["results"].append((c, out))
                st["queue"] = []
                _flush(st); st["steps"] += 1
                if st["steps"] > MAX_STEPS:
                    break
                text = _call_model(st)
            return f"[sous-agent {backend.replace('oa:', '')}] {text or 'sans réponse'}"
        except providers.ProviderError as e:
            providers.cool(e)
        except Exception as e:
            return f"Sous-agent en erreur : {e}"
    return "Aucune IA disponible pour le sous-agent."


def learn(message, res):
    """Archive l'échange et lance l'analyse en arrière-plan (leçons, faits, idées de compétences)."""
    try:
        import learning, wake
        learning.archive(message, res.get("reply", ""), res.get("log", []))
        learning.reflect_async(message, res.get("reply", ""), res.get("log", []), push=wake.push)
    except Exception:
        pass


def resume(pid, approve):
    st = PENDING.pop(pid, None)
    if not st:
        return {"reply": "Cette demande a expiré.", "log": []}
    c = st["queue"][0]
    if approve:
        c["approved"] = True
    else:
        st["queue"].pop(0)
        st["results"].append((c, "Refusé par l'utilisateur."))
        st["log"].append(f"{c['name']} → refusé")
    try:
        return _loop(st)
    except Exception as e:
        return {"reply": f"Je rencontre un problème, monsieur : {str(e)[:200]}", "log": st["log"]}


def warmup():
    """Charge le modèle local et met en cache consignes + outils dès le démarrage."""
    import threading
    def run():
        try:
            if ollama_ok() or start_ollama():
                httpx.post(f"{OLLAMA_URL}/api/chat", timeout=900, json={
                    "model": OLLAMA_MODEL, "stream": False, "tools": _ollama_tools(), **OLLAMA_OPTS,
                    "messages": [{"role": "system", "content": system_prompt()},
                                 {"role": "user", "content": "ok"}]})
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

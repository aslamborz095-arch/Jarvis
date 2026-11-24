"""Cerveau de Jarvis : Claude en ligne, Ollama en local si coupure."""
import json, os, socket, uuid, datetime

import httpx
import tools

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
CONFIRM = os.getenv("CONFIRM_DANGEROUS", "true").lower() == "true"
MAX_STEPS = 25

HISTORY = []          # [{role, content}] texte seulement, partagé PC + téléphone
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


def pick_backend():
    if os.getenv("ANTHROPIC_API_KEY") and online():
        return "claude"
    if ollama_ok():
        return "ollama"
    return None


def system_prompt():
    notes = "\n".join(f"- {n['note']}" for n in tools.load_notes()[-50:]) or "(aucune)"
    return (
        "Tu es JARVIS, l'assistant personnel d'Aslambek, sur son PC Windows. "
        "Réponds en français, court, précis, ton calme et légèrement britannique. "
        "Tes réponses sont lues à voix haute : pas de markdown, pas de listes longues. "
        "Tu exécutes réellement les tâches avec tes outils ; enchaîne autant d'étapes que nécessaire, "
        "vérifie le résultat, puis rends compte en une ou deux phrases. "
        f"Date : {datetime.datetime.now():%A %d %B %Y %H:%M}.\n"
        f"Ce que tu sais de l'utilisateur :\n{notes}"
    )


def _claude_tools():
    return [{"name": n, "description": d, "input_schema": s} for n, d, s in tools.SPECS]


def _ollama_tools():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": s}}
            for n, d, s in tools.SPECS]


def _call_model(st):
    """Appelle le modèle ; remplit st['queue'] ou renvoie le texte final."""
    if st["backend"] == "claude":
        import anthropic
        r = anthropic.Anthropic().messages.create(
            model=CLAUDE_MODEL, max_tokens=4096, system=system_prompt(),
            tools=_claude_tools(), messages=st["messages"])
        st["messages"].append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
        calls = [{"id": b.id, "name": b.name, "args": b.input} for b in r.content if b.type == "tool_use"]
        text = " ".join(b.text for b in r.content if b.type == "text").strip()
    else:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
            "model": OLLAMA_MODEL, "stream": False, "tools": _ollama_tools(),
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
    del HISTORY[:-30]
    return {"reply": text, "log": st["log"], "backend": st["backend"]}


def ask(message):
    backend = pick_backend()
    if not backend:
        return {"reply": "Aucun cerveau disponible : pas d'internet ni de clé Claude, et Ollama ne répond pas.",
                "backend": None, "log": []}
    HISTORY.append({"role": "user", "content": message})
    st = {"backend": backend, "messages": [dict(m) for m in HISTORY[-30:]],
          "queue": [], "results": [], "steps": 0, "log": []}
    try:
        text = _call_model(st)
        return _finish(st, text) if text is not None else _loop(st)
    except Exception as e:
        if backend == "claude" and ollama_ok():   # bascule locale si Claude plante
            st.update(backend="ollama", messages=[dict(m) for m in HISTORY[-30:]], queue=[], results=[])
            text = _call_model(st)
            return _finish(st, text) if text is not None else _loop(st)
        return {"reply": f"Erreur : {e}", "backend": backend, "log": st["log"]}


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
    return _loop(st)

"""Cascade de cerveaux en ligne : Jarvis essaie chaque IA dans l'ordre et passe à la suivante
quand une n'a plus de crédit / de quota, puis termine sur le cerveau local."""
import os, json, time, pathlib

BASE = pathlib.Path(__file__).parent
FILE = BASE / "data" / "providers.json"
COOL = {}   # id -> (jusqu'à quand, raison)

# Fournisseurs connus (API compatible OpenAI). "free" = offre gratuite sans carte bancaire.
PRESETS = {}   # rempli par presets.py
try:
    from presets import PRESETS  # noqa
except Exception:
    pass


class ProviderError(Exception):
    def __init__(self, pid, status, msg, retry_after=None):
        super().__init__(f"{pid} {status} : {msg[:160]}")
        self.pid, self.status, self.retry_after = pid, status, retry_after


def load():
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        items = []
    # migration : ancienne clé Groq unique
    if os.getenv("GROQ_API_KEY") and not any(p["id"] == "groq" for p in items):
        items.append({"id": "groq", **{k: v for k, v in PRESETS.get("groq", {}).items() if k in ("name", "base", "model")},
                      "key": os.getenv("GROQ_API_KEY")})
        save(items)
    return items


def save(items):
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def add(pid, key, model=""):
    p = PRESETS.get(pid)
    if not p:
        raise ValueError("Fournisseur inconnu")
    items = [x for x in load() if x["id"] != pid]
    items.append({"id": pid, "name": p["name"], "base": p["base"], "model": model or p["model"], "key": key.strip()})
    # ordre : du plus puissant au plus modeste
    items.sort(key=lambda x: PRESETS.get(x["id"], {}).get("rank", 50))
    save(items)
    COOL.pop(pid, None)


def remove(pid):
    save([x for x in load() if x["id"] != pid])
    COOL.pop(pid, None)


def available():
    now = time.time()
    return [p for p in load() if COOL.get(p["id"], (0,))[0] < now]


def cool(err):
    """Met un fournisseur en pause selon l'erreur reçue."""
    s = err.status
    if s == 429:
        dur = min(float(err.retry_after or 0) or 600, 6 * 3600)      # quota/minute ou /jour
        why = "quota atteint"
    elif s in (401, 402, 403):
        dur, why = 6 * 3600, "crédit épuisé ou clé refusée"
    elif s in (400, 404, 413, 422):
        dur, why = 120, "requête refusée"
    else:
        dur, why = 300, "indisponible"
    COOL[err.pid] = (time.time() + dur, why)


def state():
    now = time.time()
    out = []
    for p in load():
        until, why = COOL.get(p["id"], (0, ""))
        out.append({"id": p["id"], "name": p["name"], "model": p["model"],
                    "status": "ok" if until < now else f"en pause ({why}, {int((until - now) / 60) + 1} min)"})
    return out


# Modèles de secours chez le même fournisseur : chaque modèle a son propre quota gratuit
ALTS = {"groq": ["llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b"],
        "gemini": ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3.1:free"]}
MODEL_COOL = {}   # (fournisseur, modèle) -> jusqu'à quand


def _post(p, model, messages, tools_spec, max_tokens):
    import httpx
    try:
        r = httpx.post(p["base"].rstrip("/") + "/chat/completions", timeout=120,
                       headers={"Authorization": f"Bearer {p['key']}", "HTTP-Referer": "http://127.0.0.1:8765", "X-Title": "Jarvis"},
                       json={k: v for k, v in {"model": model, "messages": messages, "tools": tools_spec,
                                               "max_tokens": max_tokens}.items() if v is not None})
    except httpx.HTTPError as e:
        raise ProviderError(p["id"], 503, str(e))
    if r.status_code != 200:
        raise ProviderError(p["id"], r.status_code, r.text, r.headers.get("retry-after"))
    data = r.json()
    if "choices" not in data or not data["choices"]:
        raise ProviderError(p["id"], 502, json.dumps(data)[:200])
    return data["choices"][0]["message"]


def call(p, messages, tools_spec, max_tokens=1200):
    """Appelle le modèle principal ; s'il a atteint son quota (429), essaie les modèles de secours du même fournisseur."""
    now = time.time()
    models = [p["model"]] + [m for m in ALTS.get(p["id"], []) if m != p["model"]]
    last = None
    for m in models:
        if MODEL_COOL.get((p["id"], m), 0) > now:
            continue
        try:
            return _post(p, m, messages, tools_spec, max_tokens)
        except ProviderError as e:
            last = e
            if e.status == 429:
                MODEL_COOL[(p["id"], m)] = now + min(float(e.retry_after or 0) or 600, 6 * 3600)
            elif e.status in (400, 404, 422) and m != p["model"]:
                MODEL_COOL[(p["id"], m)] = now + 24 * 3600   # modèle de secours inexistant ou incompatible
            else:
                raise
    raise last or ProviderError(p["id"], 429, "tous les modèles de ce fournisseur sont en pause")

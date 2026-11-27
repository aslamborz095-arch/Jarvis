"""Mesure des réussites de Jarvis : taux de succès et durée par outil, par cerveau (IA) et par rôle d'équipe.

Sert à :
- reclasser les cerveaux (une IA qui échoue souvent passe en fin de cascade) ;
- signaler à l'auto-évolution les outils faibles (taux < 70 % sur au moins 5 appels) ;
- répondre à « performance_report ».
"""
import json, re, time, threading, pathlib

FILE = pathlib.Path(__file__).parent / "data" / "metrics.json"
_lock = threading.Lock()
_dirty = [0, time.time()]
FAIL = re.compile(r"^\s*(erreur|échec|echec|refusé|impossible|aucune ia)|délai dépassé|code=[1-9]", re.I)

try:
    M = json.loads(FILE.read_text(encoding="utf-8"))
except Exception:
    M = {}
for k in ("tools", "brains", "roles"):
    M.setdefault(k, {})


def _save(force=False):
    _dirty[0] += 1
    if not force and _dirty[0] < 10 and time.time() - _dirty[1] < 60:
        return
    try:
        FILE.parent.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(M, ensure_ascii=False), encoding="utf-8")
        _dirty[:] = [0, time.time()]
    except Exception:
        pass


def _rec(kind, name, ok, ms, err=""):
    with _lock:
        x = M[kind].setdefault(name, {"n": 0, "ok": 0, "ms": 0, "recent": [], "last_err": ""})
        x["n"] += 1; x["ok"] += 1 if ok else 0; x["ms"] += int(ms)
        x["recent"] = (x["recent"] + [1 if ok else 0])[-20:]   # fenêtre glissante : reflète l'état actuel
        if not ok and err:
            x["last_err"] = str(err)[:200]
        _save()


def tool_failed(out):
    return bool(FAIL.search(str(out)[:200]))


def record_tool(name, out, ms):
    _rec("tools", name, not tool_failed(out), ms, out)


def record_brain(backend, ok, ms, err=""):
    _rec("brains", backend, ok, ms, err)


def record_role(role, ok, ms):
    _rec("roles", role, ok, ms)


def rate(kind, name):
    """Taux de réussite récent (lissé) ; None si trop peu de données."""
    x = M[kind].get(name)
    if not x or len(x["recent"]) < 5:
        return None
    return (sum(x["recent"]) + 1) / (len(x["recent"]) + 2)


def rank_brains(order):
    """Garde l'ordre voulu mais relègue en fin (avant le local) les IA qui échouent souvent."""
    head = [b for b in order if b != "ollama"]
    bad = [b for b in head if (rate("brains", b) or 1) < 0.6]
    return [b for b in head if b not in bad] + bad + [b for b in order if b == "ollama"]


def weak_tools(limit=6):
    out = []
    for n, x in M["tools"].items():
        r = rate("tools", n)
        if r is not None and r < 0.7:
            out.append({"outil": n, "reussite": round(r * 100), "appels": x["n"], "derniere_erreur": x["last_err"]})
    return sorted(out, key=lambda e: e["reussite"])[:limit]


def summary():
    def tab(kind):
        return {n: {"appels": x["n"], "reussite_pct": round(100 * x["ok"] / max(1, x["n"])),
                    "recent_pct": round(100 * sum(x["recent"]) / max(1, len(x["recent"]))),
                    "ms_moy": x["ms"] // max(1, x["n"]), "derniere_erreur": x.get("last_err", "")[:160]} for n, x in M[kind].items()}
    return {"outils": tab("tools"), "cerveaux": tab("brains"), "roles": tab("roles"), "faibles": weak_tools()}


def performance_report():
    s = summary()
    tot = sum(v["appels"] for v in s["outils"].values())
    ok = sum(v["appels"] * v["reussite_pct"] / 100 for v in s["outils"].values())
    best = sorted(s["cerveaux"].items(), key=lambda kv: -kv[1]["recent_pct"])[:3]
    txt = f"{tot} actions mesurées, {round(100 * ok / max(1, tot))} % réussies."
    if best:
        txt += " Cerveaux : " + ", ".join(f"{n.replace('oa:', '')} {v['recent_pct']} %" for n, v in best) + "."
    if s["faibles"]:
        txt += " Points faibles : " + ", ".join(f"{w['outil']} {w['reussite']} %" for w in s["faibles"][:3]) + "."
    return txt


def flush():
    with _lock:
        _save(force=True)


SPECS = [("performance_report", "Taux de réussite de Jarvis : actions, cerveaux (IA), points faibles.", {"type": "object", "properties": {}, "required": []})]
FUNCS = {"performance_report": performance_report}
DANGEROUS = set()

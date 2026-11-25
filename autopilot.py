"""Autonomie PC : Jarvis pilote l'écran tout seul.
Boucle : capture → vision (où cliquer / quoi taper) → action souris/clavier → nouvelle capture,
jusqu'à ce que la tâche soit finie. Arrêt d'urgence : souris dans un coin de l'écran, ou /api/autopilot/stop."""
import io, os, re, json, time, base64, threading

import httpx

STATE = {"running": False, "goal": "", "step": 0, "last": "", "stop": False}
LOCK = threading.Lock()
GRID = 100          # pas de la grille dessinée sur la capture (pixels image)
MAX_W = 1366        # largeur envoyée à la vision

PROMPT = """Tu pilotes un PC Windows à la souris et au clavier pour accomplir ce but :
« {goal} »

Image : capture de l'écran, {w}x{h} pixels, avec une grille rouge tous les {g} px (coordonnées notées sur les bords).
Actions déjà faites :
{hist}

Choisis UNE seule action suivante. Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{{"think": "ce que tu vois et pourquoi (court)",
 "action": "click" | "double_click" | "right_click" | "type" | "hotkey" | "scroll" | "wait" | "done" | "fail",
 "x": entier, "y": entier,          // centre exact de l'élément, coordonnées de CETTE image (click/double_click/right_click/scroll)
 "text": "texte à taper",           // type (ajoute "\\n" pour Entrée)
 "keys": "ctrl+l",                  // hotkey (ex: win, enter, alt+tab, ctrl+s)
 "amount": -5,                      // scroll : négatif = descendre
 "result": "résumé pour l'utilisateur"}} // done / fail

Règles :
- Vise le centre des boutons et champs. Clique dans un champ avant d'y taper.
- Pour ouvrir une appli : hotkey "win", puis type le nom + "\\n".
- Si l'écran n'a pas changé après ton action, essaie autre chose.
- "done" dès que le but est atteint (vérifie sur l'image). "fail" si impossible.
- Ne valide jamais un paiement, un achat, une suppression définitive ou un envoi de message sans que le but le demande explicitement : dans ce cas "fail" avec l'explication."""


def _grab():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=False)


def _prepare(shot):
    """Réduit la capture et dessine une grille repère (aide la vision à viser juste)."""
    from PIL import ImageDraw
    img = shot.convert("RGB")
    if img.width > MAX_W:
        img = img.resize((MAX_W, int(img.height * MAX_W / img.width)))
    d = ImageDraw.Draw(img)
    for x in range(GRID, img.width, GRID):
        d.line([(x, 0), (x, img.height)], fill=(255, 0, 0), width=1)
        d.text((x + 2, 2), str(x), fill=(255, 0, 0)); d.text((x + 2, img.height - 12), str(x), fill=(255, 0, 0))
    for y in range(GRID, img.height, GRID):
        d.line([(0, y), (img.width, y)], fill=(255, 0, 0), width=1)
        d.text((2, y + 2), str(y), fill=(255, 0, 0)); d.text((img.width - 30, y + 2), str(y), fill=(255, 0, 0))
    b = io.BytesIO(); img.save(b, "JPEG", quality=75)
    return base64.b64encode(b.getvalue()).decode(), img.size


def _vision(data, prompt):
    """Gemini (meilleur pour viser) → Groq → Claude si clé. Renvoie le texte brut."""
    import providers
    errs = []
    order = sorted(providers.available(), key=lambda p: {"gemini": 0, "groq": 1}.get(p["id"], 5))
    for p in order:
        model = {"gemini": os.getenv("GEMINI_VISION_MODEL", p["model"]),
                 "groq": os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")}.get(p["id"])
        if not model:
            continue
        try:
            r = httpx.post(p["base"].rstrip("/") + "/chat/completions", timeout=90,
                           headers={"Authorization": f"Bearer {p['key']}"},
                           json={"model": model, "max_tokens": 600, "temperature": 0, "messages": [{"role": "user", "content": [
                               {"type": "text", "text": prompt},
                               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}]})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"] or ""
            if r.status_code in (401, 402, 403, 429):
                providers.cool(providers.ProviderError(p["id"], r.status_code, r.text, r.headers.get("retry-after")))
            errs.append(f"{p['id']} {r.status_code}")
        except Exception as e:
            errs.append(f"{p['id']} {type(e).__name__}")
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic, brain
        r = anthropic.Anthropic().messages.create(model=brain.CLAUDE_MODEL, max_tokens=600, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": prompt}]}])
        return r.content[0].text
    raise RuntimeError("Vision indisponible (" + ", ".join(errs or ["aucune clé Gemini/Groq"]) + ")")


def _parse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        raise ValueError("réponse sans JSON")
    s = re.sub(r"//[^\n\"]*\n", "\n", m.group(0))   # commentaires éventuels
    return json.loads(s)


def _act(a, k):
    """Exécute l'action ; k = facteur image → écran réel."""
    import pyautogui
    pyautogui.FAILSAFE = True          # souris dans un coin = arrêt immédiat
    t = a.get("action")
    X, Y = int(float(a.get("x", 0)) * k), int(float(a.get("y", 0)) * k)
    if t in ("click", "double_click", "right_click"):
        pyautogui.moveTo(X, Y, duration=0.25)
        {"click": pyautogui.click, "double_click": pyautogui.doubleClick, "right_click": pyautogui.rightClick}[t]()
        return f"{t} ({X},{Y})"
    if t == "type":
        txt = str(a.get("text", ""))
        enter = txt.endswith("\n")
        txt = txt.rstrip("\n")
        if txt.isascii():
            pyautogui.write(txt, interval=0.02)
        else:                            # accents : passer par le presse-papiers
            _paste(txt)
        if enter:
            pyautogui.press("enter")
        return f"tape « {txt[:40]} »" + (" + Entrée" if enter else "")
    if t == "hotkey":
        keys = [x.strip().lower() for x in str(a.get("keys", "")).split("+") if x.strip()]
        pyautogui.hotkey(*keys)
        return "touches " + "+".join(keys)
    if t == "scroll":
        if a.get("x") is not None:
            pyautogui.moveTo(X, Y, duration=0.2)
        pyautogui.scroll(int(a.get("amount", -5)) * 100)
        return f"défile {a.get('amount', -5)}"
    if t == "wait":
        time.sleep(2)
        return "attend"
    raise ValueError(f"action inconnue {t}")


def _paste(txt):
    import subprocess, pyautogui
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], input=txt, text=True,
                   creationflags=0x08000000 if os.name == "nt" else 0, timeout=10)
    pyautogui.hotkey("ctrl", "v")


def screen_task(goal: str, max_steps: int = 20):
    """Accomplit une tâche en pilotant l'écran du PC (vision + souris + clavier), en boucle jusqu'au bout."""
    if not LOCK.acquire(blocking=False):
        return "Une tâche écran est déjà en cours."
    STATE.update(running=True, goal=goal, step=0, last="", stop=False)
    hist, fails = [], 0
    try:
        for i in range(1, min(int(max_steps), 40) + 1):
            if STATE["stop"]:
                return "Arrêté à ta demande. Fait : " + "; ".join(hist[-5:])
            STATE["step"] = i
            shot = _grab()
            data, (w, h) = _prepare(shot)
            prompt = PROMPT.format(goal=goal, w=w, h=h, g=GRID,
                                   hist="\n".join(f"{n}. {x}" for n, x in enumerate(hist[-12:], 1)) or "(aucune)")
            try:
                a = _parse(_vision(data, prompt))
            except ValueError:
                fails += 1
                if fails >= 3:
                    return "Échec : la vision ne renvoie pas d'action exploitable."
                continue
            t = a.get("action")
            if t == "done":
                return "✅ " + (a.get("result") or "Tâche terminée.") + f" ({len(hist)} actions)"
            if t == "fail":
                return "❌ " + (a.get("result") or a.get("think") or "Impossible.")
            try:
                done = _act(a, shot.width / w)
            except Exception as e:
                if type(e).__name__ == "FailSafeException":
                    return "Arrêt d'urgence (souris dans un coin)."
                done = f"erreur {e}"
            line = f"{done} — {str(a.get('think', ''))[:80]}"
            hist.append(line)
            STATE["last"] = line
            time.sleep(1.2)            # laisse l'écran réagir
        return "⏳ Pas fini après le nombre d'étapes maximum. Dernières actions : " + "; ".join(hist[-5:])
    finally:
        STATE["running"] = False
        LOCK.release()


def screen_stop():
    """Arrête la tâche écran en cours."""
    STATE["stop"] = True
    return "Arrêt demandé." if STATE["running"] else "Aucune tâche écran en cours."


S = {"type": "string"}
SPECS = [
    ("screen_task", "Accomplit une tâche en pilotant l'écran du PC tout seul (regarde, clique, tape, boucle jusqu'au bout). "
                    "À utiliser quand aucun outil direct (commande, fichier, appli, web) ne suffit : appli sans API, site, réglages Windows, formulaire.",
     {"type": "object", "properties": {"goal": S, "max_steps": {"type": "integer"}}, "required": ["goal"]}),
    ("screen_stop", "Arrête la tâche écran en cours.", {"type": "object", "properties": {}, "required": []}),
]
FUNCS = {"screen_task": screen_task, "screen_stop": screen_stop}
DANGEROUS = {"screen_task"}

"""Vision : Jarvis regarde l'écran du PC ou du téléphone et répond à une question."""
import io, os, base64

import httpx

GROQ_VISION = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")


def _jpeg(img, max_w=1280):
    from PIL import Image
    if not isinstance(img, Image.Image):
        img = Image.open(io.BytesIO(img))
    img = img.convert("RGB")
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    b = io.BytesIO(); img.save(b, "JPEG", quality=80)
    return base64.b64encode(b.getvalue()).decode(), img.size


def ask(img, question):
    data, (w, h) = _jpeg(img)
    q = (f"{question}\nRéponds en français, précis et court. L'image fait {w}x{h} pixels ; "
         "si on te demande où cliquer, donne des coordonnées approximatives dans cette image.")
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        import brain
        r = anthropic.Anthropic().messages.create(model=brain.CLAUDE_MODEL, max_tokens=800, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": q}]}])
        return r.content[0].text, (w, h)
    if os.getenv("GROQ_API_KEY"):
        r = httpx.post("https://api.groq.com/openai/v1/chat/completions", timeout=90,
                       headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
                       json={"model": GROQ_VISION, "max_tokens": 800, "messages": [{"role": "user", "content": [
                           {"type": "text", "text": q},
                           {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}]})
        if r.status_code != 200:
            return f"Vision indisponible (Groq {r.status_code}) : {r.text[:150]}", (w, h)
        return r.json()["choices"][0]["message"]["content"], (w, h)
    return "Vision indisponible : il faut une clé Groq ou Claude (bouton ⚙).", (w, h)


def screen_look(question: str = "Décris ce qui est affiché à l'écran."):
    """Capture l'écran du PC et l'analyse."""
    from PIL import ImageGrab
    shot = ImageGrab.grab(all_screens=False)
    sw, _ = shot.size
    text, (w, _) = ask(shot, question)
    k = sw / w
    return f"{text}\n(Pour cliquer avec l'outil mouse, multiplie les coordonnées de l'image par {k:.2f}.)"


def phone_look(question: str = "Décris ce qui est affiché à l'écran du téléphone."):
    """Capture l'écran du téléphone et l'analyse."""
    import subprocess, phone
    d = phone.device()
    if not d:
        return "Téléphone non connecté."
    png = subprocess.run([phone.adb_path(), "-s", d, "exec-out", "screencap", "-p"], capture_output=True,
                         timeout=40, creationflags=phone.NOWIN).stdout
    from PIL import Image
    img = Image.open(io.BytesIO(png))
    text, (w, _) = ask(img, question)
    return f"{text}\n(Pour toucher avec phone_tap x,y, multiplie les coordonnées de l'image par {img.width / w:.2f}.)"


S = {"type": "string"}
SPECS = [
    ("screen_look", "Regarde l'écran du PC et répond à une question (lire, trouver un bouton, comprendre).",
     {"type": "object", "properties": {"question": S}, "required": []}),
    ("phone_look", "Regarde l'écran du téléphone (capture) et répond à une question.",
     {"type": "object", "properties": {"question": S}, "required": []}),
]
FUNCS = {"screen_look": screen_look, "phone_look": phone_look}

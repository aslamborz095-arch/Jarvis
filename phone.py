"""Contrôle du téléphone Android (Redmi) par ADB sans fil.

Association une seule fois : Options pour les développeurs → Débogage sans fil →
« Associer l'appareil avec un code » → saisir l'adresse et le code dans le panneau 📱 de Jarvis.
"""
import io, os, re, shutil, zipfile, subprocess, unicodedata, pathlib, xml.etree.ElementTree as ET

BASE = pathlib.Path(__file__).parent
PT = BASE / "data" / "platform-tools"
ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
NOWIN = 0x08000000 if os.name == "nt" else 0

APPS = {  # noms courants → paquets Android
    "whatsapp": "com.whatsapp", "youtube": "com.google.android.youtube", "chrome": "com.android.chrome",
    "gmail": "com.google.android.gm", "maps": "com.google.android.apps.maps", "spotify": "com.spotify.music",
    "instagram": "com.instagram.android", "tiktok": "com.zhiliaoapp.musically", "snapchat": "com.snapchat.android",
    "facebook": "com.facebook.katana", "messenger": "com.facebook.orca", "telegram": "org.telegram.messenger",
    "photos": "com.google.android.apps.photos", "galerie": "com.miui.gallery", "appareil photo": "com.android.camera",
    "camera": "com.android.camera", "parametres": "com.android.settings", "reglages": "com.android.settings",
    "messages": "com.google.android.apps.messaging", "telephone": "com.google.android.dialer",
    "contacts": "com.google.android.contacts", "horloge": "com.android.deskclock", "calculatrice": "com.miui.calculator",
    "play store": "com.android.vending", "tailscale": "com.tailscale.ipn", "netflix": "com.netflix.mediaclient",
    "calendrier": "com.google.android.calendar", "drive": "com.google.android.apps.docs", "claude": "com.anthropic.claude",
}
KEYS = {"accueil": 3, "home": 3, "retour": 4, "back": 4, "recents": 187, "entree": 66, "enter": 66,
        "volume+": 24, "volume-": 25, "muet": 164, "power": 26, "veille": 26, "play": 85, "suivant": 87,
        "precedent": 88, "supprimer": 67}


def _plain(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def adb_path():
    exe = PT / ("adb.exe" if os.name == "nt" else "adb")
    if exe.exists():
        return str(exe)
    if shutil.which("adb"):
        return shutil.which("adb")
    import httpx
    data = httpx.get(ADB_URL, timeout=300, follow_redirects=True).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(PT.parent)
    return str(exe)


def adb(*args, timeout=40):
    r = subprocess.run([adb_path(), *args], capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    return (r.stdout + r.stderr).strip()


SAVED = BASE / "data" / "phone.json"


def _devices():
    out = []
    for line in adb("devices").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out


def device():
    d = _devices()
    if d:
        return next((x for x in d if ":" in x), d[0])   # Wi-Fi en priorité
    try:                                                 # reconnexion à la dernière adresse connue
        import json
        host = json.loads(SAVED.read_text())["host"]
        adb("connect", host, timeout=8)
        d = _devices()
        if d:
            return d[0]
    except Exception:
        pass
    return None


def _save(host):
    import json
    SAVED.parent.mkdir(exist_ok=True)
    SAVED.write_text(json.dumps({"host": host}))


def usb_to_wifi():
    """Téléphone branché en USB → passe ADB en Wi-Fi (port 5555), puis on peut débrancher."""
    usb = [d for d in _devices() if ":" not in d]
    if not usb:
        raw = adb("devices")
        if "unauthorized" in raw:
            return "Le téléphone refuse : déverrouille-le et accepte « Autoriser le débogage USB » (coche Toujours autoriser), puis réessaie."
        return ("Windows ne voit pas le téléphone en mode débogage.\n"
                "1. Sur le téléphone, tire la barre de notifications → « Recharge via USB » → choisis « Transfert de fichiers ».\n"
                "2. Options développeur → Révoquer les autorisations du débogage USB, puis débranche/rebranche.\n"
                "3. Si ça ne suffit pas, il manque le pilote USB Android sur le PC.\n\n" + raw)
    s = usb[0]
    ip = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", adb("-s", s, "shell", "ip -f inet addr show wlan0"))
    if not ip:
        return "Le téléphone n'est pas sur le Wi-Fi."
    adb("-s", s, "tcpip", "5555")
    import time; time.sleep(3)
    host = f"{ip.group(1)}:5555"
    out = adb("connect", host, timeout=15)
    if "connected" in out:
        _save(host)
        return f"Liaison Wi-Fi établie ({host}). Tu peux débrancher le câble."
    return out


def sh(cmd, timeout=40):
    d = device()
    if not d:
        raise RuntimeError("Téléphone non connecté. Ouvre le panneau 📱 de Jarvis pour l'associer.")
    return adb("-s", d, "shell", cmd, timeout=timeout)


# ---------- association ----------
def pair(host_port, code):
    return adb("pair", host_port.strip(), code.strip(), timeout=30)


def connect(host_port):
    out = adb("connect", host_port.strip(), timeout=20)
    if "connected" in out:
        _save(host_port.strip())
    return out


def status():
    try:
        d = device()
    except Exception as e:
        return {"connected": False, "error": str(e)[:150]}
    if not d:
        return {"connected": False}
    model = sh("getprop ro.product.model")
    bat = re.search(r"level: (\d+)", sh("dumpsys battery"))
    return {"connected": True, "device": d, "model": model, "battery": int(bat.group(1)) if bat else None}


# ---------- outils pour Jarvis ----------
def phone_status():
    return str(status())


def phone_open(app: str):
    key = _plain(app)
    pkg = APPS.get(key)
    if not pkg:
        pkgs = [l.replace("package:", "") for l in sh("pm list packages -3").splitlines()] + \
               [l.replace("package:", "") for l in sh("pm list packages -s").splitlines()]
        pkg = next((p for p in pkgs if key.replace(" ", "") in p.lower()), None)
    if not pkg:
        return f"Application « {app} » introuvable sur le téléphone."
    sh(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
    return f"Ouvert sur le téléphone : {pkg}"


def _screen_nodes():
    sh("uiautomator dump /sdcard/jarvis_ui.xml", timeout=30)
    xml = sh("cat /sdcard/jarvis_ui.xml")
    xml = xml[xml.find("<?xml"):] if "<?xml" in xml else xml
    nodes = []
    for n in ET.fromstring(xml).iter("node"):
        label = n.get("text") or n.get("content-desc") or ""
        m = re.findall(r"\d+", n.get("bounds", ""))
        if not label.strip() or len(m) != 4:
            continue
        x1, y1, x2, y2 = map(int, m)
        nodes.append({"label": label.strip()[:80], "x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
                      "click": n.get("clickable") == "true"})
    return nodes


def phone_screen():
    """Ce qui est affiché à l'écran du téléphone : textes et boutons avec leurs coordonnées."""
    nodes = _screen_nodes()
    if not nodes:
        return "Écran vide ou verrouillé."
    return "\n".join(f"{'[bouton] ' if n['click'] else ''}{n['label']} @({n['x']},{n['y']})" for n in nodes[:80])


def phone_tap(text: str = "", x: int = -1, y: int = -1):
    """Touche un élément par son texte, ou des coordonnées."""
    if text:
        want = _plain(text)
        nodes = _screen_nodes()
        best = next((n for n in nodes if _plain(n["label"]) == want), None) or \
               next((n for n in nodes if want in _plain(n["label"])), None)
        if not best:
            return f"« {text} » n'est pas à l'écran."
        x, y = best["x"], best["y"]
    sh(f"input tap {x} {y}")
    return f"Touché ({x},{y})"


def phone_type(text: str):
    """Tape du texte dans le champ actif (accents retirés : limite d'Android)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"([\\\"'`$&|;<>()*?!#~])", r"\\\1", t).replace(" ", "%s")
    sh(f"input text {t}")
    return "Texte tapé sur le téléphone."


def phone_key(key: str):
    code = KEYS.get(_plain(key))
    if code is None:
        return f"Touche inconnue. Choix : {', '.join(KEYS)}"
    sh(f"input keyevent {code}")
    return f"Touche {key}"


def phone_swipe(direction: str):
    d = _plain(direction)
    moves = {"haut": "540 1600 540 500", "bas": "540 500 540 1600", "gauche": "900 1000 150 1000",
             "droite": "150 1000 900 1000"}
    sh(f"input swipe {moves.get(d, moves['haut'])} 250")
    return f"Glissé vers le {d}"


def phone_url(url: str):
    sh(f"am start -a android.intent.action.VIEW -d '{url}'")
    return f"Ouvert sur le téléphone : {url}"


def phone_dial(number: str):
    sh(f"am start -a android.intent.action.DIAL -d tel:{re.sub(r'[^0-9+]', '', number)}")
    return "Numéro composé sur le téléphone (appuie sur Appeler)."


def phone_sms(number: str, text: str):
    body = text.replace("'", "’")
    sh(f"am start -a android.intent.action.SENDTO -d sms:{re.sub(r'[^0-9+]', '', number)} --es sms_body '{body}'")
    return "SMS prêt sur le téléphone (appuie sur Envoyer)."


def phone_notifications():
    out = sh("dumpsys notification --noredact", timeout=40)
    items = re.findall(r"android\.title=String \((.*?)\).*?android\.text=String \((.*?)\)", out, re.S)
    seen, lines = set(), []
    for t, x in items:
        k = (t, x)
        if k not in seen:
            seen.add(k)
            lines.append(f"{t} : {x}"[:160])
    return "\n".join(lines[:25]) or "Aucune notification."


def phone_shell(command: str):
    return sh(command)[:6000]


S = {"type": "string"}
I = {"type": "integer"}
def phone_notify(text: str, title: str = "JARVIS"):
    """Affiche une notification sur le téléphone (Android 10+, via adb)."""
    import shlex, re as _re
    if not device():
        return "Téléphone non connecté. Ouvre le panneau 📱 de Jarvis pour l'associer."
    clean = lambda t: _re.sub(r"[\r\n]+", " ", str(t))[:900]
    out = sh(f"cmd notification post -S bigtext -t {shlex.quote(clean(title))} jarvis {shlex.quote(clean(text))}", timeout=15)
    return "Notification envoyée sur le téléphone." if "error" not in out.lower() and "exception" not in out.lower() else "Échec : " + out[:200]


def notify_async(text, title="JARVIS"):
    """Notification sans bloquer ni lever d'erreur (téléphone absent = rien)."""
    import threading
    def run():
        try:
            import wake, time as _t
            if _t.time() - wake.NATIVE_POLL[0] < 180:   # l'appli Jarvis les affiche déjà
                return
            if _devices() or SAVED.exists():
                phone_notify(text, title)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _p(props, req=None):
    return {"type": "object", "properties": props, "required": req if req is not None else list(props)}

SPECS = [
    ("phone_status", "État du téléphone (connecté, modèle, batterie).", _p({}, [])),
    ("phone_open", "Ouvre une appli sur le téléphone (ex: whatsapp, youtube, spotify).", _p({"app": S})),
    ("phone_screen", "Lit l'écran du téléphone : textes et boutons avec coordonnées.", _p({}, [])),
    ("phone_tap", "Touche un élément du téléphone par son texte (ou x,y).", _p({"text": S, "x": I, "y": I}, [])),
    ("phone_type", "Tape du texte sur le téléphone.", _p({"text": S})),
    ("phone_key", "Touche système du téléphone : accueil, retour, recents, entree, volume+, volume-, veille, play.", _p({"key": S})),
    ("phone_swipe", "Fait glisser l'écran : haut, bas, gauche, droite.", _p({"direction": S})),
    ("phone_url", "Ouvre un lien sur le téléphone.", _p({"url": S})),
    ("phone_dial", "Compose un numéro sur le téléphone.", _p({"number": S})),
    ("phone_sms", "Prépare un SMS sur le téléphone.", _p({"number": S, "text": S})),
    ("phone_notifications", "Lit les notifications du téléphone.", _p({}, [])),
    ("phone_notify", "Affiche une notification sur le téléphone de l'utilisateur.", _p({"text": S, "title": S}, ["text"])),
    ("phone_shell", "Commande shell Android (adb shell).", _p({"command": S})),
]
FUNCS = {n: globals()[n] for n, _, _ in SPECS}

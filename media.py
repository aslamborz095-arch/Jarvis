"""Musique : contrôle Spotify (ou tout lecteur) sur le PC et le téléphone, sans compte développeur."""
import os, subprocess, urllib.parse

PC_KEYS = {"play": "playpause", "pause": "playpause", "lecture": "playpause", "suivant": "nexttrack",
           "precedent": "prevtrack", "volume+": "volumeup", "volume-": "volumedown", "muet": "volumemute"}
PHONE_KEYS = {"play": 85, "pause": 85, "lecture": 85, "suivant": 87, "precedent": 88,
              "volume+": 24, "volume-": 25, "muet": 164}


def media_control(action: str, device: str = "pc"):
    """Lecture/pause, suivant, précédent, volume sur le PC ou le téléphone."""
    a = action.lower().replace("é", "e").replace("è", "e").strip()
    if device.lower().startswith(("tel", "phone", "mobile")):
        import phone
        if a not in PHONE_KEYS:
            return f"Actions : {', '.join(PHONE_KEYS)}"
        phone.sh(f"input keyevent {PHONE_KEYS[a]}")
        return f"Téléphone : {action}"
    if a not in PC_KEYS:
        return f"Actions : {', '.join(PC_KEYS)}"
    import pyautogui
    pyautogui.press(PC_KEYS[a], presses=5 if a.startswith("volume") else 1)
    return f"PC : {action}"


def music_search(query: str, device: str = "pc"):
    """Ouvre Spotify sur la recherche demandée (titre, artiste, playlist)."""
    uri = "spotify:search:" + urllib.parse.quote(query)
    if device.lower().startswith(("tel", "phone", "mobile")):
        import phone
        phone.sh(f"am start -a android.intent.action.VIEW -d '{uri}'")
        return f"Spotify ouvert sur le téléphone : {query}. Touche le résultat pour lancer."
    if os.name == "nt":
        os.startfile(uri)
    return f"Spotify ouvert sur le PC : {query}."


S = {"type": "string"}
SPECS = [
    ("media_control", "Musique : play, pause, suivant, precedent, volume+, volume-, muet. device = pc ou telephone.",
     {"type": "object", "properties": {"action": S, "device": S}, "required": ["action"]}),
    ("music_search", "Ouvre Spotify sur une recherche (titre/artiste/playlist). device = pc ou telephone.",
     {"type": "object", "properties": {"query": S, "device": S}, "required": ["query"]}),
]
FUNCS = {"media_control": media_control, "music_search": music_search}

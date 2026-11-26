"""Voix de Jarvis : voix neuronale masculine (edge-tts, en ligne), secours voix Windows hors ligne."""
import os, hashlib, asyncio, pathlib, subprocess

BASE = pathlib.Path(__file__).parent
CACHE = BASE / "data" / "tts"
VOICES = {   # voix au choix dans ⚙ ; « 11: » = ElevenLabs (clé requise), les autres sont gratuites (Microsoft)
    "11:IKne3meq5aSn9XLyUdCD": "★ Charlie — jeune, charismatique, énergique (ElevenLabs)",
    "11:cnq6HZP9Mrjsf97pVK6b": "★ Grant — britannique grave, chaud, résonant (ElevenLabs)",
    "11:wNrcUqZN35sbTl2vAQU2": "★ Callum — britannique suave, velouté (ElevenLabs)",
    "11:DlSZgkElKXmDKq713bQ6": "★ Ben — britannique profond, intense (ElevenLabs)",
    "11:i6icHCFicH3kzHTat04x": "★ Richard — britannique majestueux (ElevenLabs)",
    "en-GB-OllieMultilingualNeural": "Ollie — britannique jeune et vif, parle français (gratuit, par défaut)",
    "en-GB-RyanNeural": "Ryan — britannique (anglais seulement)",
    "en-US-AndrewMultilingualNeural": "Andrew — anglais, parle français",
    "fr-FR-RemyMultilingualNeural": "Rémy — français posé",
    "fr-FR-HenriNeural": "Henri — français",
}
VOICE_FILE = BASE / "data" / "voice.txt"
SET_FILE = BASE / "data" / "voice_settings.json"


def settings():
    import json
    d = {"pitch": -2, "rate": 14, "eleven_key": "", "v": 2}
    try:
        old = json.loads(SET_FILE.read_text())
        if old.get("v") != 2:                      # anciens réglages lents/graves : on repart sur la voix dynamique
            old = {"eleven_key": old.get("eleven_key", "")}
        d.update(old)
    except Exception:
        pass
    return d


def save_settings(**kw):
    import json
    d = settings(); d.update({k: v for k, v in kw.items() if v is not None})
    SET_FILE.parent.mkdir(exist_ok=True); SET_FILE.write_text(json.dumps(d))


def _rp():
    s = settings()
    return f"{int(s['rate']):+d}%", f"{int(s['pitch']):+d}Hz"


def current():
    try:
        v = VOICE_FILE.read_text().strip()
    except Exception:
        v = os.getenv("JARVIS_VOICE", "")
    if v.startswith("11:") and not settings().get("eleven_key"):
        return "en-GB-OllieMultilingualNeural"      # pas de clé ElevenLabs : voix gratuite directement (plus rapide)
    return v or "en-GB-OllieMultilingualNeural"


def set_voice(v):
    VOICE_FILE.parent.mkdir(exist_ok=True)
    VOICE_FILE.write_text(v)


def tts(text, voice=None):
    """MP3 (en cache) avec la voix choisie ; si elle échoue, voix de secours. None si hors ligne."""
    for v in dict.fromkeys([voice or current(), "en-GB-OllieMultilingualNeural", "en-US-AndrewMultilingualNeural", "fr-FR-HenriNeural"]):
        f = _eleven(text, v[3:]) if v.startswith("11:") else _tts(text, v)
        if f:
            return f
    return None


_eleven_off = [0]


def _eleven(text, vid):
    """Voix premium ElevenLabs ; si quota épuisé / pas de clé → None (voix gratuite de secours)."""
    import time, httpx
    key = settings().get("eleven_key")
    text = (text or "").strip()[:1500]
    if not key or not text or time.time() < _eleven_off[0]:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(f"11{vid}{text}".encode()).hexdigest() + ".mp3")
    if f.exists() and f.stat().st_size > 0:
        return f
    try:
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}", params={"output_format": "mp3_44100_64"},
                       headers={"xi-api-key": key}, timeout=60,
                       json={"text": text, "model_id": "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}})
        if r.status_code != 200:
            _eleven_off[0] = time.time() + (3600 if r.status_code in (401, 402, 429) else 300)
            return None
        f.write_bytes(r.content)
        return f
    except Exception:
        return None


def _tts(text, VOICE):
    RATE, PITCH = _rp()
    text = (text or "").strip()[:1500]
    if not text:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(f"{VOICE}{RATE}{PITCH}{text}".encode()).hexdigest() + ".mp3")
    if f.exists() and f.stat().st_size > 0:
        return f
    try:
        import edge_tts
        async def run():
            await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(f))
        asyncio.run(run())
        return f if f.exists() and f.stat().st_size > 0 else None
    except Exception:
        f.unlink(missing_ok=True)
        return None


PS_PLAY = r"""
$p = New-Object -ComObject WMPlayer.OCX
$p.settings.volume = 100
$p.URL = $env:JARVIS_MP3
$p.controls.play()
Start-Sleep -Milliseconds 400
while ($p.playState -eq 3 -or $p.playState -eq 6 -or $p.playState -eq 9) { Start-Sleep -Milliseconds 150 }
"""

PS_SAY = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } |
     Sort-Object { if ($_.VoiceInfo.Gender -eq 'Male') { 0 } else { 1 } } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Speak($env:JARVIS_SAY)
"""


def speak_local(text):
    """Parle sur les haut-parleurs du PC (mot d'éveil)."""
    if not text or os.name != "nt":
        return
    f = tts(text)
    if f:
        env, script = {**os.environ, "JARVIS_MP3": str(f)}, PS_PLAY
    else:
        env, script = {**os.environ, "JARVIS_SAY": text[:1500]}, PS_SAY
    global _PLAY
    _PLAY = subprocess.Popen(["powershell", "-NoProfile", "-Command", script], env=env, creationflags=0x08000000)
    try:
        _PLAY.wait(timeout=180)
    except Exception:
        _PLAY.kill()


_PLAY = None


def stop_local():
    """Coupe la voix en cours sur le PC (geste poing)."""
    if _PLAY and _PLAY.poll() is None:
        _PLAY.kill()

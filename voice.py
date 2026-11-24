"""Voix de Jarvis : voix neuronale masculine (edge-tts, en ligne), secours voix Windows hors ligne."""
import os, hashlib, asyncio, pathlib, subprocess

BASE = pathlib.Path(__file__).parent
CACHE = BASE / "data" / "tts"
VOICES = {   # voix au choix dans ⚙ ; les « Multilingual » anglaises parlent français avec l'accent britannique/anglais
    "en-GB-OllieMultilingualNeural": "Ollie — britannique, parle français (style Jarvis)",
    "en-GB-RyanNeural": "Ryan — britannique (anglais seulement)",
    "en-US-AndrewMultilingualNeural": "Andrew — anglais, parle français",
    "fr-FR-RemyMultilingualNeural": "Rémy — français posé",
    "fr-FR-HenriNeural": "Henri — français",
}
VOICE_FILE = BASE / "data" / "voice.txt"
RATE = os.getenv("JARVIS_VOICE_RATE", "+4%")
PITCH = os.getenv("JARVIS_VOICE_PITCH", "-4Hz")


def current():
    try:
        return VOICE_FILE.read_text().strip() or "en-GB-OllieMultilingualNeural"
    except Exception:
        return os.getenv("JARVIS_VOICE", "en-GB-OllieMultilingualNeural")


def set_voice(v):
    VOICE_FILE.parent.mkdir(exist_ok=True)
    VOICE_FILE.write_text(v)


def tts(text, voice=None):
    """MP3 (en cache) avec la voix choisie ; si elle échoue, voix de secours. None si hors ligne."""
    for v in dict.fromkeys([voice or current(), "en-US-AndrewMultilingualNeural", "fr-FR-HenriNeural"]):
        f = _tts(text, v)
        if f:
            return f
    return None


def _tts(text, VOICE):
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
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, creationflags=0x08000000, timeout=180)

"""Voix de Jarvis : voix neuronale masculine (edge-tts, en ligne), secours voix Windows hors ligne."""
import os, hashlib, asyncio, pathlib, subprocess

BASE = pathlib.Path(__file__).parent
CACHE = BASE / "data" / "tts"
VOICE = os.getenv("JARVIS_VOICE", "fr-FR-HenriNeural")
RATE = os.getenv("JARVIS_VOICE_RATE", "+6%")
PITCH = os.getenv("JARVIS_VOICE_PITCH", "-6Hz")


def tts(text):
    """Renvoie le chemin d'un MP3 (mis en cache), ou None si la voix en ligne est indisponible."""
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

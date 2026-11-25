"""Reconnaissance vocale : Whisper large-v3-turbo en ligne (Groq, gratuit, qualité de référence),
secours local faster-whisper (hors ligne)."""
import os, threading

_model = None
_lock = threading.Lock()
PROMPT = "Jarvis, assistant personnel. Ouvre, lance, mets, envoie, cherche, rappelle-moi, agenda, mail, téléphone, Spotify, YouTube, WhatsApp."


def _groq(path):
    import httpx, providers
    g = next((p for p in providers.available() if p["id"] == "groq"), None)
    key = g["key"] if g else os.getenv("GROQ_API_KEY")
    if not key:
        return None
    for model in ("whisper-large-v3-turbo", "whisper-large-v3"):
        with open(path, "rb") as f:
            r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions", timeout=60,
                           headers={"Authorization": f"Bearer {key}"},
                           files={"file": (os.path.basename(path), f)},
                           data={"model": model, "language": "fr", "prompt": PROMPT, "temperature": "0"})
        if r.status_code == 200:
            return r.json().get("text", "").strip()
        if r.status_code not in (400, 404):
            return None
    return None


def _local(path):
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="auto", compute_type="int8")
        from faster_whisper import decode_audio
        import numpy as np
        audio = decode_audio(path, sampling_rate=16000)
        peak = float(np.abs(audio).max()) if audio.size else 0
        if peak > 1e-4:
            audio = audio * min(0.9 / peak, 30.0)      # micro faible : on remonte le volume
        segs, _ = _model.transcribe(audio, language="fr", beam_size=5, initial_prompt=PROMPT, vad_filter=True,
                                    vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 400})
        return " ".join(s.text for s in segs).strip()


def transcribe(path):
    try:
        t = _groq(path)
        if t:
            return t
    except Exception:
        pass
    return _local(path)


_tiny = None


def quick(pcm16):
    """Transcription éclair (modèle tiny, local) d'un court extrait int16 16 kHz — pour repérer « Jarvis »."""
    global _tiny
    import numpy as np
    with _lock:
        if _tiny is None:
            from faster_whisper import WhisperModel
            _tiny = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=2)
        a = pcm16.astype(np.float32) / 32768.0
        pk = float(np.abs(a).max()) or 1.0
        a = a * min(0.9 / pk, 40.0)
        segs, _ = _tiny.transcribe(a, language="fr", beam_size=1, initial_prompt="Jarvis, Hey Jarvis.",
                                   condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text for s in segs).strip()

"""Reconnaissance vocale locale (Whisper), partagée par l'interface et le mot d'éveil."""
import os, threading

_model = None
_lock = threading.Lock()


def transcribe(path):
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="auto", compute_type="int8")
        segs, _ = _model.transcribe(path, language="fr", vad_filter=True)
        return " ".join(s.text for s in segs).strip()

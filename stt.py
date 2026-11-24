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
        from faster_whisper import decode_audio
        import numpy as np
        audio = decode_audio(path, sampling_rate=16000)
        peak = float(np.abs(audio).max()) if audio.size else 0
        if peak > 1e-4:
            audio = audio * min(0.9 / peak, 30.0)      # micro faible : on remonte le volume avant transcription
        segs, _ = _model.transcribe(audio, language="fr", vad_filter=True,
                                    vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 400})
        return " ".join(s.text for s in segs).strip()

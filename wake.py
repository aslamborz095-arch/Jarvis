"""Mot d'éveil « Hey Jarvis » : écoute permanente du micro du PC, 100 % local.

Dis « Hey Jarvis » → bip → donne ton ordre → Jarvis répond à voix haute sur le PC.
"""
import os, time, wave, queue, tempfile, threading, subprocess, collections

import brain, stt

THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.35"))
DEVICE = os.getenv("WAKE_DEVICE") or None   # nom ou numéro du micro (sinon micro par défaut)
STATE = {"enabled": False, "busy": False, "error": None, "level": 0.0, "score": 0.0, "device": None}
EVENTS = collections.deque(maxlen=60)
_counter = [0]
RATE, CHUNK = 16000, 1280  # 80 ms


def push(kind, **data):
    _counter[0] += 1
    EVENTS.append({"id": _counter[0], "type": kind, **data})


def events_after(i):
    return [e for e in EVENTS if e["id"] > i]


def beep(freq=880, ms=120):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


def speak(text):
    import voice
    voice.speak_local(text)


def _rms(a):
    import numpy as np
    return float(np.sqrt(np.mean(a.astype(np.float32) ** 2)))


def _record(q, noise):
    """Enregistre la commande jusqu'au silence (max 12 s)."""
    thr = max(90.0, noise * 1.8)
    frames, started, silent = [], False, 0
    t0 = time.time()
    while time.time() - t0 < 12:
        c = q.get()
        frames.append(c)
        loud = _rms(c) > thr
        if loud:
            started, silent = True, 0
        elif started:
            silent += 1
            if silent > 14:          # ~1,1 s de silence
                break
        elif time.time() - t0 > 4:   # rien dit en 4 s
            return None
    return frames if started else None


def _handle(q, noise):
    import numpy as np
    STATE["busy"] = True
    try:
        beep()
        push("state", state="listening")
        while not q.empty():
            q.get_nowait()
        frames = _record(q, noise)
        if not frames:
            push("state", state="idle")
            return
        push("state", state="thinking")
        path = os.path.join(tempfile.gettempdir(), "jarvis_cmd.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(np.concatenate(frames).tobytes())
        text = stt.transcribe(path)
        if not text:
            push("state", state="idle")
            speak("Je n'ai pas compris, monsieur.")
            return
        push("user", text=text)
        res = brain.ask(text)
        if res.get("confirm"):
            push("confirm", res=res)
            speak("J'ai besoin de votre autorisation à l'écran.")
        else:
            push("reply", res=res)
            push("state", state="speaking")
            speak(res.get("reply", ""))
        push("state", state="idle")
    finally:
        while not q.empty():      # oublie ce que le micro a entendu pendant la réponse
            q.get_nowait()
        STATE["busy"] = False


def _run():
    import numpy as np, sounddevice as sd, openwakeword
    from openwakeword.model import Model
    path = next(p for p in openwakeword.get_pretrained_model_paths() if "jarvis" in p)
    model = Model(wakeword_model_paths=[path])
    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata[:, 0].copy())

    dev = int(DEVICE) if DEVICE and DEVICE.isdigit() else DEVICE
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb, device=dev):
        STATE["enabled"], STATE["error"] = True, None
        try:
            STATE["device"] = sd.query_devices(dev, "input")["name"]
        except Exception:
            pass
        noise, peaks = 300.0, []
        while True:
            c = q.get()
            r = _rms(c)
            peaks = (peaks + [r])[-150:]                     # ~12 s d'historique
            ref = sorted(peaks)[int(len(peaks) * 0.95)] if len(peaks) > 20 else 500
            gain = max(1.0, min(10.0, 2500.0 / max(ref, 50.0)))   # gain automatique : micro faible amplifié
            if gain > 1.05:
                import numpy as np
                c = np.clip(c.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
            noise = 0.98 * noise + 0.02 * r   # bruit ambiant moyen
            STATE["level"] = round(max(STATE["level"] * 0.9, r))
            score = max(model.predict(c).values())
            STATE["score"] = round(max(STATE["score"] * 0.95, float(score)), 2)
            if score >= THRESHOLD:
                _handle(q, noise)
                model.reset()


def start():
    def loop():
        while True:
            try:
                _run()
            except Exception as e:      # micro absent, dépendance manquante…
                STATE["enabled"], STATE["error"] = False, str(e)[:200]
                time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()

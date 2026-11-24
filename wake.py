"""Mot d'éveil « Hey Jarvis » : écoute permanente du micro du PC, 100 % local.

Dis « Hey Jarvis » → bip → donne ton ordre → Jarvis répond à voix haute sur le PC.
"""
import os, time, wave, queue, tempfile, threading, subprocess, collections

import brain, stt

THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))
STATE = {"enabled": False, "busy": False, "error": None}
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


PS_SAY = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } |
     Sort-Object { if ($_.VoiceInfo.Gender -eq 'Male') { 0 } else { 1 } } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Speak($env:JARVIS_SAY)
"""


def speak(text):
    if not text or os.name != "nt":
        return
    env = {**os.environ, "JARVIS_SAY": text[:1500]}
    subprocess.run(["powershell", "-NoProfile", "-Command", PS_SAY], env=env,
                   creationflags=0x08000000, timeout=120)


def _rms(a):
    import numpy as np
    return float(np.sqrt(np.mean(a.astype(np.float32) ** 2)))


def _record(q, noise):
    """Enregistre la commande jusqu'au silence (max 12 s)."""
    thr = max(400.0, noise * 3)
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

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb):
        STATE["enabled"], STATE["error"] = True, None
        noise = 300.0
        while True:
            c = q.get()
            noise = 0.98 * noise + 0.02 * _rms(c)   # bruit ambiant moyen
            if max(model.predict(c).values()) >= THRESHOLD:
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

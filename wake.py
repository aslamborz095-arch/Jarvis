"""Mot d'éveil « Hey Jarvis » : écoute permanente du micro du PC, 100 % local.

Dis « Hey Jarvis » → bip → donne ton ordre → Jarvis répond à voix haute sur le PC.
"""
import os, re, time, wave, queue, tempfile, threading, subprocess, collections

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


def _handle(q, noise, text=None):
    import numpy as np
    STATE["busy"] = True
    try:
        beep()
        if text:
            push("state", state="thinking")
        else:
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
                a = np.concatenate(frames).astype(np.float32)
                pk = float(np.abs(a).max()) or 1.0
                a = np.clip(a * min(29000.0 / pk, 30.0), -32768, 32767).astype(np.int16)   # volume normalisé
                w.writeframes(a.tobytes())
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


SKIP = re.compile(r"mapper|mixage|stereo|stéréo|ligne|line|pilote de capture|primary", re.I)
NAME = re.compile(r"\b(hey |h[eé] |eh )?(dj?|ch|g|j)ar ?vi[sc]e?\b|jarvis", re.I)


def _candidates(sd):
    """Micros réels (API MME, sans doublons), le micro par défaut en premier, Bluetooth en dernier."""
    mme = next((i for i, h in enumerate(sd.query_hostapis()) if "MME" in h["name"]), 0)
    try:
        default = sd.default.device[0]
    except Exception:
        default = -1
    out = [i for i, d in enumerate(sd.query_devices())
           if d["max_input_channels"] > 0 and d["hostapi"] == mme and not SKIP.search(d["name"])]
    bt = lambda i: "bthhfenum" in sd.query_devices(i)["name"] or "Hands-Free" in sd.query_devices(i)["name"]
    return sorted([i for i in out if i == default or not bt(i)], key=lambda i: i != default) + [i for i in out if i != default and bt(i)]


def pick_device():
    """Teste chaque micro 0,8 s et garde celui qui capte vraiment quelque chose."""
    import numpy as np, sounddevice as sd
    if DEVICE:
        return int(DEVICE) if DEVICE.isdigit() else DEVICE
    best, best_r = None, 0.0
    for i in _candidates(sd)[:6]:
        box = []

        def probe():
            try:
                with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", device=i) as s:
                    a, _ = s.read(int(RATE * 0.8))
                box.append(_rms(a[int(RATE * 0.1):, 0]))
            except Exception:
                pass
        th = threading.Thread(target=probe, daemon=True); th.start(); th.join(3)   # un micro Bluetooth absent peut bloquer
        if not box:
            continue
        r = box[0]
        STATE.setdefault("probe", {})[sd.query_devices(i)["name"]] = round(r)
        if r > best_r * 1.5:          # un micro vivant capte au moins le souffle de la pièce
            best, best_r = i, r
        if best_r > 60 and "bthhfenum" not in sd.query_devices(i)["name"]:
            break
    return best


def _run():
    import numpy as np, sounddevice as sd, openwakeword
    from openwakeword.model import Model
    path = next(p for p in openwakeword.get_pretrained_model_paths() if "jarvis" in p)
    model = Model(wakeword_model_paths=[path])
    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata[:, 0].copy())

    dev = pick_device()
    threading.Thread(target=lambda: stt.quick(np.zeros(1600, dtype=np.int16)), daemon=True).start()   # précharge Whisper
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb, device=dev):
        STATE["enabled"], STATE["error"] = True, None
        try:
            STATE["device"] = sd.query_devices(dev, "input")["name"]
        except Exception:
            pass
        noise, peaks, burst, quiet, t0, last_check = 300.0, [], [], 0, time.time(), 0.0
        while True:
            c = q.get()
            r = _rms(c)
            peaks = (peaks + [r])[-750:]                     # ~60 s d'historique
            ref = sorted(peaks)[int(len(peaks) * 0.95)] if len(peaks) > 20 else 500
            STATE["mic_dead"] = len(peaks) >= 750 and ref < 12
            if STATE["mic_dead"] and time.time() - t0 > 120:
                return                                       # micro muet : on en cherche un autre
            gain = max(1.0, min(40.0, 2500.0 / max(ref, 20.0)))   # gain automatique : micro faible amplifié
            if gain > 1.05:
                c = np.clip(c.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
            noise = 0.98 * noise + 0.02 * r   # bruit ambiant moyen
            STATE["level"] = round(max(STATE["level"] * 0.9, r))
            score = max(model.predict(c).values())
            STATE["score"] = round(max(STATE["score"] * 0.95, float(score)), 2)
            if score >= THRESHOLD:
                _handle(q, noise)
                model.reset(); burst, quiet = [], 0
                continue
            # 2e détecteur : un bout de phrase court → Whisper local vérifie s'il contient « Jarvis »
            if r * gain > max(300.0, noise * gain * 2.2):
                burst.append(c); quiet = 0
            elif burst:
                burst.append(c); quiet += 1
                if quiet >= 5:                                # 0,4 s de silence = fin de phrase
                    seg, burst, quiet = burst, [], 0
                    if 4 <= len(seg) <= 75 and time.time() - last_check > 1.0:
                        last_check = time.time()
                        text = stt.quick(np.concatenate(seg))
                        m = NAME.search(text or "")
                        if m:
                            STATE["heard"] = text
                            rest = text[m.end():].strip(" ,.!?").strip()
                            _handle(q, noise, rest if len(rest.split()) >= 2 else None)
                            model.reset()
            if len(burst) > 75:
                burst, quiet = [], 0


def start():
    def loop():
        while True:
            try:
                _run()
            except Exception as e:      # micro absent, dépendance manquante…
                STATE["enabled"], STATE["error"] = False, str(e)[:200]
                time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()

"""
JARVIS voice output — Piper offline TTS, British male voice.

Sentence-streamed playback: the first sentence starts speaking while the rest
is still being synthesised, so replies feel immediate. `level` exposes the RMS
of the chunk currently on the speakers — the HUD waveform reads it.
"""

import io
import os
import queue
import re
import threading
import wave

import numpy as np
import sounddevice as sd

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:…])\s+")


def _load_voice(voice_path: str):
    from piper import PiperVoice
    try:
        return PiperVoice.load(voice_path)
    except TypeError:
        return PiperVoice.load(voice_path, use_cuda=False)


def _synthesize_wav_bytes(voice, text: str) -> bytes:
    """Piper API drifted across versions — handle both shapes.

    Also survives a transient zero-chunk synthesis: wave.close() raises when
    no frames were ever written, so close() is guarded and one retry runs.
    """
    last_err = ""
    for _attempt in range(2):
        buf = io.BytesIO()
        wf = wave.open(buf, "wb")
        try:
            if hasattr(voice, "synthesize_wav"):
                try:
                    voice.synthesize_wav(text, wf)
                except TypeError:
                    voice.synthesize_wav(wf, text)
            else:
                voice.synthesize(text, wf)
        finally:
            try:
                wf.close()          # writes the trailer — may raise if empty
            except Exception as e:
                last_err = str(e)
        data = buf.getvalue()
        if len(data) > 44:          # RIFF header alone is 44 bytes
            return data
    raise RuntimeError(f"piper produced no audio ({last_err}) for: {text[:60]!r}")


def _split_sentences(text: str, max_chars: int = 220) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    out = []
    for p in parts:
        while len(p) > max_chars:  # hard-wrap giant blobs (lists, code paths)
            cut = p.rfind(" ", 0, max_chars)
            cut = cut if cut > 40 else max_chars
            out.append(p[:cut].rstrip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out or [text.strip()]


class Speaker:
    def __init__(self, voice_path: str):
        self.voice_path = voice_path
        self.level = 0.0                 # RMS of the block currently playing
        self.on_state = None             # callable("speaking"|"idle")
        self._voice = None
        self._q: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True, name="jarvis-tts")
        self._worker.start()

    # ------------------------------------------------------------- lifecycle
    def _ensure_voice(self):
        with self._lock:
            if self._voice is None:
                self._voice = _load_voice(self.voice_path)
            return self._voice

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    def say(self, text: str) -> None:
        """Queue text to be spoken (non-blocking)."""
        text = (text or "").strip()
        if not text:
            return
        for sentence in _split_sentences(text):
            self._q.put(sentence)
        self._idle.clear()

    def stop(self) -> None:
        """Barge-in: drop everything queued and halt playback."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._stop.set()
        self._idle.set()
        self.level = 0.0
        if self.on_state:
            try:
                self.on_state("idle")
            except Exception:
                pass

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        while True:
            sentence = self._q.get()
            if sentence is None:
                return
            if self._stop.is_set():
                continue
            try:
                voice = self._ensure_voice()
                wav = _synthesize_wav_bytes(voice, sentence)
                self._play_wav(wav)
            except Exception as e:
                print(f"[tts] playback error: {e}")
            finally:
                if self._q.empty():
                    self._idle.set()
                    self.level = 0.0
                    if self.on_state:
                        try:
                            self.on_state("idle")
                        except Exception:
                            pass

    def _play_wav(self, wav_bytes: bytes) -> None:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        audio = data.astype(np.float32) / 32768.0
        if ch > 1:
            audio = audio.reshape(-1, ch).mean(axis=1)

        if self.on_state:
            try:
                self.on_state("speaking")
            except Exception:
                pass
        self._stop.clear()
        chunk = max(1, int(sr * 0.04))          # 40 ms blocks: responsive barge-in
        with sd.OutputStream(samplerate=sr, channels=1, dtype="float32") as stream:
            for i in range(0, len(audio), chunk):
                if self._stop.is_set():
                    break
                block = audio[i:i + chunk]
                stream.write(block)
                self.level = float(np.sqrt(np.mean(block * block))) * 3.0  # boost for visuals
        self.level = 0.0


def default_voice_path(cfg: dict) -> str:
    """Resolve the configured Piper .onnx path, creating it if missing."""
    import urllib.request
    voice = cfg.get("tts_voice", "en_GB-northern_english_male-medium")
    voice_dir = os.path.join(os.path.dirname(__file__), cfg.get("piper_dir", "models/piper"))
    os.makedirs(voice_dir, exist_ok=True)
    path = os.path.join(voice_dir, voice + ".onnx")
    if os.path.isfile(path):
        return path
    # first-run download from the official rhasspy/piper-voices repo
    parts = voice.split("-")                     # en_GB-<name>-<quality>
    lang, name, quality = parts[0], parts[1], parts[2]
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang[:2]}/{lang}/{name}/{quality}"
    for suffix in (".onnx", ".onnx.json"):
        url = f"{base}/{voice}{suffix}?download=true"
        dest = os.path.join(voice_dir, voice + suffix)
        print(f"[tts] downloading {voice}{suffix} ...")
        urllib.request.urlretrieve(url, dest)
    return path

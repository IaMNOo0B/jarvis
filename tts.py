"""
JARVIS voice output — pluggable TTS backends.

Backends (``voice.tts_backend`` in config.yaml):

  piper       Offline Piper TTS (default). British male voice, no key needed,
              no network. This is the fallback everything else degrades to.
  fish        Fish Audio neural TTS — human, non-robotic voices, voice cloning
              and voice design at https://fish.audio. Needs ``FISH_API_KEY``
              (env) or ``fish_api_key`` in secrets.local.yaml, plus
              ``voice.fish_voice_id`` (the model ID from the voice URL).
  elevenlabs  ElevenLabs neural TTS — needs ``ELEVENLABS_API_KEY`` (env) or
              ``elevenlabs_api_key`` in secrets.local.yaml, plus
              ``voice.elevenlabs_voice_id``. Uses the multilingual model, so it
              handles Hindi/Hinglish mixed with English.

``Speaker`` keeps the same public interface (``say``/``stop``/``wait_idle``/
``busy``/``level``/``on_state``), so sentence-streamed playback, barge-in and
the HUD level meter work identically with every backend. ``create_speaker(cfg)``
picks the configured backend; if a neural backend fails (bad key, no network)
it falls back to offline Piper so JARVIS never goes mute.
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


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw s16le mono PCM in a WAV container (in memory)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _resolve_voice_key(cfg: dict, env_names: list[str], yaml_keys: list[str]) -> str:
    """API key: environment first, then secrets.local.yaml (same as brain)."""
    for var in env_names:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        import yaml
        secrets_path = os.path.join(os.path.dirname(__file__), "secrets.local.yaml")
        if os.path.isfile(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for k in yaml_keys:
                val = str(data.get(k) or "").strip()
                if val:
                    return val
    except Exception:
        pass
    # last resort: key pasted directly in config (not recommended)
    for k in yaml_keys:
        val = str(cfg.get(k) or "").strip()
        if val and len(val) > 16:
            return val
    return ""


# ------------------------------------------------------------------ backends
class TTSBackend:
    """Something that turns text into WAV bytes. Raise on failure."""

    name = "base"

    def synthesize(self, text: str) -> bytes:
        raise NotImplementedError


class PiperBackend(TTSBackend):
    """Offline Piper TTS — the default. No key, no network."""

    name = "piper"

    def __init__(self, voice_path: str):
        self.voice_path = voice_path
        self._voice = None
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> bytes:
        with self._lock:
            if self._voice is None:
                self._voice = _load_voice(self.voice_path)
            voice = self._voice
        return _synthesize_wav_bytes(voice, text)


class FishAudioBackend(TTSBackend):
    """Fish Audio neural TTS (https://fish.audio). Human voices, voice clone /
    voice design support. ``format=wav`` comes back ready to play."""

    name = "fish"
    _URL = "https://api.fish.audio/v1/tts"

    def __init__(self, api_key: str, voice_id: str = "", model: str = "s1"):
        if not api_key:
            raise RuntimeError("fish backend needs FISH_API_KEY (env) or "
                               "fish_api_key in secrets.local.yaml")
        self.api_key = api_key
        self.voice_id = (voice_id or "").strip()
        self.model = model or "s1"

    def synthesize(self, text: str) -> bytes:
        import requests
        body = {"text": text, "format": "wav", "normalize": True,
                "latency": "balanced"}
        if self.voice_id:
            body["reference_id"] = self.voice_id
        try:
            resp = requests.post(
                self._URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json",
                         "model": self.model},
                json=body,
                timeout=30,
            )
        except Exception as e:
            raise RuntimeError(f"fish audio request failed: {e}")
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200 or "audio" not in ctype:
            detail = resp.text[:200]
            raise RuntimeError(f"fish audio error {resp.status_code}: {detail}")
        return resp.content


class ElevenLabsBackend(TTSBackend):
    """ElevenLabs neural TTS (https://elevenlabs.io). Multilingual model, so
    Hindi/Hinglish mixed with English comes out naturally."""

    name = "elevenlabs"
    _URL = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self, api_key: str, voice_id: str,
                 model_id: str = "eleven_multilingual_v2"):
        if not api_key:
            raise RuntimeError("elevenlabs backend needs ELEVENLABS_API_KEY (env) "
                               "or elevenlabs_api_key in secrets.local.yaml")
        if not (voice_id or "").strip():
            raise RuntimeError("elevenlabs backend needs voice.elevenlabs_voice_id "
                               "in config.yaml")
        self.api_key = api_key
        self.voice_id = voice_id.strip()
        self.model_id = model_id or "eleven_multilingual_v2"

    def synthesize(self, text: str) -> bytes:
        import requests
        try:
            resp = requests.post(
                f"{self._URL}/{self.voice_id}",
                params={"output_format": "pcm_16000"},
                headers={"xi-api-key": self.api_key,
                         "Content-Type": "application/json"},
                json={"text": text, "model_id": self.model_id},
                timeout=30,
            )
        except Exception as e:
            raise RuntimeError(f"elevenlabs request failed: {e}")
        if resp.status_code != 200:
            raise RuntimeError(f"elevenlabs error {resp.status_code}: "
                               f"{resp.text[:200]}")
        return _pcm_to_wav_bytes(resp.content, 16000)


class FallbackBackend(TTSBackend):
    """Try the primary backend; on failure warn once and use Piper forever."""

    def __init__(self, primary: TTSBackend, fallback: TTSBackend):
        self.name = f"{primary.name}+fallback:{fallback.name}"
        self._primary = primary
        self._fallback = fallback
        self._failed = False
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> bytes:
        with self._lock:
            backend = self._fallback if self._failed else self._primary
        try:
            return backend.synthesize(text)
        except Exception as e:
            with self._lock:
                if not self._failed:
                    print(f"[tts] {self._primary.name} failed ({e}) — "
                          f"falling back to {self._fallback.name}")
                    self._failed = True
            return self._fallback.synthesize(text)


def create_speaker(cfg: dict) -> "Speaker":
    """Build a Speaker for the configured ``voice.tts_backend``.

    Backends: "piper" (default, offline), "fish", "elevenlabs".
    Neural backends automatically fall back to Piper on failure.
    """
    backend_name = str(cfg.get("tts_backend", "piper") or "piper").lower()
    piper = PiperBackend(default_voice_path(cfg))  # always available as fallback

    if backend_name == "fish":
        try:
            key = _resolve_voice_key(cfg, ["FISH_API_KEY"], ["fish_api_key"])
            neural = FishAudioBackend(key, cfg.get("fish_voice_id", ""),
                                      cfg.get("fish_model", "s1"))
        except RuntimeError as e:
            print(f"[tts] {e} — using piper")
            return Speaker(piper)
        return Speaker(FallbackBackend(neural, piper))
    if backend_name == "elevenlabs":
        try:
            key = _resolve_voice_key(cfg, ["ELEVENLABS_API_KEY"],
                                     ["elevenlabs_api_key"])
            neural = ElevenLabsBackend(key, cfg.get("elevenlabs_voice_id", ""),
                                       cfg.get("elevenlabs_model",
                                               "eleven_multilingual_v2"))
        except RuntimeError as e:
            print(f"[tts] {e} — using piper")
            return Speaker(piper)
        return Speaker(FallbackBackend(neural, piper))
    if backend_name != "piper":
        print(f"[tts] unknown tts_backend {backend_name!r} — using piper")
    return Speaker(piper)


# ------------------------------------------------------------------- speaker
class Speaker:
    def __init__(self, backend):
        # backend: TTSBackend, or a Piper .onnx path (backwards compatible).
        if isinstance(backend, str):
            backend = PiperBackend(backend)
        self.backend = backend
        self.level = 0.0                 # RMS of the block currently playing
        self.on_state = None             # callable("speaking"|"idle")
        self._q: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._worker = threading.Thread(target=self._run, daemon=True, name="jarvis-tts")
        self._worker.start()

    # ------------------------------------------------------------- lifecycle
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
                wav = self.backend.synthesize(sentence)
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

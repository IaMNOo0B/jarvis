"""
JARVIS wake words — openWakeWord models (ONNX), one per phrase.

Two wake words, two brains (Phase 4):
  "hey_jarvis"   -> local brain   (pretrained model, ships with openWakeWord)
  "hello_jarvis" -> cloud brain   (custom model — see note below)

Exposes `make_sink()` which the audio engine drives: it assembles the
100 ms mic frames into the 80 ms windows the models expect and fires
`on_hit(word, score)` when a score crosses the threshold (per-word
cooldown, so one "Jarvis" doesn't trigger twice).

A word whose model can't be loaded (e.g. "hello_jarvis" before you've
trained it) is skipped with a warning — the other words keep working.

Training "hello_jarvis": openWakeWord supports custom wake-word training
from your own voice samples (collect ~50 clips of the phrase + some
not-phrase audio, train per their docs). Drop the resulting .onnx/.tflite
into openWakeWord's model dir and restart — it activates automatically.
"""


class WakeListener:
    def __init__(self, wakewords=("hey_jarvis",), threshold: float = 0.5,
                 wakeword: str | None = None):
        # wakeword= is the old single-word kwarg, kept for compatibility.
        if wakeword:
            wakewords = (wakeword,)
        self.wakewords = tuple(w for w in (wakewords or ("hey_jarvis",)) if w)
        self.threshold = threshold
        self._models = None
        self.last_scores: dict = {}
        self.last_score = 0.0

    # -------------------------------------------------------------- compat
    @property
    def wakeword(self) -> str:
        """First configured word (old single-word API)."""
        return self.wakewords[0] if self.wakewords else "hey_jarvis"

    @property
    def words(self) -> list:
        """Words with successfully loaded models (empty until preload)."""
        return list((self._models or {}).keys())

    # ------------------------------------------------------------------ model
    def preload(self) -> None:
        self._ensure()

    def _load_one(self, word: str):
        from openwakeword.model import Model
        try:
            return Model(wakeword_models=[word], inference_framework="onnx")
        except Exception:
            # first run: fetch the pretrained model files, then retry
            import openwakeword
            openwakeword.utils.download_models([word])
            return Model(wakeword_models=[word], inference_framework="onnx")

    def _ensure(self):
        if self._models is not None:
            return self._models
        try:
            from openwakeword.model import Model  # noqa: F401
        except Exception as e:  # import/onnxruntime problem
            raise RuntimeError(f"openwakeword unavailable: {e}")
        models = {}
        for word in self.wakewords:
            try:
                models[word] = self._load_one(word)
            except Exception as e:
                # e.g. "hello_jarvis" has no pretrained model yet —
                # skip it, the other words keep working.
                print(f"[wake] wake word '{word}' unavailable, skipping ({e})")
        if not models:
            raise RuntimeError("openWakeWord: no wake-word models loaded")
        self._models = models
        return models

    def scores(self, frame16: bytes) -> dict:
        """Score one 80 ms int16 frame against every loaded wake word."""
        import numpy as np
        pcm = np.frombuffer(frame16, dtype=np.int16)
        if len(pcm) != 1280:                      # pad/trim defensively
            buf = np.zeros(1280, dtype=np.int16)
            n = min(1280, len(pcm))
            buf[:n] = pcm[:n]
            pcm = buf
        out = {}
        for word, model in self._ensure().items():
            try:
                out[word] = float(model.predict(pcm).get(word, 0.0))
            except Exception:
                out[word] = 0.0
        self.last_scores = out
        self.last_score = max(out.values()) if out else 0.0
        return out

    def score(self, frame16: bytes) -> float:
        """Old single-value API: best score across words."""
        return max(self.scores(frame16).values(), default=0.0)

    # ------------------------------------------------------------------- sink
    def make_sink(self, on_hit, threshold: float | None = None,
                  cooldown: float = 1.5):
        """Return a frame-sink for the audio engine.

        on_hit(word, score) fires once per cooldown window, per wake word.
        """
        thr = self.threshold if threshold is None else threshold
        buf = bytearray()
        hit_at: dict = {}
        import time as _time

        def sink(frame: bytes) -> None:
            nonlocal buf
            buf.extend(frame)
            if len(buf) < 1280 * 2:              # need >= 80 ms of samples
                return
            while len(buf) >= 1280 * 2:
                chunk = bytes(buf[:1280 * 2])
                del buf[:1280 * 2]
                s = self.scores(chunk)
                now = _time.monotonic()
                for word, val in s.items():
                    if val >= thr and (now - hit_at.get(word, -1e9)) >= cooldown:
                        hit_at[word] = now
                        try:
                            on_hit(word, val)
                        except Exception as e:
                            print(f"[wake] handler error: {e}")

        return sink

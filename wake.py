"""
JARVIS wake word — openWakeWord's pretrained "hey jarvis" model (ONNX).

Exposes `make_sink()` which the audio engine drives: it assembles the
100 ms mic frames into the 80 ms windows the model expects and fires a
callback when the score crosses the threshold (with a cooldown so one
"Jarvis" doesn't trigger twice).
"""


class WakeListener:
    def __init__(self, wakeword: str = "hey_jarvis", threshold: float = 0.5):
        self.wakeword = wakeword
        self.threshold = threshold
        self._model = None
        self.last_score = 0.0

    # ------------------------------------------------------------------ model
    def preload(self) -> None:
        self._ensure()

    def _ensure(self):
        if self._model is not None:
            return self._model
        try:
            from openwakeword.model import Model
        except Exception as e:  # import/onnxruntime problem
            raise RuntimeError(f"openwakeword unavailable: {e}")
        try:
            self._model = Model(wakeword_models=[self.wakeword],
                                inference_framework="onnx")
        except Exception:
            # first run: fetch the pretrained model files, then retry
            import openwakeword
            openwakeword.utils.download_models([self.wakeword])
            self._model = Model(wakeword_models=[self.wakeword],
                                inference_framework="onnx")
        return self._model

    def score(self, frame16: bytes) -> float:
        """Score one 80 ms int16 frame against the wake word."""
        import numpy as np
        model = self._ensure()
        pcm = np.frombuffer(frame16, dtype=np.int16)
        if len(pcm) != 1280:                      # pad/trim defensively
            buf = np.zeros(1280, dtype=np.int16)
            n = min(1280, len(pcm))
            buf[:n] = pcm[:n]
            pcm = buf
        out = model.predict(pcm)
        val = float(out.get(self.wakeword, 0.0))
        self.last_score = val
        return val

    # ------------------------------------------------------------------- sink
    def make_sink(self, on_hit, threshold: float | None = None,
                  cooldown: float = 1.5):
        """Return a frame-sink for the audio engine.

        on_hit(score) fires once per cooldown window when score >= threshold.
        """
        thr = self.threshold if threshold is None else threshold
        buf = bytearray()
        hit_at = -1e9
        import time as _time

        def sink(frame: bytes) -> None:
            nonlocal hit_at, buf
            buf.extend(frame)
            if len(buf) < 1280 * 2:              # need >= 80 ms of samples
                return
            while len(buf) >= 1280 * 2:
                chunk = bytes(buf[:1280 * 2])
                del buf[:1280 * 2]
                s = self.score(chunk)
                now = _time.monotonic()
                if s >= thr and (now - hit_at) >= cooldown:
                    hit_at = now
                    try:
                        on_hit(s)
                    except Exception as e:
                        print(f"[wake] handler error: {e}")

        return sink

"""
JARVIS hearing — faster-whisper offline transcription.

CPU int8 with beam_size=1: tuned for near-real-time dictation of short
utterances on a normal machine. Model loads lazily on first use.
"""

import threading

import numpy as np


class Transcriber:
    def __init__(self, model_name: str = "base.en"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def preload(self) -> None:
        self._ensure()

    def _ensure(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu",
                                           compute_type="int8", cpu_threads=4)
            return self._model

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono @ 16 kHz in [-1, 1]. Returns recognised text."""
        if audio is None or len(audio) < 160:
            return ""
        model = self._ensure()
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 120},
            condition_on_previous_text=False,
        )
        text = "".join(s.text for s in segments).strip()
        return " ".join(text.split())

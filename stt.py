"""
JARVIS hearing — faster-whisper offline transcription.

CPU int8 with beam_size=1: tuned for near-real-time dictation of short
utterances on a normal machine. Model loads lazily on first use.

Hinglish support (Phase 3): the default is a *multilingual* model with
automatic language detection plus an initial prompt biased toward
Hindi-English code-mixed speech (the faster-whisper equivalent of the
`en-IN` locale trick used by Android's SpeechRecognizer). English-only
`.en` models are auto-upgraded to their multilingual sibling unless the
language is explicitly pinned to "en".
"""

import threading

import numpy as np

from protocols import load_prompt

# Compatibility alias; default transcription reads the current TXT section
# for every utterance so the wording remains centrally editable.
HINGLISH_PROMPT = load_prompt("STT_TRANSCRIPTION_PROMPT")


class Transcriber:
    def __init__(self, model_name: str = "base", language: str = "auto",
                 initial_prompt: str | None = None):
        # Auto-upgrade English-only models (base.en -> base) so Hinglish
        # isn't mangled — unless English was explicitly requested.
        if (isinstance(model_name, str) and model_name.endswith(".en")
                and (language or "auto") != "en"):
            model_name = model_name[:-len(".en")]
        self.model_name = model_name
        self.language = (language or "auto").strip().lower()
        self.initial_prompt = initial_prompt
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
        kwargs = dict(
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 120},
            condition_on_previous_text=False,
        )
        # "auto" (default) lets whisper detect the language per utterance —
        # this is what makes Hindi-English mixing work.
        if self.language != "auto":
            kwargs["language"] = self.language
        prompt = (self.initial_prompt if self.initial_prompt is not None
                  else load_prompt("STT_TRANSCRIPTION_PROMPT"))
        if prompt:
            kwargs["initial_prompt"] = prompt
        segments, _info = model.transcribe(audio, **kwargs)
        text = "".join(s.text for s in segments).strip()
        return " ".join(text.split())

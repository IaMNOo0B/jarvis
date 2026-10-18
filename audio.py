"""
JARVIS audio engine — one microphone, three modes.

The mic callback only enqueues; a dispatcher thread delivers each 100 ms frame
to the *active sink* (wake-word listener, utterance collector, or nothing while
thinking). The controller switches sinks atomically, so nothing ever competes
for frames. `level` (EMA RMS) feeds the HUD waveform continuously.

Also provides the interaction chimes — no audio assets needed.
"""

import queue
import threading

import numpy as np
import sounddevice as sd

RATE = 16000          # samples/s — matches openWakeWord + faster-whisper
BLOCK = 1600          # 100 ms per frame


class AudioEngine:
    def __init__(self, silence_seconds: float = 1.2,
                 speech_start_seconds: float = 0.35,
                 max_utterance_seconds: float = 30.0,
                 listen_timeout_seconds: float = 10.0):
        self.level = 0.0                    # smoothed mic RMS for the HUD
        self.silence_seconds = silence_seconds
        self.speech_start_seconds = speech_start_seconds
        self.max_utterance_seconds = max_utterance_seconds
        self.listen_timeout_seconds = listen_timeout_seconds

        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=400)
        self._sink_lock = threading.Lock()
        self._sink = None
        self._stream = None
        self._dispatcher = threading.Thread(target=self._dispatch, daemon=True,
                                            name="jarvis-audio-dispatch")
        self._running = False

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatcher.start()
        self._stream = sd.RawInputStream(
            samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        self._running = False
        try:
            if self._stream:
                self._stream.stop(); self._stream.close()
        except Exception:
            pass
        try:
            self._q.put_nowait(None)
        except Exception:
            pass

    # ---------------------------------------------------------------- routing
    def set_sink(self, sink) -> None:
        """Install a frame consumer (bytes of int16) or None to mute."""
        with self._sink_lock:
            self._sink = sink

    def _callback(self, indata, frames, time_info, status) -> None:
        pcm = bytes(indata)
        rms = float(np.sqrt(np.mean(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) ** 2))) / 32768.0
        self.level = self.level * 0.75 + rms * 0.25
        try:
            self._q.put_nowait(pcm)
        except queue.Full:                      # never block the audio thread
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put_nowait(pcm)

    def _dispatch(self) -> None:
        while self._running:
            frame = self._q.get()
            if frame is None:
                return
            with self._sink_lock:
                sink = self._sink
            if sink is not None:
                try:
                    sink(frame)
                except Exception as e:
                    print(f"[audio] sink error: {e}")

    # ------------------------------------------------------- utterance capture
    def collect_utterance(self) -> np.ndarray | None:
        """Block until a complete spoken utterance (or None on timeout).

        Energy VAD with an adaptive noise floor: wait for speech, then collect
        until `silence_seconds` of quiet, capped at `max_utterance_seconds`.
        """
        done = threading.Event()
        chunks: list[np.ndarray] = []
        result: dict = {"audio": None}
        ambient = 0.01
        state = "wait"                       # wait -> speech
        speech_rms = []
        quiet_since = None
        started_at = None
        active = True
        lock = threading.Lock()

        def threshold() -> float:
            return max(0.018, ambient * 3.5)

        def sink(frame: bytes):
            nonlocal ambient, state, quiet_since, started_at
            with lock:
                if not active:
                    return
            pcm = np.frombuffer(frame, dtype=np.int16)
            audio = pcm.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(audio * audio)))
            thr = threshold()

            now_ts = len(chunks) * (BLOCK / RATE)  # cheap monotonic-ish timeline

            if state == "wait":
                ambient = ambient * 0.97 + rms * 0.03 if rms < thr * 2 else ambient
                if rms > thr:
                    speech_rms.append(rms)
                    held = len(speech_rms) * 0.1
                    if held >= self.speech_start_seconds:
                        state = "speech"
                        started_at = now_ts
                        chunks.append(audio)      # start a little before onset
                else:
                    speech_rms.clear()
                return

            # state == speech
            chunks.append(audio)
            total = len(chunks) * 0.1
            if rms < thr * 0.8:
                if quiet_since is None:
                    quiet_since = total
                elif total - quiet_since >= self.silence_seconds:
                    with lock:
                        active = False
                    done.set()
            else:
                quiet_since = None
            if total >= self.max_utterance_seconds:
                with lock:
                    active = False
                done.set()

        self.set_sink(sink)
        finished = done.wait(timeout=self.listen_timeout_seconds + self.max_utterance_seconds)
        with lock:
            active = False
        if not finished:
            self.set_sink(None)
            return None
        if not done.is_set():                 # timed out waiting for speech start
            self.set_sink(None)
            return None
        audio = np.concatenate(chunks) if chunks else None
        if audio is not None and len(audio) < 0.1 * RATE:
            audio = None
        # caller is expected to set a new sink (mute or wake) right after
        return audio


# ------------------------------------------------------------------- chimes
def _tone(freqs_durations: list[tuple[float, float]], volume: float = 0.25) -> None:
    sr = 22050
    parts = []
    for freq, dur in freqs_durations:
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        wave_ = np.sin(2 * np.pi * freq * t)
        env = np.minimum(1.0, np.linspace(0, 1, len(t)) * 6) * \
              np.minimum(1.0, np.linspace(1, 0, len(t)) * 4 + 0.2)
        parts.append((wave_ * env * volume).astype(np.float32))
    audio = np.concatenate(parts)
    with sd.OutputStream(samplerate=sr, channels=1, dtype="float32") as s:
        s.write(audio)


def play_wake_chime() -> None:
    """Rising two-note 'listening' chime."""
    try:
        _tone([(880, 0.09), (1320, 0.12)], volume=0.22)
    except Exception as e:
        print(f"[audio] chime failed: {e}")


def play_done_chime() -> None:
    """Falling two-note 'finished' chime (JARVIS is done speaking)."""
    try:
        _tone([(1320, 0.07), (880, 0.10)], volume=0.14)
    except Exception as e:
        print(f"[audio] chime failed: {e}")


def play_attention_tone() -> None:
    """Single mid tone — used by push-to-talk."""
    try:
        _tone([(988, 0.10)], volume=0.2)
    except Exception as e:
        print(f"[audio] tone failed: {e}")

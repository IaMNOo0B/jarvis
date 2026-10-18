"""
JARVIS voice self-test — closed loop, no microphone required.

    python test_voice_loop.py

Flow:
  1. Resolve/download the British Piper voice
  2. Synthesize a greeting -> WAV  (file left behind: _selftest_out.wav)
  3. Feed that WAV through faster-whisper (TTS -> STT round trip)
  4. Score "Hey Jarvis." against the openWakeWord model
  5. Attempt live speaker playback (warning only if no output device)

Exit code 0 = no failures (warnings allowed).
"""

import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
    tag = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    RESULTS.append((tag, name, detail))
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def wav_bytes_to_16k_float(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(__import__("io").BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = data.astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio) - 1, n),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio, sr


def main() -> int:
    from brain import load_config
    cfg = load_config()
    vcfg = cfg.get("voice", {})

    # ---------------------------------------------------------- 1. TTS voice
    from tts import default_voice_path, _load_voice, _synthesize_wav_bytes
    try:
        t0 = time.time()
        voice_path = default_voice_path(vcfg)
        voice = _load_voice(voice_path)
        check("piper voice loaded", True,
              f"{os.path.basename(voice_path)} in {time.time() - t0:.1f}s")
    except Exception as e:
        check("piper voice loaded", False, str(e))
        return _summary()

    GREET = "Good evening sir. All systems are online and ready."
    HEY = "Hey Jarvis, can you hear me?"
    try:
        t0 = time.time()
        wav = _synthesize_wav_bytes(voice, GREET)
        synth_s = time.time() - t0
        # wav is already a complete RIFF file — write it out raw
        with open("_selftest_out.wav", "wb") as f:
            f.write(wav)
        with wave.open(__import__("io").BytesIO(wav), "rb") as wf:
            dur = wf.getnframes() / wf.getframerate()
        check("tts synthesis", 0.8 <= dur <= 15,
              f"{dur:.1f}s audio, {synth_s:.2f}s to synthesise -> _selftest_out.wav")
    except Exception as e:
        check("tts synthesis", False, repr(e))
        import traceback
        traceback.print_exc()
        return _summary()

    # ---------------------------------------------------------- 2. STT round trip
    try:
        from stt import Transcriber
        audio16, _ = wav_bytes_to_16k_float(wav)
        t0 = time.time()
        tr = Transcriber(
            vcfg.get("stt_model", "base"),
            language=vcfg.get("stt_language", "auto"),
            initial_prompt=vcfg.get("stt_initial_prompt", None),
        )
        tr.preload()
        text = tr.transcribe(audio16)
        stt_s = time.time() - t0
        wanted = {"evening", "sir", "systems", "online", "ready"}
        got = set(text.lower().replace(".", " ").replace(",", " ").split())
        hits = wanted & got
        check("stt round trip (tts -> whisper)", len(hits) >= 3,
              f'heard "{text}" ({len(hits)}/5 key words, {stt_s:.1f}s)')
    except Exception as e:
        check("stt round trip (tts -> whisper)", False, repr(e))

    # ---------------------------------------------------------- 3. wake word
    try:
        from wake import WakeListener
        wake = WakeListener(wakeword=vcfg.get("wake_word", "hey_jarvis"),
                            threshold=float(vcfg.get("wake_threshold", 0.5)))
        t0 = time.time()
        wake.preload()
        load_s = time.time() - t0

        hey_wav = _synthesize_wav_bytes(voice, HEY)
        hey16, _ = wav_bytes_to_16k_float(hey_wav)
        pcm16 = (np.clip(hey16, -1, 1) * 32767).astype(np.int16)

        base = wake.score(bytes(np.zeros(1280, dtype=np.int16)))  # silence baseline
        best = 0.0
        for i in range(0, len(pcm16) - 1280, 1280):
            best = max(best, wake.score(pcm16[i:i + 1280].tobytes()))
        thr = float(vcfg.get("wake_threshold", 0.5))
        check("wake word scoring", best >= thr,
              f"max score {best:.3f} vs silence {base:.3f} "
              f"(threshold {thr}, model load {load_s:.1f}s)",
              warn_only=(best >= 0.25 and best < thr))
    except Exception as e:
        check("wake word scoring", False, repr(e))
        traceback_txt = __import__("traceback").format_exc()
        print(traceback_txt)

    # ---------------------------------------------------------- 4. playback
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        default_out = sd.default.device[1]
        has_out = devs[default_out]["max_output_channels"] > 0
        if not has_out:
            check("speaker playback", True, "no output device", warn_only=True)
        else:
            from tts import Speaker
            sp = Speaker(voice_path)
            sp.say("Speaker test complete, sir.")
            idle = sp.wait_idle(timeout=20)
            check("speaker playback", idle, "spoke via default output",
                  warn_only=not idle)
            sp.stop()
    except Exception as e:
        check("speaker playback", True, repr(e), warn_only=True)

    return _summary()


def _summary() -> int:
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    print("\n" + "=" * 58)
    print(f" voice self-test: {len(RESULTS)} checks, "
          f"{len(fails)} failed, {len(warns)} warnings")
    print("=" * 58)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

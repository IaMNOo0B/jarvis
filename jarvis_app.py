"""
JARVIS — full application entry point.

    python jarvis_app.py                     # HUD + voice + camera + brain
    python jarvis_app.py --text              # console brain (no audio/HUD)
    python jarvis_app.py --no-camera         # without presence detection
    python jarvis_app.py --no-hud            # voice only, no overlay
    python jarvis_app.py --mute              # listens & thinks, prints replies
    python jarvis_app.py --test-audio F.wav  # one supervised end-to-end turn

State machine (voice thread):
    wake word / push-to-talk -> chime -> record (VAD) -> whisper ->
    brain tool loop -> Piper speech (barge-in capable) -> back to wake
"""

import argparse
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


# --------------------------------------------------------------------- speaker
class ConsoleSpeaker:
    """Prints instead of speaking (--mute or voice disabled)."""

    def __init__(self):
        self.level = 0.0
        self.on_state = None
        self._busy = False

    @property
    def busy(self):
        return self._busy

    def say(self, text: str) -> None:
        self._busy = True
        if self.on_state:
            self.on_state("speaking")
        print(f"\nJARVIS: {text}")
        self._busy = False
        if self.on_state:
            self.on_state("idle")

    def stop(self) -> None:
        pass

    def wait_idle(self, timeout=None) -> bool:
        return True


# --------------------------------------------------------------------- greeting
def time_greeting() -> str:
    h = time.localtime().tm_hour
    if 5 <= h < 12:
        return "Good morning, sir."
    if 12 <= h < 17:
        return "Good afternoon, sir."
    if 17 <= h < 23:
        return "Good evening, sir."
    return "Working late, sir."


class JarvisApp:
    def __init__(self, args):
        self.args = args
        from brain import BrainEngine, load_config
        self.cfg = load_config()
        if args.no_camera:
            self.cfg.setdefault("presence", {})["enabled"] = False
        if args.no_hud:
            self.cfg.setdefault("hud", {})["enabled"] = False
        # --mute keeps the microphone/wake word alive and swaps the speaker
        # for the console — 'listens & thinks, prints instead of speaking'.
        self.mute = bool(args.mute)

        self.voice_on = bool(self.cfg.get("voice", {}).get("enabled", True))
        self.hud_on = bool(self.cfg.get("hud", {}).get("enabled", True))
        self.wake_on = self.voice_on and bool(self.cfg.get("voice", {}).get("wake_enabled", True))

        # --- Qt (created by run()) ---
        self.app = None
        self.bridge = None
        self.hud = None

        # --- services ---
        self.speaker = None
        self.transcriber = None
        self.engine = None       # audio engine
        self.wake = None
        self.system_actions = None

        self._stop = threading.Event()
        self._wake_evt = threading.Event()
        self._ptt_evt = threading.Event()
        self._shutdown_evt = threading.Event()
        self._greeted_once = False
        self._inject_queue = []
        self._settings_open = False

        # brain with a HUD-aware emitter
        self.brain = BrainEngine(self.cfg, services={
            "confirm_destructive": bool(self.cfg.get("safety", {}).get("confirm_destructive", True)),
        }, emit=self._on_brain_event)

    # ---------------------------------------------------------------- events
    def _say(self, text: str) -> None:
        """Thread-safe speech entry — also mirrors into the transcript."""
        print(f"\nJARVIS: {text}", flush=True)
        if self.bridge:
            self.bridge.exchange.emit("jarvis", text)
            self.bridge.status.emit("speaking")
        if self.speaker:
            self.speaker.say(text)

    def _note(self, text: str) -> None:
        print(f"  · {text}", flush=True)
        if self.bridge:
            self.bridge.exchange.emit("system", text)

    def _on_brain_event(self, kind: str, payload) -> None:
        if not self.bridge:
            if kind in ("tool", "status"):
                print(f"  [{kind}] {payload}")
            return
        if kind == "status":
            self.bridge.status.emit(str(payload))
        elif kind == "tool":
            self.bridge.exchange.emit("system", f"⚡ {payload}")
        elif kind == "round":
            pass  # HUD status text already communicates progress

    # --------------------------------------------------------------- lifecycle
    def run(self) -> int:
        if self.args.text:
            return self._run_text()

        from PyQt6.QtWidgets import QApplication
        from overlay import HudBridge, HudWindow, HotkeyFilter, register_hotkeys
        from PyQt6.QtCore import QTimer

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.bridge = HudBridge()
        self.hud = HudWindow(self.bridge, self.cfg) if self.hud_on else None

        self._hotkey_filter = HotkeyFilter(self.bridge)
        self.app.installNativeEventFilter(self._hotkey_filter)
        self._hotkeys_ok = register_hotkeys()
        self.bridge.cmd_visibility.connect(lambda: self.hud.toggle_visible() if self.hud else None)
        self.bridge.cmd_clickthrough.connect(lambda: self.hud.toggle_click_through() if self.hud else None)
        self.bridge.cmd_ptt.connect(self._on_ptt)
        self.bridge.cmd_quit.connect(self.app.quit)
        self.bridge.cmd_settings.connect(self._open_settings)
        self.app.aboutToQuit.connect(self._cleanup)

        if self.hud:
            self.hud.model_lbl.setText(self._model_label())
            self.hud.show()

        # --- speakers & backends (load models off the GUI thread) ---
        self._setup_audio()
        self._setup_services()
        QTimer.singleShot(100, self._warm_up)
        QTimer.singleShot(400, self._startup_routines)
        if self.presence is not None:
            try:
                self.presence.start()
            except Exception as e:
                self._note(f"presence sensor failed to start: {e}")
        else:
            QTimer.singleShot(700, self._startup_greeting_if_no_camera)
        # camera-miss fallback: greet anyway if no face ever appears
        QTimer.singleShot(20000, self._fallback_greeting)

        if self.args.test_audio:
            self._inject_queue.append(self.args.test_audio)

        # --- controller + feeders ---
        if self.voice_on or self._inject_queue:
            threading.Thread(target=self._controller, daemon=True,
                             name="jarvis-controller").start()
        threading.Thread(target=self._level_feeder, daemon=True, name="jarvis-levels").start()
        threading.Thread(target=self._gauge_feeder, daemon=True, name="jarvis-gauges").start()

        print("[jarvis] running — Ctrl+Alt+J HUD, Ctrl+Alt+I interact, "
              "Ctrl+Alt+Space talk, Ctrl+Alt+S settings, Ctrl+Alt+Q quit")
        return self.app.exec()

    # -------------------------------------------------------------- settings
    def _open_settings(self) -> None:
        """Open the settings panel (from hotkey or HUD gear button)."""
        if self._settings_open:
            return
        self._settings_open = True
        try:
            from settings import open_settings_dialog
            if open_settings_dialog(self.cfg, self.hud):
                self._apply_settings()
        except Exception as e:
            self._note(f"settings panel failed: {e}")
        finally:
            self._settings_open = False

    def _apply_settings(self) -> None:
        """Apply freshly saved settings. Voice + HUD apply live; the brain
        picks the rest up on restart (the dialog says so)."""
        from brain import load_config
        fresh = load_config()
        self.cfg.clear()
        self.cfg.update(fresh)  # in place — BrainEngine keeps seeing updates
        vcfg = self.cfg.get("voice", {})

        # voice engine + API keys apply live: rebuild the speaker
        if self.voice_on and not self.mute and self.speaker is not None:
            try:
                from tts import create_speaker
                old = self.speaker
                self.speaker = create_speaker(vcfg)
                try:
                    old.stop()
                except Exception:
                    pass
                self._note("voice settings applied")
            except Exception as e:
                self._note(f"voice rebuild failed: {e}")

        # HUD corner/size/click-through apply live
        if self.hud is not None:
            try:
                self.hud.apply_config(self.cfg)
            except Exception as e:
                self._note(f"HUD apply failed: {e}")

        if self.bridge:
            self.bridge.toast.emit(
                "Settings saved — voice & HUD live · restart for brain changes")

    def _model_label(self) -> str:
        name = self.cfg.get("brain", {}).get("local_model", "local")
        short = name.split("/")[-1]
        if len(short) > 26:
            short = short[:24] + "…"
        suffix = ""
        if self.brain.cloud_configured:
            suffix = (f" + {self.brain.cloud_model}" if self.brain.cloud_model
                      else " + cloud")
        return f"local · {short}{suffix}"

    # ------------------------------------------------------------------ audio
    def _setup_audio(self) -> None:
        import system_actions
        self.system_actions = system_actions
        vcfg = self.cfg.get("voice", {})

        if self.voice_on and not self.mute:
            from tts import create_speaker
            try:
                self.speaker = create_speaker(vcfg)
                self.speaker.on_state = lambda s: self.bridge.status.emit("speaking" if s == "speaking" else "idle") if self.bridge else None
            except Exception as e:
                print(f"[jarvis] TTS unavailable ({e}) — falling back to console voice")
                self.speaker = ConsoleSpeaker()
                self.mute = True
        else:
            self.speaker = ConsoleSpeaker()

        if self._inject_queue or self.voice_on:
            from audio import AudioEngine
            self.engine = AudioEngine(
                silence_seconds=float(vcfg.get("silence_seconds", 1.2)),
                speech_start_seconds=float(vcfg.get("speech_start_seconds", 0.35)),
                max_utterance_seconds=float(vcfg.get("max_utterance_seconds", 30)),
                listen_timeout_seconds=float(vcfg.get("listen_timeout_seconds", 10)),
            )
            if not self._inject_queue:
                try:
                    self.engine.start()
                except Exception as e:
                    print(f"[jarvis] microphone unavailable ({e}) — voice input disabled")
                    self.voice_on = False
                    self.wake_on = False

        if self.wake_on:
            from wake import WakeListener
            v = self.cfg.get("voice", {})
            self.wake = WakeListener(wakeword=v.get("wake_word", "hey_jarvis"),
                                     threshold=float(v.get("wake_threshold", 0.5)))

        from stt import Transcriber
        vcfg = self.cfg.get("voice", {})
        self.transcriber = Transcriber(
            vcfg.get("stt_model", "base"),
            language=vcfg.get("stt_language", "auto"),
            initial_prompt=vcfg.get("stt_initial_prompt", None),
        )

    def _setup_services(self) -> None:
        """Wire scheduler + presence into system_actions and the brain."""
        import system_actions
        from scheduler import Scheduler

        self.scheduler = Scheduler(
            self.cfg.get("routines", {}),
            speak=lambda text: (self._note(f"⏰ {text}"), self._say(text)),
        )
        self.scheduler.configure(self.cfg.get("routines", {}))
        system_actions.SCHEDULER = self.scheduler
        self.scheduler.start()
        self.scheduler.start_daily_routines()
        self.brain.services["scheduler"] = self.scheduler

        self.presence = None
        if self.cfg.get("presence", {}).get("enabled", True) and not self.args.no_camera:
            from presence import Presence
            self.presence = Presence(self.cfg.get("presence", {}))
            self.presence.on_first_sight = self._on_first_sight
            self.presence.on_return = lambda: self._say("Welcome back, sir.")
            self.presence.on_away = lambda: self._note("Sir has left the desk.")
            self.presence.on_unavailable = self._on_camera_unavailable
            system_actions.PRESENCE = self.presence
            self.brain.services["presence"] = self.presence
            if self.hud:
                self.hud.presence_lbl.setText("◌ searching…")

    def _warm_up(self) -> None:
        """Load whisper + wake word + voice model without freezing the GUI."""
        def _load():
            if self.transcriber:
                try:
                    self.transcriber.preload()
                    self._note("speech recognition ready")
                except Exception as e:
                    self._note(f"speech recognition failed: {e}")
            if self.wake:
                try:
                    self.wake.preload()
                    self._note(f"wake word '{self.wake.wakeword}' armed")
                except Exception as e:
                    self._note(f"wake word unavailable: {e}")
        threading.Thread(target=_load, daemon=True, name="jarvis-warmup").start()

        # background health check for the local core
        def _check_core():
            try:
                import ollama
                ollama.list()
                self._note("local core online")
            except Exception as e:
                self._note(f"local core offline: {e}")
                if self.bridge:
                    self.bridge.status.emit("offline")
        threading.Thread(target=_check_core, daemon=True, name="jarvis-corecheck").start()

    # --------------------------------------------------------------- routines
    def _startup_routines(self) -> None:
        r = self.cfg.get("routines", {})
        if r.get("briefing_on_start"):
            text = self.scheduler.briefing_text("all")
            self._note("briefing scheduled")
            self.scheduler.speak(text)
        if r.get("create_desktop_icon", True):
            # icon render + win32com can take a moment — keep it off the GUI
            # thread; idempotent (no-op when the shortcut already exists)
            threading.Thread(target=self._ensure_shortcut,
                             daemon=True, name="jarvis-shortcut").start()

    @staticmethod
    def _ensure_shortcut() -> None:
        try:
            from shortcut import ensure_desktop_shortcut
            lnk = ensure_desktop_shortcut()
            if lnk:
                print(f"[shortcut] desktop icon ready: {lnk}", flush=True)
        except Exception as e:
            print(f"[shortcut] {e}", flush=True)

    def _on_first_sight(self) -> None:
        """Webcam saw sir for the first time — the movie greeting."""
        if self.bridge:
            self.bridge.presence.emit("● in view")
        if self._greeted_once:
            return
        self._greeted_once = True
        greet = time_greeting() + " All systems are online."
        threading.Thread(target=lambda: (time.sleep(0.6), self._say(greet)),
                         daemon=True).start()

    def _on_camera_unavailable(self) -> None:
        if self.bridge:
            self.bridge.presence.emit("◌ no camera")

    def _startup_greeting_if_no_camera(self) -> None:
        if self._greeted_once or self.presence is not None:
            return  # presence will greet when it sees sir
        self._greeted_once = True
        self._say(time_greeting() + " All systems are online.")

    def _fallback_greeting(self) -> None:
        """Camera never saw sir (blocked/missing) — greet anyway."""
        if not self._greeted_once:
            if self.presence is not None:
                self._note("presence: no camera view — using timed greeting")
                if self.hud:
                    self.bridge.presence.emit("◌ no camera")
            self._greeted_once = True
            self._say(time_greeting() + " All systems are online.")

    # ------------------------------------------------------------------ PTT
    def _on_ptt(self) -> None:
        self._ptt_evt.set()

    # ------------------------------------------------------------- controllers
    def _controller(self) -> None:
        """Voice state machine — runs on its own thread."""
        from audio import play_wake_chime
        vcfg = self.cfg.get("voice", {})
        barge_thr = float(vcfg.get("barge_in_threshold", 0.7))
        wake_thr = float(vcfg.get("wake_threshold", 0.5))

        # test-audio path: supervised single turn, no wake word needed
        while not self._stop.is_set() and self._inject_queue:
            path = self._inject_queue.pop(0)
            audio = self._load_test_audio(path)
            if audio is None:
                self._note(f"could not read test audio {path}")
                break
            self._run_turn(audio)
            if self.args.test_audio:
                self._stop.set()
                if self.bridge:
                    self.bridge.cmd_quit.emit()      # queued to the GUI thread
                return

        wake_sink = None
        barge_sink = None
        if self.wake and self.wake_on:
            try:
                self.wake.preload()
                wake_sink = self.wake.make_sink(
                    lambda s: self._wake_evt.set(), threshold=wake_thr)
                barge_sink = self.wake.make_sink(
                    lambda s: (self._wake_evt.set(), self.speaker.stop()),
                    threshold=barge_thr, cooldown=2.0)
            except Exception as e:
                self._note(f"wake word disabled: {e}")
                self.wake_on = False

        while not self._stop.is_set():
            # ---- waiting for "Jarvis" ----
            if self.bridge:
                self.bridge.status.emit("idle")
            if self.wake_on and wake_sink:
                self.engine.set_sink(wake_sink)
            else:
                self.engine.set_sink(None)

            triggered = False
            while not self._stop.is_set() and not triggered:
                triggered = self._wake_evt.wait(timeout=0.2)
                if not triggered and self._ptt_evt.is_set():
                    self._ptt_evt.clear()
                    triggered = True
            if self._stop.is_set():
                break
            self._wake_evt.clear()
            self._ptt_evt.clear()
            self.engine.set_sink(None)                  # mute during the chime

            # ---- capture an utterance ----
            if self.bridge:
                self.bridge.status.emit("listening")
            play_wake_chime()
            audio = self.engine.collect_utterance()
            self.engine.set_sink(None)
            if audio is None:
                self._note("didn't catch that")
                continue
            self._run_turn(audio, barge_sink=barge_sink)

        self.engine and self.engine.set_sink(None)

    def _run_turn(self, audio, barge_sink=None) -> None:
        """STT -> brain -> speech for one captured utterance."""
        try:
            text = self.transcriber.transcribe(audio)
        except Exception as e:
            self._note(f"transcription failed: {e}")
            return
        if not text:
            self._note("(nothing intelligible)")
            return
        print(f"\nYou: {text}", flush=True)
        if self.bridge:
            self.bridge.exchange.emit("you", text)

        result = self.brain.respond(text)
        if result.error == "busy":
            return
        reply = result.reply or "(no reply)"
        if self.bridge:
            self.bridge.exchange.emit("jarvis", reply)
            self.bridge.status.emit("speaking")
        self.speaker.say(reply)

        # ---- barge-in window ----
        if barge_sink and self.engine and self.voice_on:
            interrupted = False
            while self.speaker.busy and not self._stop.is_set():
                self.engine.set_sink(barge_sink)
                time.sleep(0.1)
                if self._wake_evt.is_set():
                    self._wake_evt.clear()
                    interrupted = True
                    break
            self.engine.set_sink(None)
            if interrupted:
                self._note("interrupted")
        else:
            self.speaker.wait_idle()

        if self.bridge:
            self.bridge.status.emit("idle")

    # ------------------------------------------------------------ test audio
    def _load_test_audio(self, path: str):
        import numpy as np
        import wave
        try:
            with wave.open(path, "rb") as wf:
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
            return audio
        except Exception as e:
            print(f"[jarvis] test audio error: {e}")
            return None

    # --------------------------------------------------------------- feeders
    def _level_feeder(self) -> None:
        while not self._stop.is_set():
            if self.bridge and self.engine:
                speaking = self.speaker is not None and self.speaker.busy
                if speaking:
                    self.bridge.level.emit(self.speaker.level, "spk")
                else:
                    self.bridge.level.emit(self.engine.level, "mic")
            time.sleep(0.05)

    def _gauge_feeder(self) -> None:
        from diagnostics import diagnostics
        while not self._stop.is_set():
            if self.bridge:
                try:
                    self.bridge.gauges.emit(diagnostics.light())
                except Exception:
                    pass
            time.sleep(2.0)

    # ---------------------------------------------------------------- cleanup
    def _cleanup(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            from overlay import unregister_hotkeys
            if getattr(self, "_hotkeys_ok", False):
                unregister_hotkeys()
        except Exception:
            pass
        try:
            self.speaker and self.speaker.stop()
        except Exception:
            pass
        try:
            self.engine and self.engine.close()
        except Exception:
            pass
        try:
            self.scheduler and self.scheduler.stop()
        except Exception:
            pass
        try:
            self.presence and self.presence.shutdown()
        except Exception:
            pass
        print("[jarvis] shutdown complete")

    # ------------------------------------------------------------- text mode
    def _run_text(self) -> int:
        print("=" * 74)
        print(" JARVIS — text mode (voice/HUD off)")
        print(f" model : {self.brain.model}")
        print(f" cloud : {'configured' if self.brain.cloud_configured else 'not configured'}")
        print(" type 'quit' to exit, 'reset' to clear memory context")
        print("=" * 74)
        # start services (reminders work from the console) but never the camera
        self.cfg.setdefault("presence", {})["enabled"] = False
        self._setup_services()
        print(self.scheduler.briefing_text("system"))

        while True:
            try:
                user = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nJARVIS: Session ended.")
                break
            if not user:
                continue
            if user.lower() in ("quit", "exit"):
                print("JARVIS: Shutting down. Goodbye!")
                break
            if user.lower() == "reset":
                self.brain.reset()
                print("  · conversation cleared")
                continue
            result = self.brain.respond(user)
            if result.error and result.error != "busy":
                print(f"  [!] {result.error}")
            if result.reply:
                print(f"\nJARVIS: {result.reply}")
        self._cleanup()
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="JARVIS — movie-accurate AI assistant")
    ap.add_argument("--text", action="store_true", help="console mode, no HUD/audio")
    ap.add_argument("--no-hud", action="store_true", help="run without the HUD overlay")
    ap.add_argument("--no-camera", action="store_true", help="disable presence detection")
    ap.add_argument("--no-wake", action="store_true", help="disable wake word (push-to-talk only)")
    ap.add_argument("--mute", action="store_true", help="print replies instead of speaking")
    ap.add_argument("--test-audio", metavar="FILE.wav",
                    help="run one supervised turn from a wav file, then exit")
    args = ap.parse_args()
    app = JarvisApp(args)
    if args.no_wake:
        app.wake_on = False
    return app.run()


if __name__ == "__main__":
    sys.exit(main())

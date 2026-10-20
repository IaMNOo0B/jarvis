"""
Watching eyes — proactive screen awareness (Phase 6).

A background thread captures the screen every `interval_seconds`, asks the
cloud brain (Gemini vision) what's happening, and — rarely — speaks up,
like a butler noticing you're stuck: "I see you're fighting that error, sir."

The cost-control pattern (adapted from ArtinSHF/Jarvis-AI-Assistant):
  * probabilistic gating — even a high stuck-score only *sometimes* speaks
  * interest boost      — the same struggle persisting across captures
                          raises the odds
  * cooldowns           — minimum silence between remarks
  * in-RAM captures     — screenshots are resized JPEGs in BytesIO;
                          they never touch the disk
  * own-window skip     — never reacts to the JARVIS HUD itself
  * rotating styles     — remarks don't all sound the same

Privacy: captures live in RAM and are sent to the cloud vision endpoint
only while enabled. Default OFF — opt in via config.yaml.

No new dependencies: Pillow (ImageGrab) + pywin32 are already required.
"""

import base64
import io
import json
import random
import re
import threading
import time

_STYLES = ("observant", "helpful", "dry wit")

from protocols import apply_protocols, load_prompt



class ScreenWatcher:
    """Watches the screen; calls on_remark(text) on rare, gated occasions.

    analyze_image(jpeg_b64, prompt) -> (text|None, error|None): injected
        vision backend (the app passes brain.vision_describe).
    is_idle() -> bool: injected gate (the app passes speaker-idle and
        brain-free checks) so remarks never interrupt real work.
    on_remark(text): injected delivery (the app notes + speaks it).
    own_hwnd: native handle of the JARVIS HUD — its focus is skipped.
    """

    def __init__(self, analyze_image=None, is_idle=None, on_remark=None,
                 own_hwnd=None, interval_seconds=60, cooldown_seconds=600,
                 stuck_threshold=7, speak_probability=0.35):
        self.analyze_image = analyze_image
        self.is_idle = is_idle
        self.on_remark = on_remark or (lambda t: None)
        self.own_hwnd = own_hwnd
        self.interval = max(15, int(interval_seconds or 60))
        self.cooldown = max(60, int(cooldown_seconds or 600))
        self.threshold = int(stuck_threshold if stuck_threshold is not None else 7)
        self.probability = min(1.0, max(0.0, float(speak_probability
                                                  if speak_probability is not None
                                                  else 0.35)))
        self._stop = threading.Event()
        self._thread = None
        self._guard = threading.Lock()

    # -------------------------------------------------------------- control
    def start(self) -> bool:
        """Begin watching in a daemon thread. Idempotent."""
        with self._guard:
            if self._thread and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="jarvis-watcher")
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._guard:
            self._stop.set()
            t, self._thread = self._thread, None
        if t and t is not threading.current_thread():
            t.join(timeout=5)

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        last_summary, last_window = "", ""
        persist, style_idx = 0, 0
        last_remark, last_spoke = "nothing yet", 0.0
        while not self._stop.wait(self.interval):
            if self.analyze_image is None:
                continue
            hwnd, title = self._foreground_info()
            if self.own_hwnd and hwnd == self.own_hwnd:
                continue  # never react to our own HUD
            try:
                img = self._capture()
            except Exception:
                continue
            style = _STYLES[style_idx % len(_STYLES)]
            text, err = self._analyze(img, style, last_remark)
            if err or not text:
                continue
            data = self._parse(text)
            if not data:
                continue
            summary = str(data.get("summary", ""))
            try:
                score = int(data.get("stuck_score", 0) or 0)
            except (TypeError, ValueError):
                score = 0
            # interest boost: same window, same struggle, persisting
            if title and title == last_window and self._similar(summary, last_summary):
                persist += 1
            else:
                persist = 0
            last_summary, last_window = summary, title
            if score < self.threshold:
                continue
            # Probabilistic gate: the configured probability is AMPLIFIED by
            # the interest boost (same struggle persisting), but a 0.0
            # probability always stays silent — boost never creates
            # willingness from nothing.
            p = min(1.0, self.probability * (1.0 + 0.5 * min(persist, 3)))
            if random.random() > p:
                continue  # stay rare
            if time.monotonic() - last_spoke < self.cooldown:
                continue
            remark = str(data.get("remark", "") or "").strip()
            if not remark or remark == last_remark:
                continue
            try:
                if self.is_idle is not None and not self.is_idle():
                    continue  # never interrupt real work
            except Exception:
                continue
            last_spoke = time.monotonic()
            last_remark = remark
            style_idx += 1
            try:
                self.on_remark(remark)
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def _analyze(self, img_b64: str, style: str, last_remark: str):
        try:
            return self.analyze_image(
                img_b64, apply_protocols(load_prompt("SCREEN_WATCHER_PROMPT").format(style=style, last_remark=last_remark)))
        except Exception as e:
            return None, str(e)

    @staticmethod
    def _capture(max_width: int = 640) -> str:
        """Screenshot -> base64 JPEG. RAM only, never touches disk."""
        from PIL import ImageGrab
        img = ImageGrab.grab()
        w, h = img.size
        if w > max_width:
            img = img.resize((max_width, int(h * max_width / w)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def _foreground_info():
        """(hwnd, title) of the focused window; (None, '') on failure."""
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            return hwnd, win32gui.GetWindowText(hwnd)
        except Exception:
            return None, ""

    @staticmethod
    def _parse(text: str):
        """Extract the JSON verdict from a model reply."""
        try:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else json.loads(text)
            if isinstance(data, dict) and "stuck_score" in data:
                return data
        except Exception:
            pass
        return None

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """Crude 'same struggle' check: 3+ shared words."""
        if not a or not b:
            return False
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        return len(wa & wb) >= 3

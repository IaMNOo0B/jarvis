"""
JARVIS presence sensor — webcam face detection.

Greets sir the first time he appears, and when he returns after being away.
The thread is launched once and pauses/resumes via an active flag (so the
presence_control tool can turn the camera off and on again safely); the camera
is only opened while active. All callbacks fire on the detection thread —
jarvis_app wraps them to reach the speaker/HUD safely.
"""

import threading
import time


class Presence(threading.Thread):
    def __init__(self, cfg: dict | None = None):
        super().__init__(daemon=True, name="jarvis-presence")
        cfg = cfg or {}
        self.enabled_cfg = bool(cfg.get("enabled", True))
        self.away_minutes = float(cfg.get("away_minutes", 5))
        self.greet_on_return = bool(cfg.get("greet_on_return", True))
        self.auto_lock = bool(cfg.get("auto_lock_on_away", False))
        self.camera_index = int(cfg.get("camera_index", 0))
        self.interval = float(cfg.get("detect_interval_seconds", 2.0))

        self.on_first_sight = None   # callable() — startup greeting
        self.on_away = None          # callable() — left the desk
        self.on_return = None        # callable() — came back
        self.on_unavailable = None   # callable() — camera could not be opened

        self._stop_evt = threading.Event()
        self._active = threading.Event()
        if self.enabled_cfg:
            self._active.set()
        self._launched = False
        self._state = "idle"         # idle | searching | present | away | unavailable
        self._last_seen = 0.0
        self._ever_seen = False
        self._lock = threading.Lock()

    # -------------------------------------------------------------- controls
    def start(self) -> None:
        """Launch the thread once; subsequent calls just re-enable the camera."""
        self._active.set()
        if not self._launched:
            self._launched = True
            super().start()

    def stop(self) -> None:
        """Pause: releases the camera; the thread stays alive for resume."""
        self._active.clear()

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._active.set()          # unblock any wait

    def status(self) -> str:
        with self._lock:
            s = self._state
        return {
            "idle": "off",
            "searching": "searching for you",
            "present": "you are in view",
            "away": "you have been away",
            "unavailable": "camera unavailable",
        }.get(s, s)

    # -------------------------------------------------------------- detection
    def run(self) -> None:
        import cv2

        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        while not self._stop_evt.is_set():
            if not self._active.wait(timeout=1.0):
                with self._lock:
                    if self._state != "idle":
                        self._state = "idle"
                continue

            cap = self._open_camera(cv2)
            if cap is None:
                with self._lock:
                    self._state = "unavailable"
                print("[presence] camera unavailable — check camera privacy settings "
                      "(will retry)", flush=True)
                if self.on_unavailable:
                    _safe(self.on_unavailable)
                while self._active.is_set() and not self._stop_evt.is_set():
                    time.sleep(5.0)       # retry camera later
                continue

            with self._lock:
                self._state = "searching"
            print(f"[presence] camera #{self.camera_index} active")

            while self._active.is_set() and not self._stop_evt.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(self.interval)
                    continue
                self._inspect(cv2, cascade, frame)
                time.sleep(self.interval)

            cap.release()
            with self._lock:
                self._state = "idle"
            print("[presence] camera released")

    def _open_camera(self, cv2):
        backends = [None]
        for b in ("CAP_DSHOW", "CAP_MSMF"):
            if hasattr(cv2, b):
                backends.append(getattr(cv2, b))
        tried = []
        for idx in (self.camera_index, 0, 1, 2):
            if idx not in tried:
                tried.append(idx)
        for backend in backends:
            for idx in tried:
                try:
                    cap = (cv2.VideoCapture(idx) if backend is None
                           else cv2.VideoCapture(idx, backend))
                except Exception:
                    continue
                if cap.isOpened():
                    self.camera_index = idx
                    return cap
                cap.release()
        return None

    def _inspect(self, cv2, cascade, frame) -> None:
        small = cv2.resize(frame, (320, int(frame.shape[0] * 320 / frame.shape[1])))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1,
                                         minNeighbors=5, minSize=(40, 40))
        now = time.time()
        saw_face = len(faces) > 0

        cb_first = cb_return = cb_away = None
        with self._lock:
            if saw_face:
                was_away = self._state == "away"
                self._last_seen = now
                first_time = not self._ever_seen
                self._ever_seen = True
                self._state = "present"
                if first_time:
                    cb_first = self.on_first_sight
                if was_away and self.greet_on_return:
                    cb_return = self.on_return
            else:
                away_for = now - self._last_seen if self._last_seen else 0
                if self._ever_seen and self._state == "present" \
                        and away_for > self.away_minutes * 60:
                    self._state = "away"
                    cb_away = self.on_away
                    if self.auto_lock:
                        try:
                            import ctypes
                            ctypes.windll.user32.LockWorkStation()
                        except Exception:
                            pass

        # fire callbacks outside the lock
        if cb_first:
            _safe(cb_first)
        if cb_return:
            _safe(cb_return)
        if cb_away:
            _safe(cb_away)


def _safe(cb) -> None:
    try:
        cb()
    except Exception as e:
        print(f"[presence] callback error: {e}")

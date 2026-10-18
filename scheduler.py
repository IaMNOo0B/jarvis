"""
JARVIS proactive scheduler — reminders, daily briefings, scheduled speech.

A single daemon thread consumes a heap of (due_ts, kind, payload) events.
The speaker is injected (speaker.say from the voice layer) so this module
works in text mode too (falls back to printing).
"""

import heapq
import threading
import time

import requests

from diagnostics import diagnostics


def _speak_default(text: str) -> None:
    print(f"\n[JARVIS speaks] {text}")


class Scheduler(threading.Thread):
    def __init__(self, routines_cfg: dict | None = None, speak=None):
        super().__init__(daemon=True, name="jarvis-scheduler")
        cfg = routines_cfg or {}
        self.speak = speak or _speak_default
        self.weather_location = cfg.get("weather_location", "") or ""
        self._heap: list[tuple[float, int, str, object]] = []
        self._seq = 0
        self._cv = threading.Condition()
        self._stop_evt = threading.Event()

    # ------------------------------------------------------------- lifecycle
    def run(self) -> None:
        while not self._stop_evt.is_set():
            with self._cv:
                while not self._heap and not self._stop_evt.is_set():
                    self._cv.wait(timeout=1.0)
                if self._stop_evt.is_set():
                    return
                now = time.time()
                due_ts, _seq, kind, payload = self._heap[0]
                if due_ts > now:
                    self._cv.wait(timeout=min(due_ts - now, 1.0))
                    continue
                heapq.heappop(self._heap)
            try:
                self._fire(kind, payload)
            except Exception as e:  # never let a routine kill the thread
                print(f"[scheduler] routine error: {e}")

    def stop(self) -> None:
        self._stop_evt.set()
        with self._cv:
            self._cv.notify_all()

    # --------------------------------------------------------------- schedule
    def _push(self, due_ts: float, kind: str, payload) -> None:
        with self._cv:
            self._seq += 1
            heapq.heappush(self._heap, (due_ts, self._seq, kind, payload))
            self._cv.notify_all()

    def start_daily_routines(self) -> None:
        """(Re-)arm morning/evening briefings for every future occurrence today+."""
        from datetime import datetime, timedelta
        for cfg_key, kind in (("morning_briefing", "morning"),
                              ("evening_briefing", "evening")):
            hhmm = str(self._schedules.get(cfg_key, "") or "")
            if not hhmm or len(hhmm) < 4:
                continue
            h, m = int(hhmm[:2]), int(hhmm[3:5])
            now = datetime.now()
            nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            self._push(nxt.timestamp(), "daily", {"kind": kind, "hhmm": hhmm})

    _schedules: dict = {}

    def configure(self, routines_cfg: dict) -> None:
        self._schedules = routines_cfg or {}

    # -------------------------------------------------------------- reminders
    def add_reminder_in(self, text: str, minutes: float) -> str:
        when = time.strftime("%H:%M", time.localtime(time.time() + minutes * 60))
        self._push(time.time() + minutes * 60, "reminder", text)
        return f"Reminder set for {when}: {text}"

    def add_reminder_at(self, text: str, hhmm: str) -> str:
        from datetime import datetime
        hh, mm = int(hhmm[:2]), int(hhmm[3:5])
        target = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target.timestamp() <= time.time():
            from datetime import timedelta
            target += timedelta(days=1)
        self._push(target.timestamp(), "reminder", text)
        return f"Reminder set for {target.strftime('%H:%M')}: {text}"

    # ------------------------------------------------------------------ fires
    def _fire(self, kind: str, payload) -> None:
        if kind == "reminder":
            self.speak(f"Sir, a reminder — {payload}.")
        elif kind == "daily":
            self.speak(self.briefing_text(payload["kind"]))
            # re-arm for tomorrow
            from datetime import datetime, timedelta
            hh, mm = int(payload["hhmm"][:2]), int(payload["hhmm"][3:5])
            nxt = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=1)
            self._push(nxt.timestamp(), "daily", payload)

    # --------------------------------------------------------------- briefing
    def briefing_text(self, kind: str = "all") -> str:
        parts = []
        if kind in ("all", "weather"):
            w = self._weather()
            if w:
                parts.append(w)
        if kind in ("all", "news"):
            n = self._news()
            if n:
                parts.append(n)
        if kind in ("all", "system"):
            parts.append(diagnostics.summary_text().replace("Diagnostics complete, sir. ", ""))
        if not parts:
            return "All quiet on every front, sir."
        opener = {
            "weather": "The weather, sir.",
            "news": "Today's headlines, sir.",
            "system": "Systems, sir.",
        }.get(kind, "Your briefing, sir.")
        return opener + " " + " Also, ".join(parts)

    def _weather(self) -> str:
        try:
            url = "https://wttr.in/"
            if self.weather_location:
                url += self.weather_location.replace(" ", "%20") + "/"
            r = requests.get(url, params={"format": "j1"}, timeout=8,
                             headers={"User-Agent": "curl/8"})
            j = r.json()
            cc = (j.get("current_condition") or [{}])[0]
            desc = ((cc.get("weatherDesc") or [{}])[0]).get("Value") or "fair skies"
            temp = cc.get("temp_C", "?")
            feels = cc.get("FeelsLikeC", temp)
            humidity = cc.get("humidity", "?")
            area = (j.get("nearest_area") or [{}])[0]
            place = ((area.get("areaName") or [{}])[0]).get("value", "your area")
            return (f"Weather in {place}: {desc}, {temp} degrees feeling like {feels}, "
                    f"humidity {humidity} percent.")
        except Exception as e:
            return f"Weather service unreachable ({type(e).__name__}: {e})."

    def _news(self) -> str:
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                try:
                    items = list(ddgs.news("top news today", max_results=5))
                except Exception:
                    items = list(ddgs.text("top news headlines today", max_results=5))
            titles = [(i.get("title") or "").strip() for i in items]
            titles = [t for t in titles if t][:4]
            if not titles:
                return "No headlines available just now."
            return "Headlines: " + "; ".join(titles) + "."
        except Exception as e:
            return f"News service unreachable ({e})."

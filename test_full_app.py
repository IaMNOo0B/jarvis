"""
JARVIS full-app integration test.

Spawns `jarvis_app.py` exactly as a user would launch it, then drives it with
the real global hotkeys (pyautogui SendInput -> WM_HOTKEY) and screenshots:

  1. launch, wait for warmup, screenshot with HUD visible
  2. Ctrl+Alt+J -> HUD hides (region pixels must change)
  3. Ctrl+Alt+J -> HUD shows again
  4. Ctrl+Alt+Space -> push-to-talk -> listening (log gains a note)
  5. Ctrl+Alt+Q -> graceful quit -> "[jarvis] shutdown complete"

    python test_full_app.py
Exit code 0 = pass.
"""

import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "fullapp.log")
FAILS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def region_diff(img1, img2, screen_w, screen_h):
    """Mean abs pixel diff of the HUD's bottom-right corner region."""
    import numpy as np
    box = (max(0, screen_w - 520), max(0, screen_h - 720), screen_w, screen_h)
    a = np.asarray(img1.crop(box), dtype=np.int16)
    b = np.asarray(img2.crop(box), dtype=np.int16)
    return float(np.abs(a - b).mean())


def main() -> int:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.moveTo(400, 400)

    if os.path.exists(LOG):
        os.remove(LOG)
    logf = open(LOG, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-u", "jarvis_app.py"],
        cwd=BASE, stdout=logf, stderr=subprocess.STDOUT,
    )
    print(f"[test] spawned jarvis_app pid={proc.pid}", flush=True)

    try:
        # ---- 1. warmup ------------------------------------------------------
        time.sleep(15)
        import pyautogui as pg
        sw, sh = pg.size()
        shot1 = pg.screenshot()
        shot1.save("fullapp_1_running.png")

        # ---- 2. hide HUD ----------------------------------------------------
        pg.hotkey("ctrl", "alt", "j")
        time.sleep(2.0)
        shot2 = pg.screenshot()
        shot2.save("fullapp_2_hidden.png")
        diff = region_diff(shot1, shot2, sw, sh)
        check("hotkey Ctrl+Alt+J hides HUD", diff > 6.0,
              f"region pixel delta {diff:.1f}")

        # ---- 3. show HUD again ---------------------------------------------
        pg.hotkey("ctrl", "alt", "j")
        time.sleep(2.0)
        shot3 = pg.screenshot()
        diff_back = region_diff(shot3, shot2, sw, sh)
        check("hotkey Ctrl+Alt+J shows HUD again", diff_back > 6.0,
              f"region pixel delta {diff_back:.1f}")

        # ---- 4. push-to-talk ------------------------------------------------
        log_so_far = open(LOG, encoding="utf-8", errors="ignore").read()
        pg.hotkey("ctrl", "alt", "space")
        time.sleep(13)          # listen timeout (10 s) + margin
        log_ptt = open(LOG, encoding="utf-8", errors="ignore").read()
        heard_note = ("didn't catch that" in log_ptt
                      or "nothing intelligible" in log_ptt
                      or "JARVIS:" in log_ptt[len(log_so_far):])
        check("push-to-talk runs a listening turn", heard_note,
              "timeout/transcript note seen" if heard_note
              else "no note appended after Ctrl+Alt+Space")

        # ---- 5. graceful quit ----------------------------------------------
        pg.hotkey("ctrl", "alt", "q")
        try:
            rc = proc.wait(timeout=15)
            check("hotkey Ctrl+Alt+Q quits gracefully", rc == 0, f"exit={rc}")
        except subprocess.TimeoutExpired:
            check("hotkey Ctrl+Alt+Q quits gracefully", False,
                  "still running after 15s")
            proc.kill()
            proc.wait(timeout=10)

        # ---- log content asserts -------------------------------------------
        log = open(LOG, encoding="utf-8", errors="ignore").read()
        for label, needle in [
            ("app booted", "[jarvis] running"),
            ("local core checked", "local core online"),
            ("whisper warmed up", "speech recognition ready"),
            ("wake word armed", "wake word 'hey_jarvis' armed"),
            ("presence sensor ran", "[presence]"),
            ("greeting spoken", "All systems are online"),
            ("clean shutdown", "[jarvis] shutdown complete"),
        ]:
            check(f"log: {label}", needle in log,
                  "" if needle in log else f"missing {needle!r}")
        shot4_ok = os.path.exists("fullapp_1_running.png")
        check("screenshots captured", shot4_ok)
        return 1 if FAILS else 0
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            logf.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())

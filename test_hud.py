"""
JARVIS HUD self-test — launches the overlay, feeds it live-looking data,
verifies Win32 click-through styles, and captures screenshots.

    python test_hud.py

Artifacts: hud_preview.png (widget render), hud_on_desktop.png (actual screen).
Exit code 0 = pass.
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from brain import load_config
    from overlay import (HID_TOGGLE_CLICK, HudBridge, HudWindow, HotkeyFilter,
                         register_hotkeys, unregister_hotkeys)

    app = QApplication(sys.argv)
    cfg = load_config()
    bridge = HudBridge()
    hud = HudWindow(bridge, cfg)
    hfilter = HotkeyFilter(bridge)
    app.installNativeEventFilter(hfilter)

    hotkeys_ok = register_hotkeys()
    check("global hotkeys registered", hotkeys_ok,
          "Ctrl+Alt+J / I / Space" if hotkeys_ok else "a combo was already taken")

    hud.show()

    # ---- simulated live activity -----------------------------------------
    bridge.status.emit("researching")
    bridge.exchange.emit("you", "Run diagnostics on my system, Jarvis.")
    bridge.exchange.emit(
        "jarvis",
        "Diagnostics complete, sir. CPU at 23 percent, memory 61 percent used, "
        "GPU at 50 degrees, all systems nominal.")
    bridge.exchange.emit("system", "⚡ run_diagnostics({})")
    bridge.gauges.emit({"cpu": 23.4, "mem": 61.2, "net_rx": 1_350_000,
                        "net_tx": 260_000, "battery": 84.0, "charging": True})
    bridge.presence.emit("● in view")
    bridge.toast.emit("Reminder: stand up and stretch, sir")

    level_phase = {"t": 0.0}

    def feed_level():
        level_phase["t"] += 0.12
        bridge.level.emit(min(1.0, abs(math.sin(level_phase["t"] * 2.4)) * 0.7), "mic")

    lvl_timer = QTimer()
    lvl_timer.setInterval(50)
    lvl_timer.timeout.connect(feed_level)
    lvl_timer.start()

    # ---- click-through verification ---------------------------------------
    def verify_clickthrough():
        try:
            import win32con, win32gui
            hwnd = int(hud.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            layered = bool(style & win32con.WS_EX_LAYERED)
            transparent = bool(style & win32con.WS_EX_TRANSPARENT)
            check("layered + click-through applied", layered and transparent,
                  f"exstyle=0x{style:08X}")
            hud.toggle_click_through()
            style2 = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            check("interactive toggle clears WS_EX_TRANSPARENT",
                  not (style2 & win32con.WS_EX_TRANSPARENT),
                  f"exstyle=0x{style2:08X}")
            hud.toggle_click_through()   # back to default
        except Exception as e:
            check("layered + click-through applied", False, repr(e))

    def capture():
        verify_clickthrough()
        try:
            pix = hud.grab()
            ok = pix.save("hud_preview.png")
            check("widget render captured", ok and pix.width() > 100,
                  f"{pix.width()}x{pix.height()} -> hud_preview.png")
        except Exception as e:
            check("widget render captured", False, repr(e))
        try:
            import pyautogui
            geo = hud.frameGeometry()
            shot = pyautogui.screenshot(region=(geo.x(), geo.y(),
                                                 geo.width(), geo.height()))
            shot.save("hud_on_desktop.png")
            # sanity: the capture should not be a single flat colour
            import numpy as np
            arr = np.asarray(shot)
            check("on-screen capture has content",
                  arr.std() > 8.0, f"std={arr.std():.1f} -> hud_on_desktop.png")
        except Exception as e:
            check("on-screen capture has content", False, repr(e))
        lvl_timer.stop()
        app.quit()

    QTimer.singleShot(2200, capture)
    app.exec()
    hud.hide()
    unregister_hotkeys()

    print("=" * 56)
    print(f" hud self-test: {len(FAILS)} failed" + (f": {FAILS}" if FAILS else ""))
    print("=" * 56)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

"""
JARVIS HUD overlay — frameless, translucent, always-on-top holographic panel.

* Click-through by default via Win32 WS_EX_LAYERED|WS_EX_TRANSPARENT, so it
  never blocks the desktop; Ctrl+Alt+I toggles interactivity (drag it around).
* Ctrl+Alt+J shows/hides the whole HUD; Ctrl+Alt+Space starts a dictated turn.
* HudBridge carries thread-safe Qt signals from the audio/brain threads into
  the paint widgets (queued connections — safe by construction).
"""

import ctypes
import ctypes.wintypes
import time

from PyQt6.QtCore import (QAbstractNativeEventFilter, QObject, QPoint, QRectF, Qt,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hud_widgets import AMBER, ArcReactor, CYAN, EyeGlyph, Gauge, Transcript, Waveform

WM_HOTKEY = 0x0312
HID_TOGGLE_VIS = 1
HID_TOGGLE_CLICK = 2
HID_PTT = 3
HID_QUIT = 4
HID_SETTINGS = 5

_STATUS_UI = {
    "idle":         ("Standby", QColor(140, 220, 255), "idle"),
    "listening":    ("Listening…", QColor(120, 255, 180), "listening"),
    "thinking":     ("Thinking…", AMBER, "thinking"),
    "researching":  ("Researching…", AMBER, "thinking"),
    "escalating":   ("Consulting external core…", AMBER, "thinking"),
    "speaking":     ("Speaking…", CYAN, "speaking"),
    "offline":      ("Core offline", QColor(150, 150, 160), "offline"),
}


class HudBridge(QObject):
    """Signal carrier — created on the GUI thread, emitted from anywhere."""
    status = pyqtSignal(str)                 # idle|listening|thinking|researching|speaking|offline
    exchange = pyqtSignal(str, str)          # role: you|jarvis|system, text
    gauges = pyqtSignal(dict)                # cpu/mem/net_rx/net_tx/battery/charging
    level = pyqtSignal(float, str)           # 0..1, "mic" | "spk"
    presence = pyqtSignal(str)               # text for the presence dot
    toast = pyqtSignal(str)                  # temporary amber alert
    cmd_visibility = pyqtSignal()            # hotkey -> toggle HUD
    cmd_clickthrough = pyqtSignal()          # hotkey -> toggle mouse pass-through
    cmd_ptt = pyqtSignal()                   # hotkey -> push-to-talk
    cmd_quit = pyqtSignal()                  # worker thread -> exit the app
    cmd_settings = pyqtSignal()              # hotkey / gear -> settings panel


class HotkeyFilter(QAbstractNativeEventFilter):
    """Receives WM_HOTKEY on the GUI thread and re-emits as Qt signals."""

    def __init__(self, bridge: HudBridge):
        super().__init__()
        self.bridge = bridge

    def nativeEventFilter(self, eventType, message):
        try:
            if bytes(eventType) not in (b"windows_dispatcher_MSG",
                                        b"windows_generic_MSG"):
                return (False, 0)

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.wintypes.HWND),
                    ("message", ctypes.wintypes.UINT),
                    ("wParam", ctypes.wintypes.WPARAM),
                    ("lParam", ctypes.wintypes.LPARAM),
                    ("time", ctypes.wintypes.DWORD),
                    ("pt", ctypes.wintypes.POINT),
                ]

            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if msg.message == WM_HOTKEY:
                wid = int(msg.wParam)
                if wid == HID_TOGGLE_VIS:
                    self.bridge.cmd_visibility.emit()
                elif wid == HID_TOGGLE_CLICK:
                    self.bridge.cmd_clickthrough.emit()
                elif wid == HID_PTT:
                    self.bridge.cmd_ptt.emit()
                elif wid == HID_QUIT:
                    self.bridge.cmd_quit.emit()
                elif wid == HID_SETTINGS:
                    self.bridge.cmd_settings.emit()
                return (True, 0)
        except Exception:
            pass
        return (False, 0)


def register_hotkeys() -> bool:
    """System-wide: Ctrl+Alt+J (HUD), Ctrl+Alt+I (interact), Ctrl+Alt+Space (talk),
    Ctrl+Alt+S (settings), Ctrl+Alt+Q (quit)."""
    user32 = ctypes.windll.user32
    MOD_CONTROL, MOD_ALT, MOD_NOREPEAT = 0x0002, 0x0001, 0x4000
    combos = [
        (HID_TOGGLE_VIS, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("J")),
        (HID_TOGGLE_CLICK, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("I")),
        (HID_PTT, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x20),
        (HID_QUIT, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Q")),
        (HID_SETTINGS, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("S")),
    ]
    ok = True
    for hid, mods, vk in combos:
        if not user32.RegisterHotKey(None, hid, mods, vk):
            ok = False
            print(f"[hud] hotkey id {hid} could not be registered (already in use?)")
    return ok


def unregister_hotkeys() -> None:
    user32 = ctypes.windll.user32
    for hid in (HID_TOGGLE_VIS, HID_TOGGLE_CLICK, HID_PTT, HID_QUIT,
                HID_SETTINGS):
        user32.UnregisterHotKey(None, hid)


class BootOverlay(QWidget):
    """Suit-up theater: staged system checklist on launch, then gone.

    Pure theater — never blocks input (mouse events pass straight through)
    and deletes itself after the last stage.
    """
    STAGES = (("POWER", "arc reactor"),
              ("SENSORS", "presence + screen"),
              ("VOICE", "wake word + whisper"),
              ("NETWORK", "cloud brain"),
              ("ONLINE", "all systems nominal"))

    def __init__(self, parent):
        super().__init__(parent)
        self._stage = -1
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setInterval(420)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._stage += 1
        if self._stage >= len(self.STAGES):
            self._timer.stop()
            self.hide()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(2, 8, 16, 205))
        cx = self.width() / 2
        y0 = self.height() / 2 - 70
        p.setPen(QColor(0, 216, 255, 235))
        p.setFont(QFont("Consolas", 13))
        p.drawText(QRectF(0, y0, self.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, "INITIALIZE J.A.R.V.I.S.")
        p.setFont(QFont("Consolas", 10))
        y = y0 + 42
        for i, (name, desc) in enumerate(self.STAGES):
            if i > self._stage:
                break
            done = i < self._stage
            mark = "✓" if done else "▸"
            col = (QColor(120, 255, 180, 225) if done
                   else QColor(0, 216, 255, 235))
            p.setPen(col)
            p.drawText(QRectF(cx - 140, y, 280, 22),
                       Qt.AlignmentFlag.AlignLeft, f"{mark} {name:8s}  {desc}")
            y += 24
        frac = max(0.0, min(1.0, (self._stage + 1) / len(self.STAGES)))
        bar = QRectF(cx - 140, y + 8, 280, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(bar, 2, 2)
        p.setBrush(QColor(0, 216, 255, 205))
        p.drawRoundedRect(
            QRectF(bar.left(), bar.top(), bar.width() * frac, 4), 2, 2)
        p.end()


class HudWindow(QWidget):
    def __init__(self, bridge: HudBridge, cfg: dict):
        super().__init__(None)
        hcfg = cfg.get("hud", {})
        self.bridge = bridge
        self._click_through = bool(hcfg.get("click_through", True))
        self._corner = hcfg.get("corner", "bottom-right")
        self._show_taskbar = bool(hcfg.get("show_taskbar", False))
        self._drag_offset: QPoint | None = None
        self._last_level = 0.0
        self._last_level_ts = 0.0
        self._level_source = "mic"
        self._toast_until = 0.0
        self._status = "idle"
        self._reassert_at = 0.0

        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint
                 | (Qt.WindowType.Window if self._show_taskbar else Qt.WindowType.Tool))
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedSize(int(hcfg.get("width", 470)), int(hcfg.get("height", 680)))

        self._build()
        self._wire_bridge()
        self._place()

        hz = int(hcfg.get("update_hz", 60))
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(10, int(1000 / hz)))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("J · A · R · V · I · S")
        title.setFont(QFont("Segoe UI", 11))
        title.setStyleSheet("color: rgba(0,216,255,0.95); letter-spacing: 3px;"
                            " background: transparent;")
        self.clock = QLabel("--:--")
        self.clock.setFont(QFont("Consolas", 11))
        self.clock.setStyleSheet("color: rgba(160,225,255,0.85); background: transparent;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.clock)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFont(QFont("Segoe UI", 11))
        self.settings_btn.setFlat(True)
        self.settings_btn.setToolTip("Settings (Ctrl+Alt+S)")
        self.settings_btn.setStyleSheet("color: rgba(160,225,255,0.85);"
                                        " background: transparent; border: none;")
        self.settings_btn.clicked.connect(
            lambda: self.bridge.cmd_settings.emit())
        header.addWidget(self.settings_btn)
        root.addLayout(header)

        self.reactor = ArcReactor()
        root.addWidget(self.reactor, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.status_lbl = QLabel("Standby")
        self.status_lbl.setFont(QFont("Segoe UI", 11))
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: rgba(140,220,255,0.95); background: transparent;")
        root.addWidget(self.status_lbl)

        self.wave = Waveform()
        root.addWidget(self.wave)

        self.transcript = Transcript()
        root.addWidget(self.transcript, stretch=1)

        self.toast_lbl = QLabel("")
        self.toast_lbl.setFont(QFont("Segoe UI", 9))
        self.toast_lbl.setStyleSheet("color: rgba(255,190,60,0.95); background: transparent;")
        self.toast_lbl.setVisible(False)
        self.toast_lbl.setWordWrap(True)
        root.addWidget(self.toast_lbl)

        self.g_cpu = Gauge("CPU")
        self.g_mem = Gauge("MEM")
        self.g_net = Gauge("NET", color=QColor(120, 255, 180))
        self.g_bat = Gauge("BAT", color=AMBER)
        for g in (self.g_cpu, self.g_mem, self.g_net, self.g_bat):
            root.addWidget(g)

        footer = QHBoxLayout()
        self.presence_lbl = QLabel("◌ sensor off")
        self.presence_lbl.setFont(QFont("Segoe UI", 8))
        self.presence_lbl.setStyleSheet("color: rgba(150,210,235,0.75); background: transparent;")
        self.model_lbl = QLabel("local core")
        self.model_lbl.setFont(QFont("Segoe UI", 8))
        self.model_lbl.setStyleSheet("color: rgba(150,210,235,0.55); background: transparent;")
        self.eye = EyeGlyph()
        self.eye.set_watching(bool(cfg.get("screen_watcher", {}).get("enabled", False)))
        footer.addWidget(self.presence_lbl)
        footer.addStretch(1)
        footer.addWidget(self.eye)
        footer.addWidget(self.model_lbl)
        root.addLayout(footer)
        self._update_clock()

        # suit-up sequence on top of everything (deletes itself when done)
        self._boot = BootOverlay(self)
        self._boot.setGeometry(self.rect())
        self._boot.raise_()
        self._boot.show()

    def _wire_bridge(self) -> None:
        self.bridge.status.connect(self.set_status)
        self.bridge.exchange.connect(self.transcript.add_exchange)
        self.bridge.gauges.connect(self._on_gauges)
        self.bridge.level.connect(self._on_level)
        self.bridge.presence.connect(self.presence_lbl.setText)
        self.bridge.toast.connect(self._on_toast)

    # ---------------------------------------------------------------- placement
    def _place(self) -> None:
        from PyQt6.QtGui import QGuiApplication
        screen = self.screen()
        if screen is None and self.windowHandle() is not None:
            screen = self.windowHandle().screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        margin = 12
        if self._corner in ("bottom-right", "top-right"):
            x = geo.right() - w - margin
        else:
            x = geo.left() + margin
        if self._corner in ("bottom-right", "bottom-left"):
            y = geo.bottom() - h - margin
        else:
            y = geo.top() + margin
        self.move(x, y)

    # ----------------------------------------------------------------- states
    def set_status(self, status: str) -> None:
        text, color, arc = _STATUS_UI.get(status, _STATUS_UI["idle"])
        self._status = status
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            f"color: rgba({color.red()},{color.green()},{color.blue()},0.98); background: transparent;")
        self.reactor.set_state(arc)

    def _on_gauges(self, d: dict) -> None:
        if d.get("cpu") is not None:
            self.g_cpu.set_value(d["cpu"], f"{d['cpu']:.0f}%")
        if d.get("mem") is not None:
            self.g_mem.set_value(d["mem"], f"{d['mem']:.0f}%")
        rx = d.get("net_rx") or 0.0
        tx = d.get("net_tx") or 0.0
        total = rx + tx
        self.g_net.set_value(min(100.0, total / 5e6 * 100.0),
                             f"↓{_fmt_rate(rx)} ↑{_fmt_rate(tx)}")
        bat = d.get("battery")
        if bat is not None:
            suffix = " AC" if d.get("charging") else " DC"
            self.g_bat.set_value(bat, f"{bat:.0f}%{suffix}")
        else:
            self.g_bat.set_value(0, "mains")

    def _on_level(self, value: float, source: str) -> None:
        self._last_level = max(0.0, min(1.0, value))
        self._last_level_ts = time.monotonic()
        self._level_source = source

    def _on_toast(self, text: str) -> None:
        self.toast_lbl.setText("⏱ " + text)
        self.toast_lbl.setVisible(True)
        self._toast_until = time.monotonic() + 8

    # ------------------------------------------------------------------- frame
    def _tick(self) -> None:
        now = time.monotonic()
        live = self._last_level if (now - self._last_level_ts) < 0.3 else 0.0
        self.wave.push(live)
        if self._status == "speaking":
            self.reactor.set_level(live)
        else:
            self.reactor.set_level(0.0)
        if self._toast_until and now > self._toast_until:
            self.toast_lbl.setVisible(False)
            self._toast_until = 0.0
        # keep the panel above apps that steal topmost (cheap, every ~4 s)
        if self.isVisible() and now > self._reassert_at:
            self._reassert_at = now + 4.0
            self._ensure_topmost()
        self.update()

    def _ensure_topmost(self) -> None:
        try:
            import win32con, win32gui
            hwnd = int(self.winId())
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _update_clock(self) -> None:
        self.clock.setText(time.strftime("%H:%M:%S"))

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(4, 4, -4, -4)
        # outer holographic glow
        for pad, alpha in ((10, 14), (6, 26)):
            glow = QRectF(rect).adjusted(-pad, -pad, pad, pad)
            col = QColor(0, 216, 255, alpha)
            p.setPen(QPen(col, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(glow, 22, 22)
        # panel body
        body = QRectF(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(3, 13, 23, 205))
        p.drawRoundedRect(body, 18, 18)
        # crisp border
        p.setPen(QPen(QColor(0, 216, 255, 120), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 18, 18)
        # header accent
        p.setPen(QPen(QColor(0, 216, 255, 70), 2.0))
        p.drawLine(int(body.left() + 18), int(body.top() + 34),
                   int(body.right() - 18), int(body.top() + 34))
        # scanlines — the hologram pass (1px lines, ~6% black)
        p.setPen(QPen(QColor(0, 0, 0, 16), 1.0))
        ww, hh = self.width(), self.height()
        for yy in range(8, hh - 8, 3):
            p.drawLine(8, yy, ww - 8, yy)
        # vignette — darken the corners
        vg = QRadialGradient(QPointF(ww / 2, hh / 2), max(ww, hh) * 0.62)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 110))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(vg)
        p.drawRoundedRect(QRectF(rect), 18, 18)
        # corner brackets — the sci-fi HUD grammar
        bl = 26.0
        p.setPen(QPen(QColor(0, 216, 255, 170), 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(rect)
        for x, y, dx, dy in ((r.left(), r.top(), 1, 1),
                             (r.right(), r.top(), -1, 1),
                             (r.left(), r.bottom(), 1, -1),
                             (r.right(), r.bottom(), -1, -1)):
            bracket = QPainterPath()
            bracket.moveTo(x + dx * bl, y)
            bracket.lineTo(x, y)
            bracket.lineTo(x, y + dy * bl)
            p.drawPath(bracket)
        p.end()

    # ------------------------------------------------------------------ input
    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self._apply_click_through()

    def toggle_click_through(self) -> None:
        self._click_through = not self._click_through
        self._apply_click_through()
        mode = "mouse pass-through ON — Ctrl+Alt+I to interact" if self._click_through \
            else "interactive — drag me, Ctrl+Alt+I to pass through"
        self.bridge.exchange.emit("system", f"HUD {mode}")

    def apply_config(self, cfg: dict) -> None:
        """Live-apply HUD settings from the settings panel (no restart)."""
        hcfg = cfg.get("hud", {})
        self._corner = hcfg.get("corner", self._corner)
        self.setFixedSize(int(hcfg.get("width", self.width())),
                          int(hcfg.get("height", self.height())))
        self._click_through = bool(hcfg.get("click_through", self._click_through))
        self._apply_click_through()
        self._place()
        if hasattr(self, "eye"):
            self.eye.set_watching(
                bool(cfg.get("screen_watcher", {}).get("enabled", False)))

    def _apply_click_through(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          self._click_through)
        try:
            import win32con, win32gui
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
            if self._click_through:
                style |= win32con.WS_EX_TRANSPARENT
            else:
                style &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
            win32gui.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED,
            )
        except Exception as e:
            print(f"[hud] click-through toggle failed: {e}")

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(120, self._apply_click_through)
        self.raise_()

    def mousePressEvent(self, ev):
        if not self._click_through and ev.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag_offset is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_offset)
            ev.accept()

    def mouseReleaseEvent(self, _ev):
        self._drag_offset = None


def _fmt_rate(bps: float) -> str:
    if bps >= 1e6:
        return f"{bps / 1e6:.1f}M"
    if bps >= 1e3:
        return f"{bps / 1e3:.0f}K"
    return f"{bps:.0f}B"

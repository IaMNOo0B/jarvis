"""
JARVIS HUD widgets — pure-painting components.

Everything here is flicker-friendly: continuous QTimer-driven update(),
elapsed-time animation (never assumes exact frame timing), and layered
translucent strokes for the holographic glow instead of expensive effects.
"""

import math
import time
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

CYAN = QColor(0, 216, 255)
CYAN_DIM = QColor(0, 150, 190)
WHITE = QColor(235, 250, 255)
AMBER = QColor(255, 190, 60)

_STATE_STYLE = {
    "offline":    (QColor(120, 130, 140), 0.3, 12.0),
    "idle":       (CYAN, 0.55, 18.0),
    "listening":  (QColor(120, 255, 180), 0.9, 34.0),
    "thinking":   (QColor(255, 210, 90), 1.0, 90.0),
    "speaking":   (CYAN, 1.0, 46.0),
}


class ArcReactor(QWidget):
    """The holographic core: copper coil ring, counter-rotating tick ring,
    and a voice-reactive sin-wave ring around a pulsing reactor heart.

    Own 30fps timer — a parent's update() never reaches children in Qt, so
    the rings were static until this timer existed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._level = 0.0
        self._t0 = time.monotonic()
        self.setFixedHeight(232)
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps
        self._timer.timeout.connect(self._on_frame)
        self._timer.start()

    def _on_frame(self) -> None:
        if self.isVisible():
            self.update()

    def set_state(self, state: str) -> None:
        if state in _STATE_STYLE:
            self._state = state
            self.update()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def sizeHint(self) -> QSize:
        return QSize(240, 232)

    def paintEvent(self, _ev):
        try:
            self._paint_reactor()
        except Exception as e:  # a paint bug must never take the app down
            if not getattr(self, "_paint_warned", False):
                print(f"[hud] reactor paint error: {e!r}")
                self._paint_warned = True

    def _paint_reactor(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = time.monotonic() - self._t0
        base, intensity, speed = _STATE_STYLE.get(self._state, _STATE_STYLE["idle"])

        cx = self.width() / 2
        cy = self.height() / 2
        beat = 0.5 + 0.5 * math.sin(t * speed / 18.0)
        if self._state == "speaking":
            beat = max(beat * 0.6, min(1.0, self._level * 4.0))

        def glow_arc(radius: QRectF, start_deg: float, span_deg: float,
                     width: float, alpha_mul: float = 1.0, cap=Qt.PenCapStyle.RoundCap):
            """Layered translucent strokes -> holographic glow, no effects."""
            col = QColor(base)
            for extra, a in ((9, 0.10), (5, 0.18), (2, 0.35), (0, 0.95)):
                col.setAlphaF(min(1.0, a * intensity * alpha_mul * (0.75 + 0.25 * beat)))
                pen = QPen(col, width + extra)
                pen.setCapStyle(cap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(radius, int(start_deg * 16), int(span_deg * 16))

        # --- outer segmented ring (three windows, slow clockwise) -----------
        rot1 = (t * speed * 0.6) % 360
        r1 = QRectF(cx - 84, cy - 84, 168, 168)
        for i in range(3):
            glow_arc(r1, rot1 + i * 120, 74, 3.2)

        # --- middle ring (counter-rotating, two long arcs) -----------------
        rot2 = (-t * speed * 1.1) % 360
        r2 = QRectF(cx - 64, cy - 64, 128, 128)
        glow_arc(r2, rot2, 150, 4.0, 0.9)
        glow_arc(r2, rot2 + 180, 150, 4.0, 0.9)

        # --- inner ring (fast, single gap) ---------------------------------
        rot3 = (t * speed * 2.0) % 360
        r3 = QRectF(cx - 46, cy - 46, 92, 92)
        glow_arc(r3, rot3, 300, 3.0, 1.0)

        # --- static hairline ------------------------------------------------
        rh = QRectF(cx - 55, cy - 55, 110, 110)
        col = QColor(base)
        col.setAlphaF(0.28 * intensity)
        p.setPen(QPen(col, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rh)

        # --- coil ring: 10 copper trapezoids, slow rotation -----------------
        p.save()
        p.translate(cx, cy)
        p.rotate((t * speed * 0.35) % 360)
        for i in range(10):
            p.save()
            p.rotate(i * 36.0)
            coil = QPainterPath()
            coil.moveTo(68, -4.5)
            coil.lineTo(80, -7.5)
            coil.lineTo(80, 7.5)
            coil.lineTo(68, 4.5)
            coil.closeSubpath()
            copper = QColor(198, 134, 62)
            copper.setAlphaF(0.8 * intensity)
            edge = QColor(base)
            edge.setAlphaF(0.55 * intensity)
            p.setPen(QPen(edge, 1.0))
            p.setBrush(copper)
            p.drawPath(coil)
            p.restore()
        p.restore()

        # --- tick ring: dashed, counter-rotating ---------------------------
        p.save()
        p.translate(cx, cy)
        p.rotate((-t * speed * 0.8) % 360)
        tick_col = QColor(base)
        tick_col.setAlphaF(0.45 * intensity)
        tick_pen = QPen(tick_col, 2.0)
        tick_pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(tick_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 94, 94)
        p.restore()

        # --- voice ring: sin-wave EQ circle --------------------------------
        # layered drifting sines (the VisualizadorAudio trick, circularised);
        # dances with the voice while speaking, breathes when idle.
        n_pts = 64
        if self._state == "speaking":
            amp = 2.0 + 10.0 * self._level
        elif self._state == "listening":
            amp = 5.0
        else:
            amp = 2.2 * (0.6 + 0.4 * math.sin(t * 1.4))
        pts = []
        for i in range(n_pts + 1):
            a = 2 * math.pi * i / n_pts
            wave = (math.sin(a * 3 + t * 4.0) * 0.5
                    + math.sin(a * 7 - t * 6.3) * 0.3
                    + math.sin(a * 13 + t * 9.1) * 0.2)
            r = 102 + wave * amp
            pts.append(QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r))
        vpath = QPainterPath()
        vpath.moveTo(pts[0])
        for pt in pts[1:]:
            vpath.lineTo(pt)
        for extra, va in ((5, 0.10), (2, 0.22), (0, 0.75)):
            vcol = QColor(base)
            vcol.setAlphaF(min(1.0, va * intensity))
            vpen = QPen(vcol, 1.6 + extra)
            vpen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(vpen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(vpath)

        # --- core: layered radial glow --------------------------------------
        core_r = 20 + 7 * beat + (6 * self._level if self._state == "speaking" else 0)
        grad = QRadialGradient(QPointF(cx, cy), core_r + 16)
        hot = QColor(WHITE)
        hot.setAlphaF(0.95 * intensity)
        mid = QColor(base)
        mid.setAlphaF(0.55 * intensity)
        edge = QColor(base).darker(220)
        edge.setAlphaF(0.0)
        grad.setColorAt(0.0, hot)
        grad.setColorAt(0.45, mid)
        grad.setColorAt(1.0, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(cx, cy), core_r + 16, core_r + 16)
        inner = QColor(WHITE)
        inner.setAlphaF(min(1.0, 0.5 + 0.5 * beat))
        p.setBrush(inner)
        p.drawEllipse(QPointF(cx, cy), 6, 6)
        p.end()


class EyeGlyph(QWidget):
    """Privacy eye — glows cyan while the screen-watcher is reading the
    screen, dim otherwise. Trust-building UI for the watching-eyes feature."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watching = False
        self.setFixedSize(30, 20)
        self.setToolTip("Lights up while JARVIS is watching the screen")

    def set_watching(self, watching: bool) -> None:
        self._watching = bool(watching)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        active = self._watching
        # almond outline
        col = QColor(CYAN if active else (90, 120, 140))
        col.setAlphaF(0.95 if active else 0.45)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        eye = QPainterPath()
        eye.moveTo(3, cy)
        eye.quadTo(cx, 1, w - 3, cy)
        eye.quadTo(cx, h - 1, 3, cy)
        p.drawPath(eye)
        # pupil
        p.setPen(Qt.PenStyle.NoPen)
        pcol = QColor(CYAN if active else (70, 100, 120))
        pcol.setAlphaF(1.0 if active else 0.5)
        p.setBrush(pcol)
        p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
        # halo when watching
        if active:
            halo = QColor(CYAN)
            halo.setAlphaF(0.16)
            p.setBrush(halo)
            p.drawEllipse(QPointF(cx, cy), 7.5, 7.5)
        p.end()


class Waveform(QWidget):
    """Rolling level bars — mic while listening, speakers while talking."""

    def __init__(self, parent=None, bars: int = 46):
        super().__init__(parent)
        self.bars = bars
        self._levels = deque([0.0] * bars, maxlen=bars)
        self.setFixedHeight(54)

    def push(self, level: float) -> None:
        self._levels.append(max(0.0, min(1.0, level)))
        if self.isVisible():
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        h = self.height()
        n = len(self._levels)
        gap = 3
        bw = max(3.0, (w - gap * (n - 1)) / n)
        x = 0.0
        for i, lv in enumerate(self._levels):
            # centre-out envelope: index distance from newest decides floor
            bh = max(3.0, lv * (h - 6))
            top = (h - bh) / 2
            col = QColor(CYAN)
            col.setAlphaF(min(1.0, 0.25 + lv * 2.2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, top, bw, bh), 1.5, 1.5)
            x += bw + gap
        p.end()


class Gauge(QWidget):
    """Horizontal labelled meter (CPU / MEM / NET / BAT)."""

    def __init__(self, label: str, parent=None, color=CYAN):
        super().__init__(parent)
        self.label = label
        self.value = 0.0          # 0..100 (or arbitrary normalised)
        self.text = "–"
        self.color = color
        self._flash_until = 0.0
        self.setFixedHeight(22)

    def set_value(self, value: float, text: str | None = None) -> None:
        self.value = max(0.0, min(100.0, value))
        if text is not None:
            self.text = text
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = self.height()
        w = self.width()
        font = QFont("Consolas", 9)
        p.setFont(font)
        p.setPen(QColor(150, 210, 235))
        p.drawText(QRectF(0, 0, 44, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.label)
        track_x, track_w = 48.0, w - 48 - 58
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(track_x, h / 2 - 4, track_w, 8), 4, 4)
        col = QColor(self.color)
        col.setAlphaF(0.9)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(track_x, h / 2 - 4, max(6.0, track_w * self.value / 100.0), 8), 4, 4)
        p.setPen(QColor(210, 240, 255))
        p.drawText(QRectF(track_x + track_w + 6, 0, 52, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.text)
        p.end()


class Transcript(QPlainTextEdit):
    """Scrolling conversation log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(80)
        self.setUndoRedoEnabled(False)
        self.setStyleSheet(
            "QPlainTextEdit { background: rgba(0, 20, 34, 0.55);"
            " border: 1px solid rgba(0, 216, 255, 0.22); border-radius: 10px;"
            " color: #bfeaff; font-family: 'Segoe UI'; font-size: 10.5pt;"
            " padding: 6px; selection-background-color: rgba(0,216,255,0.3); }"
        )
        self.viewport().setAutoFillBackground(False)

    def add_exchange(self, role: str, text: str) -> None:
        text = " ".join((text or "").split())
        if not text:
            return
        if role == "you":
            self.appendPlainText(f"▸ {text}")
        elif role == "jarvis":
            self.appendPlainText(f"JARVIS: {text}")
        else:  # system notes (tool activity, alerts)
            self.appendPlainText(f"  · {text}")
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

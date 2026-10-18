"""
JARVIS desktop launcher — generates jarvis.ico and a Desktop shortcut.

    ensure_desktop_shortcut()   # idempotent; no-op off Windows

Creates:
  * AI_Model/jarvis.ico          — arc-reactor icon rendered with Qt
  * <Desktop>/JARVIS.lnk         — launches `pythonw jarvis_app.py` with the
    project folder as its working directory

Called automatically at startup (routines.create_desktop_icon) and by
setup_models.py, so the icon appears on first run without extra steps.
The .ico is assembled manually from PNG frames (16-256px) so every Windows
size renders crisply.
"""

import os
import struct
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE, "jarvis.ico")
LNK_NAME = "JARVIS.lnk"
ICON_SIZES = (16, 32, 48, 64, 256)


# ------------------------------------------------------------------- icon art
def _render_png(size: int) -> bytes:
    """Render the arc-reactor icon at one size and return PNG bytes.

    Uses QImage, NOT QPixmap: this runs on a worker thread at app startup and
    Qt only allows GUI-bound Pixmaps on the main thread (QImage is safe).
    """
    from PyQt6.QtCore import QBuffer, QIODevice, QRect, QRectF, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:                      # setup runs before the HUD exists
        app = QApplication([sys.argv[0] if sys.argv else "jarvis"])

    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    m = max(1, size // 16)               # padding so nothing is clipped
    s = size - 2 * m

    # dark rounded-square base
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(5, 16, 28, 245))
    p.drawRoundedRect(QRectF(m, m, s, s), s * 0.20, s * 0.20)

    def ring(inset: float, width: float, color, spans):
        area = QRect(int(m + inset), int(m + inset),
                     int(s - 2 * inset), int(s - 2 * inset))
        pen = QPen(QColor(*color))
        pen.setWidthF(max(1.0, width * s / 128))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for start, span in spans:
            p.drawArc(area, int(start * 16), int(span * 16))

    # segmented outer ring — the movie reactor silhouette
    ring(s * 0.05, 7, (0, 216, 255, 255), [(0, 80), (120, 80), (240, 80)])
    # offset middle ring
    ring(s * 0.19, 6, (0, 216, 255, 200), [(50, 125), (230, 125)])
    # inner track
    ring(s * 0.31, 3, (0, 150, 190, 255), [(0, 360)])

    # glowing core
    core = s * 0.155
    cx = m + s / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 216, 255, 90))
    p.drawEllipse(QRectF(cx - core * 1.45, cx - core * 1.45,
                         core * 2.9, core * 2.9))
    p.setBrush(QColor(140, 245, 255, 255))
    p.drawEllipse(QRectF(cx - core, cx - core, core * 2, core * 2))
    p.setBrush(QColor(255, 255, 255, 255))
    inner = core * 0.40
    p.drawEllipse(QRectF(cx - inner, cx - inner, inner * 2, inner * 2))
    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _write_ico(path: str, pngs: dict) -> None:
    """Assemble a multi-size .ico from PNG payloads (PNG-in-ICO, Vista+)."""
    items = sorted(pngs.items())
    header = struct.pack("<HHH", 0, 1, len(items))
    offset = 6 + 16 * len(items)
    entries = b""
    data = b""
    for size, png in items:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(png), offset)
        data += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + data)


def ensure_icon(path: str = ICON_PATH) -> str:
    """Render jarvis.ico if missing. Returns the icon path."""
    if os.path.isfile(path):
        return path
    pngs = {s: _render_png(s) for s in ICON_SIZES}
    _write_ico(path, pngs)
    return path


# ------------------------------------------------------------------ shortcut
def ensure_desktop_shortcut() -> str | None:
    """Create <Desktop>/JARVIS.lnk if it does not exist. Idempotent."""
    if not sys.platform.startswith("win"):
        return None
    try:
        icon = ensure_icon()
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = shell.SpecialFolders("Desktop")   # follows OneDrive redirect
        lnk = os.path.join(desktop, LNK_NAME)
        if os.path.isfile(lnk):
            return lnk                                # already installed
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        launcher = pythonw if os.path.isfile(pythonw) else sys.executable
        shortcut = shell.CreateShortCut(lnk)
        shortcut.Targetpath = launcher
        shortcut.Arguments = f'"{os.path.join(BASE, "jarvis_app.py")}"'
        shortcut.WorkingDirectory = BASE
        shortcut.IconLocation = f"{icon},0"
        shortcut.Description = "JARVIS — Just A Rather Very Intelligent System"
        shortcut.save()
        return lnk
    except Exception as e:
        print(f"[shortcut] desktop icon not created: {e}")
        return None


if __name__ == "__main__":
    print(ensure_icon())
    print(ensure_desktop_shortcut() or "(not Windows — shortcut skipped)")

"""Headless HUD lifecycle smoke test.

Runs the REAL HudWindow.__init__ -> _build -> _wire_bridge -> _place plus
apply_config / toggle_visible / toggle_click_through against permissive Qt
stubs. Catches NameErrors and wiring bugs (like the 'cfg' startup crash)
without a display or Windows. Run:  python test_hud_headless.py
"""
import sys
import types
from unittest.mock import MagicMock

sys.modules['ctypes.wintypes'] = types.ModuleType('ctypes.wintypes')


class _Sig:
    def connect(self, *a):
        pass

    def emit(self, *a):
        pass


class _FakeGeo:
    def right(self):
        return 1920

    def bottom(self):
        return 1080

    def left(self):
        return 0

    def top(self):
        return 0


class _FakeScreen:
    def availableGeometry(self):
        return _FakeGeo()


class _AnyWidget:
    """Permissive stub: any method call is a safe no-op returning a widget."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name in ('timeout', 'clicked'):
            return _Sig()
        return lambda *a, **k: _AnyWidget()

    def rect(self):
        return MagicMock()

    def isVisible(self):
        return True

    def width(self):
        return 470

    def height(self):
        return 680

    def screen(self):
        return None

    def windowHandle(self):
        return None

    def winId(self):
        return 0

    def move(self, *a):
        pass


class _QtModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cls = type(name, (_AnyWidget,), {})
        setattr(self, name, cls)
        return cls


class _Flag:
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return 1


class _Qt:
    WindowType = _Flag()
    WidgetAttribute = _Flag()
    GlobalColor = _Flag()
    PenStyle = _Flag()
    AlignmentFlag = _Flag()
    ActivationReason = _Flag()
    TimerType = _Flag()


for _mod in ('PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets'):
    _m = _QtModule(_mod)
    sys.modules[_mod] = _m
sys.modules['PyQt6'] = types.ModuleType('PyQt6')
sys.modules['PyQt6.QtCore'].Qt = _Qt
sys.modules['PyQt6.QtCore'].pyqtSignal = lambda *a: _Sig()
sys.modules['PyQt6.QtGui'].QGuiApplication.primaryScreen = staticmethod(
    _FakeScreen)


class FakeBridge:
    def __init__(self):
        for s in ('status', 'exchange', 'gauges', 'level', 'presence', 'toast',
                  'cmd_visibility', 'cmd_clickthrough', 'cmd_ptt', 'cmd_quit',
                  'cmd_settings'):
            setattr(self, s, _Sig())


def main() -> int:
    import overlay
    cfg = {"hud": {"width": 470, "height": 680, "corner": "bottom-right",
                   "click_through": True, "show_taskbar": False},
           "screen_watcher": {"enabled": False}}
    w = overlay.HudWindow(FakeBridge(), cfg)
    print("[PASS] HudWindow.__init__")
    w.apply_config({"hud": {"width": 500, "height": 700},
                    "screen_watcher": {"enabled": True}})
    print("[PASS] apply_config")
    w.toggle_visible()
    print("[PASS] toggle_visible")
    w.toggle_click_through()
    print("[PASS] toggle_click_through")
    print("ALL HUD LIFECYCLE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

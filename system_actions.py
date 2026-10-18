"""
JARVIS system_control layer — the hands on this Windows PC.

Every function returns a short string meant to be shown to the model (and
condensed into one spoken confirmation line). Unknown names return None from
dispatch() so the caller can report "unknown tool" instead of crashing.

Destructive actions (shutdown/restart/logoff/lock/sleep/kill) use a two-phase
confirmation: first call stores the intent and returns CONFIRM_REQUIRED; when
sir agrees and the model calls again within the window, it executes.
"""

import ctypes
import os
import shutil
import subprocess
import time

from diagnostics import diagnostics

# --------------------------------------------------------------------------
# module-level service handles — jarvis_app wires these in when running the
# full app; text mode leaves them None and tools degrade gracefully.
# --------------------------------------------------------------------------
SCHEDULER = None   # scheduler.Scheduler instance
PRESENCE = None    # presence.Presence instance

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCREENSHOT_DIR = os.path.join(PROJECT_ROOT, "JARVIS_screenshots")

CONFIRM_WINDOW = 180  # seconds a pending destructive intent stays valid
_pending = {"action": None, "value": None, "ts": 0.0}

DESTRUCTIVE = {"shutdown", "restart", "logoff", "lock", "sleep", "kill_process"}

# Friendly app name -> launch target
_APP_MAP = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "vscode": "code.exe",
    "visual studio code": "code.exe",
    "spotify": "spotify.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "paint": "mspaint.exe",
}


# --------------------------------------------------------------------- utils
def _run(cmd: list, timeout: int = 15) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _powershell(script: str, timeout: int = 15) -> tuple[int, str]:
    rc, out, err = _run(["powershell", "-NoProfile", "-Command", script], timeout)
    return rc, out or err


def _start_menu_hit(name: str) -> str | None:
    """Last-resort: search Start-menu shortcuts for 'name'."""
    roots = [
        os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    ]
    needle = name.lower().replace(" ", "")
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                stem = os.path.splitext(f)[0].lower().replace(" ", "")
                if needle in stem:
                    return os.path.join(dirpath, f)
    return None


# -------------------------------------------------------------------- volume
def _volume_interface():
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    # pycaw >= 2025 exposes the endpoint directly
    if hasattr(dev, "EndpointVolume"):
        return dev.EndpointVolume
    # legacy pycaw: activate the interface manually
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))


def _volume_get() -> float:
    return _volume_interface().GetMasterVolumeLevelScalar()


def _volume_set01(v: float) -> None:
    _volume_interface().SetMasterVolumeLevelScalar(max(0.0, min(1.0, v)), None)


# ------------------------------------------------------------------- actions
def _system_control(action: str, value: str = "", services: dict | None = None) -> str:
    action = (action or "").lower().strip()

    if action == "volume_get":
        return f"Volume is at {round(_volume_get() * 100)} percent."
    if action == "volume_set":
        pct = float(str(value).replace("%", "").strip())
        _volume_set01(pct / 100.0)
        return f"Volume set to {round(pct)} percent."
    if action == "volume_up":
        _volume_set01(_volume_get() + 0.10)
        return f"Volume at {round(_volume_get() * 100)} percent."
    if action == "volume_down":
        _volume_set01(_volume_get() - 0.10)
        return f"Volume at {round(_volume_get() * 100)} percent."
    if action == "mute":
        _volume_interface().SetMute(1, None)
        return "Muted, sir."
    if action == "unmute":
        _volume_interface().SetMute(0, None)
        return "Unmuted."
    if action == "is_muted":
        return "Muted." if _volume_interface().GetMute() else "Not muted."

    if action == "brightness_set":
        pct = int(float(str(value).replace("%", "").strip()))
        rc, out = _powershell(
            "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{max(0, min(100, pct))}) | Out-Null; 'ok'"
        )
        if rc != 0:
            return f"Brightness control unavailable on this display: {out}"
        return f"Brightness set to {max(0, min(100, pct))} percent."
    if action == "brightness_get":
        rc, out = _powershell("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness")
        return f"Brightness is at {out} percent." if rc == 0 else "Brightness status unavailable."

    if action == "open_app":
        target = str(value).strip()
        key = target.lower()
        exe = _APP_MAP.get(key)
        if exe:
            os.startfile(exe)
            return f"Opened {target}."
        if os.path.isfile(target):
            os.startfile(target)
            return f"Opened {target}."
        try:
            os.startfile(target)          # URLs, associations, plain names
            return f"Opened {target}."
        except OSError:
            pass
        hit = _start_menu_hit(target)
        if hit:
            os.startfile(hit)
            return f"Opened {target} from the Start menu."
        which = shutil.which(target) or shutil.which(target + ".exe")
        if which:
            subprocess.Popen([which], shell=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return f"Launched {target}."
        return f"Could not find an application named '{target}' on this system."

    if action == "close_app":
        target = str(value).strip().lower()
        exe = _APP_MAP.get(target, target)
        if not exe.endswith(".exe"):
            exe += ".exe"
        rc, _o, err = _run(["taskkill", "/IM", exe, "/F"])
        return f"Closed {exe}." if rc == 0 else f"Could not close {exe}: {err or 'not running'}."

    if action == "open_url":
        os.startfile(str(value).strip())
        return f"Opened {value} in your default browser."
    if action == "open_path":
        os.startfile(os.path.abspath(str(value)))
        return f"Opened {value}."

    if action == "screenshot":
        import pyautogui
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SCREENSHOT_DIR, f"shot_{stamp}.png")
        pyautogui.screenshot(path)
        return f"Screenshot saved to {path}."

    if action == "clipboard_get":
        rc, out = _powershell("Get-Clipboard")
        return f"Clipboard: {out[:1500]}" if rc == 0 else "Clipboard is empty or unavailable."
    if action == "clipboard_set":
        # -Value with a single arg via stdin avoids quoting hell
        p = subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                           input=str(value), capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "Copied to clipboard." if p.returncode == 0 else "Clipboard write failed."

    if action == "type_text":
        import pyautogui
        _powershell(f"Set-Clipboard -Value '{str(value).replace(chr(39), '')[:4000]}'")
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        return "Typed into the active window."
    if action == "hotkey":
        import pyautogui
        keys = [k.strip().lower() for k in str(value).split("+") if k.strip()]
        if keys:
            pyautogui.hotkey(*keys)
            return f"Pressed {'+'.join(keys)}."
        return "No keys supplied."
    if action == "press":
        import pyautogui
        pyautogui.press(str(value).strip().lower())
        return f"Pressed {value}."
    if action == "mouse_move":
        import pyautogui
        x, y = (int(n) for n in str(value).split(",")[:2])
        pyautogui.moveTo(x, y, duration=0.2)
        return f"Cursor moved to {x},{y}."

    if action == "kill_process":
        target = str(value).strip().lower()
        exe = _APP_MAP.get(target, target)
        if not exe.endswith(".exe"):
            exe += ".exe"
        rc, _o, err = _run(["taskkill", "/IM", exe, "/F"])
        return f"Terminated {exe}." if rc == 0 else f"Could not terminate {exe}: {err or 'not running'}."

    # -------- destructive: two-phase confirmation --------
    if action in DESTRUCTIVE:
        return _destructive(action, str(value), services)

    if action == "status":
        return diagnostics.summary_text()

    return f"Unknown system_control action '{action}'."


def _destructive(action: str, value: str, services: dict | None) -> str:
    global _pending
    confirm = bool((services or {}).get("confirm_destructive", True))

    already_pending = (
        _pending["action"] == action
        and time.time() - _pending["ts"] < CONFIRM_WINDOW
    )
    if confirm and not already_pending:
        _pending = {"action": action, "value": value, "ts": time.time()}
        return (
            f"CONFIRM_REQUIRED:{action}. JARVIS must ask sir to confirm '{action}' "
            "in one short spoken question. Do NOT claim it was done. When sir agrees, "
            f"call system_control again with action '{action}' to execute it."
        )
    _pending = {"action": None, "value": None, "ts": 0.0}

    if action == "lock":
        _run(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "Workstation locked, sir."
    if action == "logoff":
        _run(["shutdown", "/l"])
        return "Logging off."
    if action == "shutdown":
        _run(["shutdown", "/s", "/t", "60"])
        return "Shutting down in 60 seconds — cancel with 'shutdown /a' if needed."
    if action == "restart":
        _run(["shutdown", "/r", "/t", "60"])
        return "Restarting in 60 seconds."
    if action == "sleep":
        _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Going to sleep."
    return f"Unhandled destructive action '{action}'."


# --------------------------------------------------------------- diagnostics
def _run_diagnostics(_args: dict | None = None) -> str:
    return diagnostics.summary_text()


# ------------------------------------------------------------------ reminders
def _set_reminder(args: dict) -> str:
    if SCHEDULER is None:
        return "The reminder service is only running in full JARVIS mode (jarvis_app.py)."
    text = str(args.get("text", "")).strip()
    minutes = args.get("minutes")
    at_time = str(args.get("at_time", "")).strip()
    if not text:
        return "Reminder needs a subject."
    if at_time:
        return SCHEDULER.add_reminder_at(text, at_time)
    try:
        mins = float(minutes) if minutes is not None else None
    except (TypeError, ValueError):
        mins = None
    if mins is None:
        return "Reminder needs minutes or an at_time like '15:30'."
    return SCHEDULER.add_reminder_in(text, mins)


def _get_briefing(args: dict) -> str:
    kind = str(args.get("kind", "all")).lower()
    if SCHEDULER is None:
        return "Briefings only run in full JARVIS mode (jarvis_app.py)."
    return SCHEDULER.briefing_text(kind)


# ------------------------------------------------------------------- presence
def _presence_control(args: dict) -> str:
    if PRESENCE is None:
        return "Presence sensor is only running in full JARVIS mode (jarvis_app.py)."
    act = str(args.get("action", "status")).lower()
    if act == "off":
        PRESENCE.stop()
        return "Webcam presence sensor disabled, sir."
    if act == "on":
        try:
            PRESENCE.start()
        except Exception as e:
            return f"Could not re-enable presence sensor: {e}"
        return "Webcam presence sensor active."
    st = PRESENCE.status()
    return f"Presence sensor: {st}."


# ------------------------------------------------------------------- dispatch
_HANDLERS = {
    "system_control": lambda a: _system_control(a.get("action", ""), a.get("value", ""), a.get("_services")),
    "run_diagnostics": lambda a: _run_diagnostics(a),
    "set_reminder": _set_reminder,
    "get_briefing": _get_briefing,
    "presence_control": _presence_control,
}


def dispatch(name: str, args: dict, services: dict | None = None) -> str | None:
    """Return a result string, or None when the name is not ours."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    if services is not None and name == "system_control":
        args = dict(args or {})
        args["_services"] = services
    try:
        return handler(args or {})
    except Exception as e:  # a failed action must produce speech-able feedback
        return f"Action '{name}' failed: {e}"


# ------------------------------------------------------------------- schemas
TOOL_DEFINITIONS_EXTRA = [
    {
        "type": "function",
        "function": {
            "name": "system_control",
            "description": "Control this Windows PC: apps, volume, brightness, URLs, files, screenshots, clipboard, typing, hotkeys, and power actions (lock/shutdown/restart ask for confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open_app", "close_app", "open_url", "open_path",
                            "volume_get", "volume_set", "volume_up", "volume_down",
                            "mute", "unmute", "is_muted",
                            "brightness_set", "brightness_get",
                            "screenshot", "clipboard_get", "clipboard_set",
                            "type_text", "hotkey", "press", "mouse_move",
                            "kill_process", "lock", "logoff", "shutdown",
                            "restart", "sleep", "status",
                        ],
                    },
                    "value": {
                        "type": "string",
                        "description": "Action payload: app name, URL, path, volume 0-100, hotkey like 'ctrl+shift+t', process name, etc.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_diagnostics",
            "description": "Full system health check: CPU, memory, disk, battery, GPU, network and heaviest processes. Use for any question about how the PC is doing.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Schedule a spoken reminder for sir. Fires even if he does not talk first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remind sir about."},
                    "minutes": {"type": "number", "description": "Minutes from now (use instead of at_time)."},
                    "at_time": {"type": "string", "description": "Clock time today like '15:30' (use instead of minutes)."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_briefing",
            "description": "Build a spoken briefing: weather (wttr.in), top news headlines, and system status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["all", "weather", "news", "system"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "presence_control",
            "description": "Enable, disable or query the webcam presence sensor (greets sir when he sits down).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "status"]},
                },
            },
        },
    },
]

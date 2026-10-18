"""Install-aware paths — dev folder vs proper installed app.

Dev (python jarvis_app.py): everything lives next to the repo, as before.
Installed (frozen JARVIS.exe): the bundle may sit in a read-only location
(Program Files) or a PyInstaller temp folder, so anything the app WRITES
(settings, secrets, voices, workspace) goes to a per-user data dir instead:
%APPDATA%\\JARVIS on Windows, ~/.jarvis elsewhere.

Use user_file(name) for writable files; read-only shipped files (config.yaml)
keep living next to the bundle.
"""

import os
import sys


def frozen() -> bool:
    """True when running as the frozen JARVIS.exe (PyInstaller)."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    """Where the app itself lives: exe folder (installed) or repo root (dev)."""
    if frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    """Writable per-user data dir. Created on first use."""
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(root, "JARVIS")
    else:
        d = os.path.join(os.path.expanduser("~"), ".jarvis")
    os.makedirs(d, exist_ok=True)
    return d


def user_file(name: str) -> str:
    """Writable path for NAME. Dev: next to the repo. Installed: data dir."""
    if frozen():
        return os.path.join(data_dir(), name)
    return os.path.join(bundle_dir(), name)

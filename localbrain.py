"""Local brain (Ollama) management — status and one-click install.

The brain's local half runs on Ollama. This module answers "is it here?"
and, if not, installs it in the background: downloads OllamaSetup.exe,
walks the user through it, then pulls the model from config.yaml.

Safe to call from anywhere: GUI wizard, brain skill, or terminal.
"""

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request

INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
_DEFAULT_MODEL = "hf.co/ge525/Qwen3.8-9B-Distill-uncensored-heretic-Q4_K_M-GGUF:Q4_K_M"

_state = {"installing": False, "log": []}
_lock = threading.Lock()


def _log(msg: str) -> None:
    with _lock:
        _state["log"].append(msg)
        _state["log"] = _state["log"][-50:]


def _repo_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def wanted_model() -> str:
    """Model name from config.yaml, with a sane fallback."""
    cfg = os.path.join(_repo_dir(), "config.yaml")
    try:
        with open(cfg, encoding="utf-8") as f:
            m = re.search(r'local_model:\s*"([^"]+)"', f.read())
            if m:
                return m.group(1)
    except Exception:
        pass
    return _DEFAULT_MODEL


def _ollama_bin():
    return shutil.which("ollama")


def status() -> dict:
    """Snapshot: installed / reachable / models / installing / recent log."""
    info = {"installed": False, "reachable": False, "models": [],
            "installing": False, "log": []}
    with _lock:
        info["installing"] = _state["installing"]
        info["log"] = list(_state["log"][-8:])
    if not _ollama_bin():
        return info
    info["installed"] = True
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True,
                           text=True, timeout=15)
        if r.returncode == 0:
            info["reachable"] = True
            for line in r.stdout.splitlines()[1:]:
                name = line.split()[0] if line.split() else ""
                if name and name != "NAME":
                    info["models"].append(name)
    except Exception:
        pass
    return info


def start_install() -> str:
    """Kick off the background install. Idempotent — safe to call twice."""
    with _lock:
        if _state["installing"]:
            return "The local brain is already installing, sir — check status for progress."
        _state["installing"] = True
        _state["log"] = []
    t = threading.Thread(target=_install, daemon=True)
    t.start()
    return ("Installing your local brain in the background, sir. "
            "It's a big download — I'll keep working while it runs.")


def _install() -> None:
    try:
        _log("Checking for Ollama…")
        if not _ollama_bin():
            dest = os.path.join(os.environ.get("TEMP", os.getcwd()),
                                "OllamaSetup.exe")
            if not os.path.isfile(dest):
                _log("Downloading the Ollama installer…")
                urllib.request.urlretrieve(INSTALLER_URL, dest)
            _log("Opening the Ollama installer — click through it, sir.")
            subprocess.Popen([dest])  # GUI installer, user clicks Next
            _log("Waiting for the installer to finish…")
            for _ in range(180):  # ~15 min
                if _ollama_bin():
                    break
                time.sleep(5)
            if not _ollama_bin():
                _log("Ollama still not found — did the installer finish?")
                return
        _log("Ollama is here. Pulling the model (this is the big one)…")
        model = wanted_model()
        if model not in (status().get("models") or []):
            p = subprocess.Popen(["ollama", "pull", model],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 text=True)
            for line in p.stdout:
                line = line.strip()
                if line:
                    _log(line[-120:])
            p.wait()
            if p.returncode != 0:
                _log("Model pull had trouble — try 'ollama pull " + model + "' by hand.")
                return
        _log("Local brain ready, sir. Restart me and I'll think on-device.")
    except Exception as e:
        _log(f"Install hit a snag: {e}")
    finally:
        with _lock:
            _state["installing"] = False

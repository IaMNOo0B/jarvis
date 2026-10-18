"""
JARVIS one-shot setup — dependencies + model downloads + core check.

    python setup_models.py

Safe to re-run: everything already present is skipped.
"""

import os
import sys
import subprocess
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
PIPER_DIR = os.path.join(BASE, "models", "piper")
VOICE = "en_GB-northern_english_male-medium"

REQUIRED = [
    "piper-tts", "faster-whisper", "openwakeword==0.6.0",
    "sounddevice", "soundfile", "pycaw", "comtypes",
    "PyQt6", "pywin32", "opencv-python", "psutil", "PyAutoGUI",
    "PyYAML", "ollama", "ddgs", "beautifulsoup4", "requests",
]


def log(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def ensure_pip_packages() -> None:
    missing = []
    for spec in REQUIRED:
        name = spec.split("==")[0].replace("-", "_").lower()
        try:
            __import__(name if name != "piper_tts" else "piper")
            continue
        except ImportError:
            pass
        # import name differs from dist name for a few — fall back to pkg check
        import importlib.metadata as md
        try:
            md.version(spec.split("==")[0])
        except Exception:
            missing.append(spec)
    if not missing:
        log("all Python packages present")
        return
    log(f"installing: {', '.join(missing)}")
    r = subprocess.run([sys.executable, "-m", "pip", "install", *missing])
    if r.returncode != 0:
        sys.exit(f"[setup] pip install failed (exit {r.returncode})")


def ensure_piper_voice() -> None:
    os.makedirs(PIPER_DIR, exist_ok=True)
    path = os.path.join(PIPER_DIR, VOICE + ".onnx")
    if os.path.isfile(path):
        log(f"voice present: {VOICE}")
        return
    parts = VOICE.split("-")
    lang, name, quality = parts[0], parts[1], parts[2]
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang[:2]}/{lang}/{name}/{quality}"
    for suffix in (".onnx", ".onnx.json"):
        url = f"{base}/{VOICE}{suffix}?download=true"
        dest = path + suffix
        log(f"downloading {VOICE}{suffix} ...")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            sys.exit(f"[setup] voice download failed: {e}")
    log("British voice ready")


def ensure_whisper() -> None:
    try:
        from faster_whisper import WhisperModel
        model_name = "base.en"
        log(f"pre-downloading whisper '{model_name}' (first run only) ...")
        WhisperModel(model_name, device="cpu", compute_type="int8")
        log("whisper ready")
    except Exception as e:
        sys.exit(f"[setup] whisper setup failed: {e}")


def ensure_wakeword() -> None:
    try:
        import openwakeword
        from openwakeword.model import Model
        try:
            Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        except Exception:
            log("downloading wake-word models ...")
            openwakeword.utils.download_models()
            Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        log("wake word 'hey jarvis' ready")
    except Exception as e:
        sys.exit(f"[setup] wake-word setup failed: {e}")


def check_ollama() -> None:
    try:
        import ollama
        tags = ollama.list()
        models = [m.get("model", m.get("name", "?")) for m in tags.get("models", [])]
        log(f"ollama online — {len(models)} model(s)")
        if not models:
            log("WARNING: no models pulled. Run: ollama pull llama3.1")
    except Exception as e:
        log(f"WARNING: ollama not reachable ({e}) — start it with 'ollama serve'")


def ensure_desktop_icon() -> None:
    """Create <Desktop>/JARVIS.lnk (idempotent; skipped off Windows)."""
    try:
        from shortcut import ensure_desktop_shortcut
        lnk = ensure_desktop_shortcut()
        log(f"desktop icon: {lnk}" if lnk else "desktop icon skipped (non-Windows)")
    except Exception as e:
        log(f"WARNING: desktop icon not created ({e})")


def main() -> None:
    log("JARVIS setup starting")
    ensure_pip_packages()
    ensure_piper_voice()
    ensure_whisper()
    ensure_wakeword()
    check_ollama()
    ensure_desktop_icon()
    log("setup complete — run:  python jarvis_app.py  (or the JARVIS desktop icon)")


if __name__ == "__main__":
    main()

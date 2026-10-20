# -*- mode: python ; coding: utf-8 -*-
# JARVIS PyInstaller spec.
#
# Build (from project root, AI_Model/):
#     pyinstaller --clean --noconfirm --onedir --name JARVIS Jarvis.spec
# or, for a single exe:
#     pyinstaller --clean --noconfirm --onefile --name JARVIS Jarvis.spec
#
# The one-file JARVIS.exe is the "double-click JARVIS" app — no Python needed
# on the target PC. The target PC still needs its own network for the first-run
# download of the offline Piper / faster-whisper / openWakeWord assets.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

hidden_imports = [
    # --- PyQt6 ---
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.QtWebEngineWidgets",
    "sip",
    # --- audio / voice ---
    "sounddevice",
    "soundfile",
    "sounddevice._portaudio",
    "sounddevice._portaudiokbd",
    "portaudio",
    "wave",
    "numpy",
    "numpy.linalg",
    # --- piper / TTS ---
    "piper",
    "piper.PiperVoice",
    "piper.voice",
    # --- faster-whisper ---
    "faster_whisper",
    "faster_whisper.tokenizer",
    "faster_whisper.tokenizer_multilingual",
    "faster_whisper.model",
    "faster_whisper.backends",
    "faster_whisper.backend_device",
    "ctranslate2",
    # --- openwakeword / onnx ---
    "openwakeword",
    "openwakeword.model",
    "onnxruntime",
    "onnxruntime.capi",
    "onnxruntime.capi.onnxruntime_pybind11_state",
    # --- pycaw / comtypes / windows ---
    "pycaw",
    "pycaw.pycaw",
    "pycaw.pycaw.IAudioEndpointVolume",
    "comtypes",
    "comtypes.client",
    "comtypes.gen",
    "win32api",
    "win32gui",
    "win32con",
    "win32process",
    "win32security",
    "win32event",
    "win32pipe",
    # --- pywin32 full-ish coverage (overlay / hotkey COM) ---
    "pywintypes",
    "pythoncom",
    "win32com",
    "win32com.client",
    "win32com.client.constants",
    "win32com.client.mwildcard",
    # --- ollama client ---
    "ollama",
    "ollama._client",
    "ollama._utils",
    "ollama.types",
    "ollama.__init__",
    # --- opencv ---
    "cv2",
    "cv2.data",
    "cv2.cv2",
    # --- pyautogui / PIL backend ---
    "pyautogui",
    "pyautogui.keyboard",
    "pyautogui.mouse",
    "pyautogui._pyautogui_osx",
    "pyautogui._pyautogui_win",
    "pyautogui._pyautogui_linux",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL._imaging",
    "PIL._imagingtk",
    # --- bs4 / requests / ddgs / yaml ---
    "bs4",
    "bs4.builder",
    "bs4.element",
    "bs4.diagnose",
    "requests",
    "requests.packages",
    "requests.packages.urllib3",
    "requests.packages.urllib3.util",
    "requests.packages.urllib3.exceptions",
    "ddgs",
    "yaml",
    "yaml.constructor",
    "yaml.emitter",
    "yaml.nodes",
    "yaml.parser",
    "yaml.reader",
    "yaml.resolver",
    "yaml scanner",
    "yaml serializer",
    "yaml tokens",
    # --- psutil ---
    "psutil",
    "psutil._common",
    "psutil._psutil_linux",
    "psutil._psutil_posix",
    "psutil._psutil_windows",
    # --- transformers (if ever used frozen) ---
    "transformers",
    "transformers.models",
    "transformers.models.auto",
    "transformers.models.auto.modeling_auto",
    # --- torch (optional / large) ---
    "torch",
    "torch._C",
    "torch.cuda",
    "torch.nn",
    "torch.optim",
    "torch.utils.data",
    "torch.distributions",
    "torch.multiprocessing",
    "torch._utils",
    "torch.serialization",
    "torch.backends",
    "torch.backends.cudnn",
    "torch.backends.mkldnn",
]

main_script = os.path.join(os.path.dirname(__file__), "freeze_jarvis.py")

# The app sources (jarvis_app.py, brain.py, ...) live at the REPO ROOT, one
# level above this spec. Put it on the module search path so Analysis bundles
# them into the frozen app.
_repo_root = str(Path(__file__).resolve().parent.parent)

# ---------------------------------------------------------------- data + binaries
APP = {
    "script": main_script,
    "name": "JARVIS",
}

data_files = [
    (os.path.join(_repo_root, "JARVIS_PROTOCOLS.txt"), "."),
    (os.path.join(_repo_root, "skill_test_runner.py"), "."),
]

# The skill loader scans the on-disk skills/ tree at runtime. Bundle the
# source files as data as well as the Python package modules so user overrides
# can compare against the shipped baseline in a frozen build.
_skills_root = os.path.join(_repo_root, "skills")
for _current_root, _dirnames, _filenames in os.walk(_skills_root):
    _dirnames[:] = [d for d in _dirnames if d not in {"__pycache__", ".git"}]
    for _filename in _filenames:
        if not (_filename.endswith(".py") or _filename.endswith(".md")):
            continue
        _source_path = os.path.join(_current_root, _filename)
        _relative_dir = os.path.relpath(_current_root, _repo_root)
        data_files.append((_source_path, _relative_dir))

binaries = []

# Collect dynamic libs for native packages that PyInstaller's hooks might not
# fully pull in on every wheel (especially sounddevice/PyQt6/opencv/pycaw).
binaries += collect_dynamic_libs("sounddevice", need_info=True) or []
binaries += collect_dynamic_libs("cv2", need_info=True) or []
binaries += collect_dynamic_libs("pycaw", need_info=True) or []
try:
    binaries += collect_dynamic_libs("PyQt6", need_info=True) or []
except Exception:
    pass

try:
    data_files += collect_data_files("pycaw", recurse=True) or []
except Exception:
    pass
try:
    data_files += collect_data_files("PyQt6", recurse=True) or []
except Exception:
    pass

a = Analysis(
    ["freeze_jarvis.py"],
    pathex=[_repo_root],
    binaries=binaries if binaries else None,
    datas=data_files if data_files else None,
    hiddenimports=hidden_imports,
    hookspath=None,
    runtime_hooks=None,
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=None,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)

'''JARVIS single-file frozen launcher.

This is the PyInstaller one-file entry point. On a Windows PC with NO Python
installed, double-clicking the resulting JARVIS.exe is enough: it unpacks
itself, creates its models folder under %APPDATA%\\JARVIS\\models if needed,
downloads the offline voice/whisper/wake assets on first run, creates the
desktop icon, and boots the full JARVIS experience (HUD + voice + webcam +
brain).

Built from jarvis_app.py via:

    pyinstaller --clean --noconfirm --onefile --name JARVIS Jarvis.spec

(this spec is the source of truth for the build; the build bat drives it).

Runtime note: frozen one-file executables extract to a temp _MEI dir on
startup. Long-lived Jarvis sessions run fine from there, but anything that
must persist across restarts (models, memory_bank, logs, secrets) goes under
APPDATA/JARVIS, never under the temp dir.
'''

import os
import sys
import tempfile
from pathlib import Path


def _frozen_root() -> Path:
    '''PyInstaller one-file runtime root, or cwd when run from source.'''
    try:
        from PyInstaller.utils.hooks import get_temp_dir
        return Path(get_temp_dir())
    except Exception:
        pass
    # Fallback: the one-file runtime sets _MEIPASS; source runs in cwd.
    meipass = os.environ.get('_MEIPASS')
    if meipass:
        return Path(meipass)
    return Path.cwd()


def _repo_root() -> Path:
    '''Locate the app sources (the dir containing jarvis_app.py).

    The sources live at the repo root; this entry point may sit at the root
    or inside AI_Model/ (the PyInstaller build dir). Walk up until found.
    '''
    here = Path(__file__).resolve().parent
    for cand in (here, here.parent):
        if (cand / "jarvis_app.py").is_file():
            return cand
    return here


def _resource_path(rel: str) -> Path:
    '''Resolve a bundled resource shipped via --add-data / spec Analysis.'''
    root = _frozen_root()
    p = root / rel
    if p.exists():
        return p
    # Unfrozen (running from source): resources live beside the app sources.
    return _repo_root() / rel


if __name__ == "__main__":
    # Make the app sources importable no matter where this entry point lives
    # (repo root or AI_Model/), then launch the full JARVIS experience.
    _rr = str(_repo_root())
    if _rr not in sys.path:
        sys.path.insert(0, _rr)
    from jarvis_app import main as _jarvis_main
    sys.exit(_jarvis_main())

"""Self-update — one-button `git pull` from the Settings panel.

GitHub is the bridge between Muse (in the cloud) and this PC: every change
is pushed to the repo, and this module pulls it down. The Settings dialog's
"Updates" tab drives it; the pull runs in a background thread so the UI
never freezes.

If the folder isn't a git clone (e.g. the ZIP was downloaded instead),
pull_updates() says so plainly instead of failing.
"""

import os
import subprocess
import sys

_TIMEOUT = 120


def repo_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=repo_dir(),
        capture_output=True, text=True, timeout=_TIMEOUT)


def is_git_repo() -> bool:
    try:
        return _git("rev-parse", "--git-dir").returncode == 0
    except Exception:
        return False


def current_commit() -> str | None:
    """Short hash of HEAD, or None when unavailable."""
    try:
        r = _git("rev-parse", "--short", "HEAD")
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        return None


def _file_hash(path: str):
    import hashlib
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def pull_updates() -> tuple[bool, str]:
    """Pull the latest code from GitHub. Returns (ok, human message)."""
    if not is_git_repo():
        return (False,
                "This folder isn't a git clone, sir — so there's nothing to "
                "pull. Clone the repo with git once (instead of the ZIP), "
                "and this button will fetch every update I push.")
    try:
        cur = current_commit()
        req_before = _file_hash(os.path.join(repo_dir(), "requirements.txt"))
        r = _git("pull")
    except FileNotFoundError:
        return False, "Git isn't installed on this PC, sir — install it from git-scm.com."
    except Exception as e:
        return False, f"Update failed, sir: {e}"
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return False, f"Update failed, sir: {out[:300]}"
    new = current_commit()
    # New Python packages don't install themselves — flag it.
    req_note = ""
    if _file_hash(os.path.join(repo_dir(), "requirements.txt")) != req_before:
        req_note = (" Also: the requirements changed, so run "
                    "`pip install -r requirements.txt` once in the jarvis folder.")
    if "Already up to date" in out or new == cur:
        return True, f"Already up to date, sir ({new or 'unknown version'}).{req_note}"
    return (True,
            f"Updated {cur or '?'} → {new or '?'}, sir. "
            f"Restart JARVIS to run the new version.{req_note}")


def install_requirements() -> tuple[bool, str]:
    """`pip install -r requirements.txt`. Idempotent — pip skips what's
    already there, so it's safe to run any time."""
    req = os.path.join(repo_dir(), "requirements.txt")
    if not os.path.isfile(req):
        return False, "No requirements.txt found here, sir."
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req],
            capture_output=True, text=True, timeout=600)
    except Exception as e:
        return False, f"Install failed, sir: {e}"
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        return False, "Install failed, sir: " + " ".join(tail)
    return True, "Requirements installed, sir. Restart JARVIS."

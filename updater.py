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


def pull_updates() -> tuple[bool, str]:
    """Pull the latest code from GitHub. Returns (ok, human message)."""
    if not is_git_repo():
        return (False,
                "This folder isn't a git clone, sir — so there's nothing to "
                "pull. Clone the repo with git once (instead of the ZIP), "
                "and this button will fetch every update I push.")
    try:
        cur = current_commit()
        r = _git("pull")
    except FileNotFoundError:
        return False, "Git isn't installed on this PC, sir — install it from git-scm.com."
    except Exception as e:
        return False, f"Update failed, sir: {e}"
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return False, f"Update failed, sir: {out[:300]}"
    new = current_commit()
    if "Already up to date" in out or new == cur:
        return True, f"Already up to date, sir ({new or 'unknown version'})."
    return (True,
            f"Updated {cur or '?'} → {new or '?'}, sir. "
            f"Restart JARVIS to run the new version.")

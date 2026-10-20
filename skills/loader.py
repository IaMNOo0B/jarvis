"""Discover drop-in skill packs with writable user overrides.

Development loads from the repository's skills/ folder. Packaged Jarvis loads
user-installed/promoted overrides first, then falls back to bundled skills.
A user override with a broken import is reported as broken rather than silently
falling back, so a failed promotion cannot be hidden.
"""

import importlib.util
import os
import traceback

from paths import frozen, user_file

BUNDLED_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
USER_SKILLS_DIR = user_file("skills") if frozen() else BUNDLED_SKILLS_DIR
# Retain the old exported name for diagnostics and other modules.
SKILLS_DIR = BUNDLED_SKILLS_DIR


def _iter_skill_dirs():
    search_dirs = [USER_SKILLS_DIR]
    if os.path.realpath(BUNDLED_SKILLS_DIR) != os.path.realpath(USER_SKILLS_DIR):
        search_dirs.append(BUNDLED_SKILLS_DIR)
    seen = set()
    for root in search_dirs:
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for entry in entries:
            if entry.startswith(("_", ".")) or entry in seen:
                continue
            skill_py = os.path.join(root, entry, "skill.py")
            if os.path.isfile(skill_py):
                seen.add(entry)
                yield entry, skill_py


def discover():
    """Import every selected skill pack; errors stay visible to diagnostics."""
    found = {}
    for name, path in _iter_skill_dirs():
        try:
            spec = importlib.util.spec_from_file_location(
                "jarvis_skill_%s" % name, path)
            if spec is None or spec.loader is None:
                raise ImportError("cannot create module spec for %s" % path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            found[name] = {"module": mod, "path": path}
        except Exception:
            found[name] = {"error": traceback.format_exc(limit=3), "path": path}
    return found

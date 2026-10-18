"""Discovers drop-in skill packs: every ``skills/<name>/skill.py``.

Stdlib only. A broken skill never breaks the brain — it is skipped and the
error is recorded so diagnostics can report it.
"""

import importlib.util
import os
import traceback

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iter_skill_dirs():
    try:
        entries = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return
    for entry in entries:
        if entry.startswith(("_", ".")):
            continue
        skill_py = os.path.join(SKILLS_DIR, entry, "skill.py")
        if os.path.isfile(skill_py):
            yield entry, skill_py


def discover():
    """Import every skill pack.

    Returns ``{name: {"module": mod} | {"error": str}}`` — errors are captured,
    never raised.
    """
    found = {}
    for name, path in _iter_skill_dirs():
        try:
            spec = importlib.util.spec_from_file_location(
                "jarvis_skill_%s" % name, path)
            if spec is None or spec.loader is None:
                raise ImportError("cannot create module spec for %s" % path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            found[name] = {"module": mod}
        except Exception:
            found[name] = {"error": traceback.format_exc(limit=3)}
    return found

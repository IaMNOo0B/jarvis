"""Discover drop-in skill packs with writable user overrides.

Development loads from the repository's skills/ folder. Packaged Jarvis loads
user-installed/promoted overrides first, then falls back to bundled skills.

If a versioned promotion fails immediately while importing at startup, the
loader asks skill_evolution to restore the matching prior version only when
the on-disk hash still matches that promotion. Unknown or manually edited
files are left untouched and errors remain visible.
"""

import importlib.util
import os
import traceback

from paths import frozen, user_file

BUNDLED_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
USER_SKILLS_DIR = user_file("skills") if frozen() else BUNDLED_SKILLS_DIR
SKILLS_DIR = BUNDLED_SKILLS_DIR


def _search_roots():
    roots = [USER_SKILLS_DIR]
    if os.path.realpath(BUNDLED_SKILLS_DIR) != os.path.realpath(USER_SKILLS_DIR):
        roots.append(BUNDLED_SKILLS_DIR)
    return roots


def _iter_skill_dirs():
    seen = set()
    for root in _search_roots():
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


def _import_skill(name, path):
    spec = importlib.util.spec_from_file_location("jarvis_skill_%s" % name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot create module spec for %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _record_loaded_version(name, path):
    try:
        from skill_evolution import mark_skill_version_active
        return mark_skill_version_active(name, path)
    except Exception as exc:
        return {"activated": False, "reason": f"Could not record version load: {type(exc).__name__}: {exc}"}


def _recover_import_failure(name, path, error_text):
    try:
        from skill_evolution import recover_failed_promotion_on_import_error
        return recover_failed_promotion_on_import_error(name, path, error_text)
    except Exception as exc:
        return {
            "recovered": False,
            "reason": f"Automatic recovery could not run: {type(exc).__name__}: {exc}",
        }


def _fallback_after_recovery(name, failed_path):
    """Return the restored override or bundled baseline, if one remains."""
    if os.path.isfile(failed_path):
        return failed_path
    bundled_path = os.path.join(BUNDLED_SKILLS_DIR, name, "skill.py")
    if os.path.realpath(BUNDLED_SKILLS_DIR) != os.path.realpath(USER_SKILLS_DIR) and os.path.isfile(bundled_path):
        return bundled_path
    return None


def discover():
    """Import each selected skill and expose automatic recovery results."""
    found = {}
    for name, path in _iter_skill_dirs():
        try:
            mod = _import_skill(name, path)
            activation = _record_loaded_version(name, path)
            found[name] = {
                "module": mod,
                "path": path,
                "activation": activation,
            }
            continue
        except Exception:
            original_error = traceback.format_exc(limit=5)

        recovery = _recover_import_failure(name, path, original_error)
        if recovery.get("recovered"):
            retry_path = _fallback_after_recovery(name, path)
            if retry_path:
                try:
                    mod = _import_skill(name, retry_path)
                    found[name] = {
                        "module": mod,
                        "path": retry_path,
                        "recovery": recovery,
                        "activation": _record_loaded_version(name, retry_path),
                    }
                    continue
                except Exception:
                    retry_error = traceback.format_exc(limit=5)
                    found[name] = {
                        "error": (
                            "A failed promotion was automatically rolled back, but the restored "
                            "skill also failed to import.\n"
                            f"Recovery: {recovery}\nOriginal import error:\n{original_error}"
                            f"\nRestored import error:\n{retry_error}"
                        ),
                        "path": retry_path,
                        "recovery": recovery,
                    }
                    continue

            found[name] = {
                "error": (
                    "A failed promotion was automatically rolled back, but no previous or "
                    "bundled skill file remains to load.\n"
                    f"Recovery: {recovery}\nOriginal import error:\n{original_error}"
                ),
                "path": path,
                "recovery": recovery,
            }
            continue

        found[name] = {
            "error": original_error,
            "path": path,
            "recovery": recovery,
        }
    return found

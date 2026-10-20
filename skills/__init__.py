"""JARVIS skill system — drop-in capability packs.

A *skill* is a folder ``skills/<name>/`` containing a ``skill.py`` with::

    SKILL_NAME = "<name>"            # must match the folder name
    SKILL_DESCRIPTION = "..."       # one line, shown in diagnostics
    TOOL_DEFINITIONS = [...]        # OpenAI-style function schemas,
                                    # same shape as actions.TOOL_DEFINITIONS
    def handle(tool_name, args, services=None):
        # Return a result string, or None when this skill
        # does not own ``tool_name``. Never raise.

The brain picks skills up automatically — no registration, no core edits.
Core tools (actions.py / system_actions.py) always win name collisions.

Public API: ``tool_definitions()``, ``dispatch()``, ``list_skills()``,
``reload()``.
"""

from .loader import discover

_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        _CACHE = discover()
    return _CACHE


def reload():
    """Forget cached skills so newly dropped-in packs are picked up."""
    global _CACHE
    _CACHE = None


def _tool_name(schema):
    try:
        return (schema.get("function") or {}).get("name")
    except Exception:
        return None


def tool_definitions(exclude=frozenset()):
    """Schemas from every healthy skill, minus core/duplicate names."""
    out = []
    seen = set(exclude or ())
    for _name, info in _load().items():
        mod = info.get("module")
        if mod is None:
            continue
        for schema in getattr(mod, "TOOL_DEFINITIONS", None) or []:
            tname = _tool_name(schema)
            if not tname or tname in seen:
                continue
            seen.add(tname)
            out.append(schema)
    return out


def dispatch(name, args, services=None):
    """Route one tool call to the skill that owns it.

    Returns the result string, or None when no skill claims ``name``.
    Never raises — a crashing skill produces speakable feedback instead.
    """
    for sname, info in _load().items():
        mod = info.get("module")
        if mod is None:
            continue
        handle = getattr(mod, "handle", None)
        if not callable(handle):
            continue
        try:
            result = handle(name, args or {}, services)
        except Exception as e:  # a failed skill must produce speakable feedback
            return "Skill '%s' failed on '%s': %s" % (sname, name, e)
        if result is not None:
            return result
    return None


def list_skills():
    """Metadata for diagnostics / HUD: name, description, tools, status."""
    rows = []
    for name, info in _load().items():
        if "error" in info:
            rows.append({"name": name, "status": "error",
                         "error": info["error"]})
            continue
        mod = info["module"]
        tools = [t for t in
                 (_tool_name(s) for s in
                  getattr(mod, "TOOL_DEFINITIONS", None) or [])
                 if t]
        row = {
            "name": getattr(mod, "SKILL_NAME", name),
            "description": getattr(mod, "SKILL_DESCRIPTION", ""),
            "tools": tools,
            "status": "ok" if callable(getattr(mod, "handle", None))
                      else "no-handle",
        }
        if info.get("recovery"):
            row["startup_recovery"] = info["recovery"]
        if info.get("activation", {}).get("activated"):
            row["active_version"] = info["activation"].get("version_id")
        rows.append(row)
    return rows

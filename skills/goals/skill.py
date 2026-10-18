"""Goals — long-term tracking with a real ledger.

goal_add / goal_list / goal_log / goal_done. The brain does the coaching;
this skill is the persistent ledger (JSON in the user data dir).
Stdlib only.
"""

import json
import os
import time
from datetime import datetime

SKILL_NAME = "goals"
SKILL_DESCRIPTION = ("Long-term goal tracking: add goals, log progress, "
                     "list them, mark done.")


def _ledger_path():
    if os.environ.get("JARVIS_GOALS_FILE"):
        return os.environ["JARVIS_GOALS_FILE"]
    from paths import user_file
    return user_file("goals.json")


def _load():
    try:
        with open(_ledger_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(goals):
    with open(_ledger_path(), "w", encoding="utf-8") as f:
        json.dump(goals, f, indent=1)


def _find(goals, gid):
    for g in goals:
        if str(g.get("id")) == str(gid).strip():
            return g
    return None


def _goal_add(args):
    title = str(args.get("title", "") or "").strip()
    if not title:
        return "goal_add needs 'title'."
    goals = _load()
    gid = str(max([int(g.get("id", 0)) for g in goals] + [0]) + 1)
    goals.append({"id": gid, "title": title,
                  "created": datetime.now().strftime("%Y-%m-%d"),
                  "entries": [], "done": False})
    _save(goals)
    return f"Goal #{gid} noted, sir: {title}"


def _goal_list(args):
    goals = _load()
    open_g = [g for g in goals if not g.get("done")]
    if not open_g:
        return "No open goals, sir."
    lines = ["Your goals, sir:"]
    for g in open_g:
        n = len(g.get("entries", []))
        lines.append(f"#{g['id']} {g['title']} ({n} update{'s' if n != 1 else ''})")
    return "\n".join(lines)


def _goal_log(args):
    gid = str(args.get("goal_id", "") or "").strip()
    text = str(args.get("text", "") or "").strip()
    if not gid or not text:
        return "goal_log needs 'goal_id' and 'text'."
    goals = _load()
    g = _find(goals, gid)
    if not g:
        return f"No goal #{gid}, sir."
    g.setdefault("entries", []).append(
        {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text})
    _save(goals)
    return f"Logged on goal #{gid}, sir."


def _goal_done(args):
    gid = str(args.get("goal_id", "") or "").strip()
    if not gid:
        return "goal_done needs 'goal_id'."
    goals = _load()
    g = _find(goals, gid)
    if not g:
        return f"No goal #{gid}, sir."
    g["done"] = True
    g["done_on"] = datetime.now().strftime("%Y-%m-%d")
    _save(goals)
    return f"Goal #{gid} complete — well done, sir: {g['title']}"


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "goal_add",
        "description": "Start tracking a long-term goal.",
        "parameters": {"type": "object",
                       "properties": {"title": {"type": "string"}},
                       "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "goal_list",
        "description": "List open goals with progress counts.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "goal_log",
        "description": "Log a progress update on a goal.",
        "parameters": {"type": "object",
                       "properties": {"goal_id": {"type": "string"},
                                      "text": {"type": "string"}},
                       "required": ["goal_id", "text"]}}},
    {"type": "function", "function": {
        "name": "goal_done",
        "description": "Mark a goal complete.",
        "parameters": {"type": "object",
                       "properties": {"goal_id": {"type": "string"}},
                       "required": ["goal_id"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "goal_add":
            return _goal_add(args)
        if tool_name == "goal_list":
            return _goal_list(args)
        if tool_name == "goal_log":
            return _goal_log(args)
        if tool_name == "goal_done":
            return _goal_done(args)
    except Exception as e:
        return f"Goals tool failed, sir: {e}"
    return None

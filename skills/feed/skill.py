"""Feed — your morning digest page.

build_digest gathers the date, weather, headlines and your goals into one
styled page and opens it. Composes the everyday + goals + reports skills —
the brain's equivalent of a personal newspaper. Stdlib only.
"""

from skills.everyday.skill import handle as _everyday
from skills.goals.skill import handle as _goals
from skills.reports.skill import handle as _reports

SKILL_NAME = "feed"
SKILL_DESCRIPTION = ("Build your daily digest page (date, weather, headlines, "
                     "goals) and open it.")


def _build_digest(args):
    date = _everyday("get_datetime", {}) or ""
    weather = _everyday("get_weather", {}) or ""
    news = _everyday("get_news", {}) or ""
    goals = _goals("goal_list", {}) or ""
    md = (f"# Morning digest\n\n*{date}*\n\n"
          f"## Weather\n{weather}\n\n"
          f"## Headlines\n{news}\n\n"
          f"## Goals\n{goals}\n")
    return _reports("make_report",
                    {"title": "Morning digest", "body": md, "open": "yes"})


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "build_digest",
        "description": ("Build your daily digest page (date, weather, headlines, "
                        "goals) and open it in the browser."),
        "parameters": {"type": "object", "properties": {}}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "build_digest":
            return _build_digest(args)
    except Exception as e:
        return f"Digest failed, sir: {e}"
    return None

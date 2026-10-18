"""Self-care — the brain updating and healing itself.

check_for_updates / install_requirements. Lets the user say
"Jarvis, check for updates" and lets the brain repair its own
dependencies when a skill fails on a missing package.
Stdlib only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_NAME = "updater"
SKILL_DESCRIPTION = ("Self-update: pull the latest JARVIS code from GitHub, "
                     "and install/repair Python requirements.")


def _check_for_updates(args):
    import updater
    ok, msg = updater.pull_updates()
    return msg


def _install_requirements(args):
    import updater
    ok, msg = updater.install_requirements()
    return msg


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "check_for_updates",
        "description": ("Pull the latest JARVIS code from GitHub. "
                        "Tell the user to restart JARVIS if anything changed."),
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "install_requirements",
        "description": ("Install or repair Python packages "
                        "(pip install -r requirements.txt). Use when a tool "
                        "fails on a missing package, or the user asks."),
        "parameters": {"type": "object", "properties": {}}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "check_for_updates":
            return _check_for_updates(args)
        if tool_name == "install_requirements":
            return _install_requirements(args)
        return None
    except Exception as e:
        return f"Sorry, sir — that hit a snag: {e}"

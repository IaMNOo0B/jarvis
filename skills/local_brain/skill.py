"""Local brain — Ollama status and install, as brain tools.

local_brain_status / install_local_brain. The user can ask
"Jarvis, is your local brain working?" or "install your local brain",
and the brain handles it without the Settings panel.
Stdlib only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_NAME = "local_brain"
SKILL_DESCRIPTION = ("Local brain (Ollama): check whether it's installed and "
                     "working, or install it in the background.")


def _status(args):
    import localbrain
    s = localbrain.status()
    if s["installing"]:
        tail = " | ".join(s["log"][-3:])
        return f"Still installing, sir. Latest: {tail}"
    if not s["installed"]:
        return ("My local brain isn't installed, sir — say the word and I'll "
                "install it (big download, runs in the background).")
    if not s["reachable"]:
        return ("Ollama is installed but not answering, sir — "
                "it may need a restart.")
    models = ", ".join(s["models"]) if s["models"] else "no models yet"
    return f"Local brain online, sir. Models: {models}."


def _install(args):
    import localbrain
    return localbrain.start_install()


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "local_brain_status",
        "description": ("Check whether the local brain (Ollama) is installed, "
                        "reachable, and which models it has."),
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "install_local_brain",
        "description": ("Install the local brain (Ollama + model) in the "
                        "background. The user clicks through the Ollama "
                        "installer when it opens. Big download — tell the "
                        "user it runs behind the scenes."),
        "parameters": {"type": "object", "properties": {}}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "local_brain_status":
            return _status(args)
        if tool_name == "install_local_brain":
            return _install(args)
        return None
    except Exception as e:
        return f"Sorry, sir — that hit a snag: {e}"

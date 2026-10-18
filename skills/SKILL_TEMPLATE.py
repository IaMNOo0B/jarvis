"""TEMPLATE — copy this file to skills/<your_skill>/skill.py and fill it in.

A skill is a drop-in capability pack: no core files need editing, the brain
discovers it on next start (or after skills.reload()).

3 steps:
  1. mkdir skills/<your_skill>  and copy this file to skills/<your_skill>/skill.py
  2. Set SKILL_NAME (must match the folder), describe the tools, implement handle()
  3. Restart JARVIS — your tools appear in the brain's toolset automatically.

Rules:
  * Tool names should be namespaced: "<your_skill>_..." to avoid collisions.
    Core tools (actions.py / system_actions.py) win any collision anyway.
  * handle() returns a string result, or None when the tool isn't yours.
  * handle() must never raise — return an error string instead; the loader
    also guards you, but speakable errors make a better JARVIS.
"""

SKILL_NAME = "my_skill"  # <-- must match the folder name
SKILL_DESCRIPTION = "One line: what this skill adds."

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "my_skill_do_thing",
            "description": "What it does and when JARVIS should use it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Input text to work on.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    # Add more tools here — each needs a matching branch in handle().
]


def handle(tool_name, args, services=None):
    """Run one of this skill's tools. Return None for tools that aren't ours."""
    args = args or {}
    if tool_name == "my_skill_do_thing":
        text = str(args.get("text", "")).strip()
        if not text:
            return "my_skill_do_thing needs 'text'."
        # ... do the work ...
        return "Done: %s" % text
    return None

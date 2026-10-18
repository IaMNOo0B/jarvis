# JARVIS skill system

New capabilities ship as **drop-in skill packs** — no core files to edit.

## Add a skill in 3 steps

1. `mkdir skills/<name>` and copy `SKILL_TEMPLATE.py` → `skills/<name>/skill.py`
2. Fill in `SKILL_NAME` (must match the folder), `TOOL_DEFINITIONS`, `handle()`
3. Restart JARVIS — the brain discovers the skill automatically

## Contract

`skill.py` must define:

| Name | What |
|---|---|
| `SKILL_NAME` | Folder name, e.g. `"browser"` |
| `SKILL_DESCRIPTION` | One line for diagnostics |
| `TOOL_DEFINITIONS` | OpenAI-style function schemas (same shape as `actions.TOOL_DEFINITIONS`) |
| `handle(tool_name, args, services=None)` | Returns a result string, or `None` if the tool isn't this skill's. Never raise. |

## Guarantees

- A broken skill is **skipped, never fatal** — the brain still starts, and
  `skills.list_skills()` reports the error for diagnostics.
- **Core tools win** name collisions (`actions.py` / `system_actions.py`
  are checked first, and their names are excluded from skill schemas).
- Skills receive the same `services` dict as other tools.

## Introspection

```python
from skills import list_skills, tool_definitions, reload
list_skills()        # [{'name': ..., 'tools': [...], 'status': 'ok'}, ...]
reload()             # pick up newly added skills without restarting the process
```

## Roadmap

Upcoming first-party skills (see the build map): `browser` (headless web
action), `telegram` (phone channel), `screen_watcher` (proactive vision).

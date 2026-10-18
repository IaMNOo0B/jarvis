# Everyday skill

The little tools a butler should just know. No new dependencies
(stdlib + requests, which the project already needs).

| Tool | Example |
|---|---|
| `get_datetime` | "what time is it" — the brain has no clock otherwise |
| `calculate` | `(100 - 37) / 3`, `sqrt(16)` — safe AST eval, never from memory |
| `set_timer` / `list_timers` / `cancel_timer` | `"5m"`, `"1h30m"`, `"90"` — announces via `services["speak"]` |
| `get_weather` | optional city; wttr.in, no key |
| `get_news` | optional topic; DuckDuckGo headlines |
| `define_word` | dictionaryapi.dev, no key |
| `translate` | English ↔ Hindi via MyMemory, no key |
| `pick_one` | `"pizza, biryani, pasta"` |

Timers fire on a daemon thread and call `services["speak"]` when the app
provides it (`jarvis_app` wires `self._say`); without it they still track
state for `list_timers`.

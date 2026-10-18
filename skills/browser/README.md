# Ghost Browser skill

JARVIS drives a real Chromium that is **always headless** — no window ever
opens. He browses like a ghost; you see only the HUD.

## One-time setup (on the PC)

```bat
pip install playwright
playwright install chromium
```

`playwright` is listed in `requirements.txt`. The `playwright install chromium`
step downloads the actual browser (~170 MB) — it is not a pip package.

> `.exe` build note: the frozen app still needs the Chromium binaries on the
> target machine — run `playwright install chromium` once there too.

## Tools

| Tool | What |
|---|---|
| `browser_open(url)` | Navigate; returns title + URL + text preview |
| `browser_snapshot()` | Interactive elements as `[e1]` `[e2]` … refs |
| `browser_click(ref)` | Click a ref, e.g. `e3` |
| `browser_fill(ref, text)` | Fill an input ref |
| `browser_screenshot()` | PNG → `skills/browser/shots/`, returns the path |

Typical flow: `browser_open` → `browser_snapshot` → `browser_click`/`browser_fill`.
**Refs expire on every navigation** — snapshot again after the page changes.

## Notes

- One shared browser is reused across calls (fast); a single lock keeps
  Playwright's thread-unsafe sync API safe under the brain's parallel tools.
- Timeouts: 20 s navigation, 15 s operations — failures come back as
  speakable text, never exceptions.
- Without Playwright installed, every tool replies with install guidance
  instead of crashing.

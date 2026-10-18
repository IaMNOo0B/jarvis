"""Ghost Browser skill — JARVIS drives a real, invisible Chromium.

Headless ALWAYS: no window ever pops up. The user sees only the HUD;
the web happens like a ghost.

Tools:
  browser_open(url)        navigate; returns title + URL + text preview
  browser_snapshot()       interactive elements as [e1] [e2] ... refs
  browser_click(ref)       click an element ref, e.g. "e3"
  browser_fill(ref, text)  fill an input ref
  browser_screenshot()     PNG capture -> path, for the human to view

State: one shared headless Chromium, reused across calls. Refs reset on
every navigation. Thread-safe via a single lock (Playwright's sync API
is not thread-safe).

Setup (one time, on the PC):
  pip install playwright
  playwright install chromium
"""

import os
import threading
import time

SKILL_NAME = "browser"
SKILL_DESCRIPTION = ("Invisible headless Chromium: open pages, list clickable "
                     "elements, click, fill forms, screenshot.")

_SHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
_NAV_TIMEOUT_MS = 20000
_OP_TIMEOUT_MS = 15000
_ELEMENT_SELECTOR = ("a, button, input, select, textarea, "
                     "[role='button'], [onclick]")
_MAX_ELEMENTS = 80

_LOCK = threading.Lock()
_CTX = {"playwright": None, "browser": None, "page": None, "refs": {}}

_MISSING = ("Playwright is not installed on this PC, so I can't browse yet. "
            "Run: pip install playwright  &&  playwright install chromium")


def _pw():
    if _CTX["playwright"] is None:
        from playwright.sync_api import sync_playwright  # ImportError if missing
        _CTX["playwright"] = sync_playwright().start()
    return _CTX["playwright"]


def _ensure_page():
    """Return the shared page, launching the invisible browser if needed."""
    try:
        page = _CTX["page"]
        if page is not None and not page.is_closed():
            return page
    except Exception:
        pass
    try:
        pw = _pw()
    except ImportError:
        raise RuntimeError(_MISSING)
    try:
        if _CTX["browser"] is not None:
            _CTX["browser"].close()
    except Exception:
        pass
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"),
    )
    page = context.new_page()
    page.set_default_timeout(_OP_TIMEOUT_MS)
    page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
    _CTX["browser"] = browser
    _CTX["page"] = page
    _CTX["refs"] = {}
    return page


def _describe(el):
    return el.evaluate("""(e) => {
        const t = (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
        return {
            tag: e.tagName.toLowerCase(),
            type: e.getAttribute('type') || '',
            label: (e.getAttribute('aria-label') || e.getAttribute('placeholder')
                    || e.getAttribute('name') || e.getAttribute('value') || t || '').slice(0, 60),
        };
    }""")


# ------------------------------------------------------------------ tools
def _browser_open(args):
    url = str(args.get("url", "")).strip()
    if not url:
        return "browser_open needs 'url'."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    with _LOCK:
        page = _ensure_page()
        page.goto(url, wait_until="domcontentloaded")
        _CTX["refs"] = {}
        current = page.url
        title = page.title()
        text = page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 1500) : ''")
    return "Opened %s\nTitle: %s\nPreview:\n%s" % (current, title, text.strip())


def _browser_snapshot(args):
    with _LOCK:
        page = _ensure_page()
        els = page.query_selector_all(_ELEMENT_SELECTOR)[:_MAX_ELEMENTS]
        refs = {}
        lines = []
        n = 0
        for el in els:
            try:
                if not el.is_visible():
                    continue
                info = _describe(el)
            except Exception:
                continue
            if not info["label"]:
                continue
            n += 1
            ref = "e%d" % n
            refs[ref] = el
            tag = info["tag"]
            if info["type"]:
                tag += ":" + info["type"]
            lines.append('[%s] <%s> "%s"' % (ref, tag, info["label"]))
        _CTX["refs"] = refs
    if not lines:
        return "No interactive elements found on this page."
    return ("Interactive elements (use browser_click/browser_fill with the ref; "
            "refs expire when the page changes):\n" + "\n".join(lines))


def _browser_click(args):
    ref = str(args.get("ref", "")).strip()
    if not ref:
        return "browser_click needs 'ref' (e.g. 'e3' from browser_snapshot)."
    with _LOCK:
        page = _ensure_page()
        el = _CTX["refs"].get(ref)
        if el is None:
            return ("Unknown element ref '%s'. Run browser_snapshot first — "
                    "refs expire when the page changes." % ref)
        el.click()
        _CTX["refs"] = {}
        page.wait_for_timeout(800)
        current, title = page.url, page.title()
    return "Clicked %s. Now at %s — %s" % (ref, current, title)


def _browser_fill(args):
    ref = str(args.get("ref", "")).strip()
    text = str(args.get("text", ""))
    if not ref:
        return "browser_fill needs 'ref' (e.g. 'e3' from browser_snapshot)."
    with _LOCK:
        page = _ensure_page()
        el = _CTX["refs"].get(ref)
        if el is None:
            return ("Unknown element ref '%s'. Run browser_snapshot first — "
                    "refs expire when the page changes." % ref)
        el.fill(text)
    return "Filled %s with %d characters." % (ref, len(text))


def _browser_screenshot(args):
    full = bool(args.get("full_page", False))
    os.makedirs(_SHOTS_DIR, exist_ok=True)
    path = os.path.join(_SHOTS_DIR, "shot_%d.png" % int(time.time()))
    with _LOCK:
        page = _ensure_page()
        page.screenshot(path=path, full_page=full)
    return "Screenshot saved: %s" % path


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": ("Open a URL in the invisible headless browser. "
                            "Returns the page title, URL and a text preview. "
                            "Resets element refs."),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string",
                            "description": "URL to open (https:// added if missing)."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": ("List clickable/fillable elements on the current page "
                            "as [e1] [e2] ... refs. Call this before clicking "
                            "or filling anything."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": ("Click an element ref from browser_snapshot "
                            "(e.g. 'e3'). Page may change afterwards."),
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string",
                            "description": "Element ref like 'e3'."},
                },
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill an input element ref from browser_snapshot with text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string",
                            "description": "Element ref like 'e3'."},
                    "text": {"type": "string",
                             "description": "Text to type into the field."},
                },
                "required": ["ref", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": ("Capture the current page as a PNG file. Returns the "
                            "file path, which you can show the user."),
            "parameters": {
                "type": "object",
                "properties": {
                    "full_page": {"type": "boolean",
                                  "description": "Capture the whole scrollable page."},
                },
            },
        },
    },
]


def handle(tool_name, args, services=None):
    """Run one browser tool. Returns None for tools that aren't ours."""
    args = args or {}
    try:
        if tool_name == "browser_open":
            return _browser_open(args)
        if tool_name == "browser_snapshot":
            return _browser_snapshot(args)
        if tool_name == "browser_click":
            return _browser_click(args)
        if tool_name == "browser_fill":
            return _browser_fill(args)
        if tool_name == "browser_screenshot":
            return _browser_screenshot(args)
    except RuntimeError as e:
        return str(e)  # e.g. Playwright not installed — speakable guidance
    except Exception as e:
        return "Browser %s failed: %s" % (tool_name, e)
    return None

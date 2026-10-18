"""Everyday skill — the little tools a butler should just know.

  get_datetime  current date + time (the brain has no clock otherwise)
  calculate     safe arithmetic (LLMs are bad at math; this isn't)
  set_timer / list_timers / cancel_timer
                countdown timers with a spoken "done, sir"
  get_weather   wttr.in, no API key, optional location
  get_news      headlines via DuckDuckGo, optional topic
  define_word   dictionaryapi.dev, no API key
  translate     English <-> Hindi via MyMemory, no API key
  pick_one      decide between options ("pick a movie")

Timers speak through brain services["speak"] when the app provides it
(jarvis_app wires self._say); without it they still track state.

Stdlib + requests only.
"""

import ast
import itertools
import math
import operator
import random
import re
import threading
from datetime import datetime

import requests

SKILL_NAME = "everyday"
SKILL_DESCRIPTION = ("Everyday utilities: clock, calculator, timers, weather, "
                     "headlines, dictionary, translator, decisions.")

_UA = {"User-Agent": "curl/8"}

# ------------------------------------------------------------------ datetime
def _get_datetime(args):
    now = datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %I:%M %p ") + \
        f"{now.tzname()} ({now.strftime('%z')})"

# ----------------------------------------------------------------- calculate
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
          "tan": math.tan, "log": math.log, "log10": math.log10,
          "exp": math.exp, "abs": abs, "round": round,
          "floor": math.floor, "ceil": math.ceil}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("not a safe arithmetic expression")


def _calculate(args):
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return "calculate needs 'expression', e.g. '(100 - 37) / 3'."
    try:
        val = _eval(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return "That's a division by zero, sir."
    except Exception:
        return ("I can only calculate plain arithmetic, sir — numbers, "
                "+ - * / // % **, parentheses, and sqrt/sin/cos/log etc.")
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    return f"{expr} = {val}"

# -------------------------------------------------------------------- timers
_TIMERS = {}
_IDS = itertools.count(1)
_TLOCK = threading.Lock()


def _parse_duration(raw):
    """'90' | 90 | '5m' | '1h30m' | '10 seconds' -> seconds (int) or None."""
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    s = str(raw or "").strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return max(1, int(float(s)))
    total = 0.0
    for val, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|h|m|s)",
            s):
        total += float(val) * {"h": 3600, "m": 60, "s": 1}[unit[0]]
    return int(total) if total > 0 else None


def _human_secs(secs):
    h, r = divmod(int(secs), 3600)
    m, s = divmod(r, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s or not parts:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts)


def _set_timer(args, services):
    secs = _parse_duration(args.get("duration"))
    if not secs:
        return ("set_timer needs 'duration' — seconds or '5m', '1h30m', "
                "'10 seconds'.")
    label = str(args.get("label") or "timer").strip()[:80]
    tid = next(_IDS)

    def _fire():
        with _TLOCK:
            info = _TIMERS.get(tid)
            if not info:
                return
            info["done"] = True
        speak = (services or {}).get("speak")
        if callable(speak):
            try:
                speak(f"Timer done, sir — {label}.")
            except Exception:
                pass

    t = threading.Timer(secs, _fire)
    t.daemon = True
    with _TLOCK:
        _TIMERS[tid] = {"label": label, "seconds": secs,
                        "ends_at": datetime.now().timestamp() + secs,
                        "done": False, "timer": t}
    t.start()
    return f"Timer #{tid} '{label}' set for {_human_secs(secs)}."


def _list_timers(args):
    with _TLOCK:
        items = sorted(_TIMERS.items())
    if not items:
        return "No timers, sir."
    now = datetime.now().timestamp()
    lines = []
    for tid, info in items:
        if info["done"]:
            lines.append(f"#{tid} '{info['label']}' — done")
        else:
            left = max(0, int(info["ends_at"] - now))
            lines.append(f"#{tid} '{info['label']}' — {_human_secs(left)} left")
    return "\n".join(lines)


def _cancel_timer(args):
    raw = str(args.get("timer_id", "")).strip()
    if not raw.isdigit():
        return "cancel_timer needs 'timer_id' — see list_timers."
    tid = int(raw)
    with _TLOCK:
        info = _TIMERS.pop(tid, None)
    if not info:
        return f"No timer #{tid}, sir."
    try:
        info["timer"].cancel()
    except Exception:
        pass
    status = "had already finished" if info["done"] else "cancelled"
    return f"Timer #{tid} '{info['label']}' {status}."

# ------------------------------------------------------------------- weather
def _get_weather(args):
    loc = str(args.get("location", "") or "").strip()
    try:
        url = "https://wttr.in/"
        if loc:
            url += loc.replace(" ", "%20") + "/"
        r = requests.get(url, params={"format": "j1"}, timeout=8, headers=_UA)
        j = r.json()
        cc = (j.get("current_condition") or [{}])[0]
        desc = ((cc.get("weatherDesc") or [{}])[0]).get("Value") or "fair skies"
        temp, feels = cc.get("temp_C", "?"), cc.get("FeelsLikeC", "?")
        humidity = cc.get("humidity", "?")
        area = (j.get("nearest_area") or [{}])[0]
        place = ((area.get("areaName") or [{}])[0]).get("value", loc or "your area")
        return (f"Weather in {place}: {desc}, {temp}°C feeling like {feels}°C, "
                f"humidity {humidity}%.")
    except Exception as e:
        return f"Weather service unreachable, sir ({type(e).__name__})."

# ---------------------------------------------------------------------- news
def _get_news(args):
    topic = str(args.get("topic", "") or "").strip() or "top news today"
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            try:
                items = list(ddgs.news(topic, max_results=5))
            except Exception:
                items = list(ddgs.text(topic + " headlines", max_results=5))
        titles = [t for t in ((i.get("title") or "").strip() for i in items) if t][:4]
        if not titles:
            return "No headlines available just now, sir."
        return "Headlines: " + "; ".join(titles) + "."
    except Exception:
        return "News service unreachable, sir."

# ---------------------------------------------------------------- dictionary
def _define_word(args):
    word = str(args.get("word", "") or "").strip().split()[0:1]
    word = word[0] if word else ""
    if not word:
        return "define_word needs 'word'."
    try:
        r = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
            timeout=8, headers=_UA)
        if r.status_code != 200:
            return f"No definition found for '{word}', sir."
        entry = r.json()[0]
        phon = entry.get("phonetic", "")
        bits = []
        for meaning in entry.get("meanings", [])[:2]:
            pos = meaning.get("partOfSpeech", "")
            for d in meaning.get("definitions", [])[:2]:
                defi = d.get("definition", "")
                ex = d.get("example", "")
                bits.append(f"{pos}: {defi}" + (f" — e.g. '{ex}'" if ex else ""))
        if not bits:
            return f"No definition found for '{word}', sir."
        head = f"{entry.get('word', word)}" + (f" ({phon})" if phon else "")
        return head + " — " + " ".join(bits[:3])
    except Exception:
        return "Dictionary unreachable, sir."

# ---------------------------------------------------------------- translate
def _translate(args):
    text = str(args.get("text", "") or "").strip()
    target = str(args.get("target_lang", "hi") or "hi").strip().lower()
    source = str(args.get("source_lang", "en") or "en").strip().lower()
    if not text:
        return "translate needs 'text'."
    if target not in ("en", "hi") or source not in ("en", "hi"):
        return "I translate between English and Hindi, sir (target_lang 'en' or 'hi')."
    try:
        r = requests.get("https://api.mymemory.translated.net/get",
                         params={"q": text, "langpair": f"{source}|{target}"},
                         timeout=10, headers=_UA)
        j = r.json()
        out = ((j.get("responseData") or {}).get("translatedText") or "").strip()
        if not out:
            return "Translation service is busy, sir — try again."
        if "MYMEMORY WARNING" in out.upper() or "QUERY LENGTH LIMIT" in out.upper():
            return ("Translation service's free quota is used up for today, "
                    "sir — try again tomorrow.")
        return out
    except Exception:
        return "Translation service unreachable, sir."

# ------------------------------------------------------------------- pick one
def _pick_one(args):
    raw = args.get("options", "")
    if isinstance(raw, str):
        opts = [o.strip() for o in re.split(r"[,\n;]+", raw) if o.strip()]
    else:
        opts = [str(o).strip() for o in (raw or []) if str(o).strip()]
    if len(opts) < 2:
        return "pick_one needs at least two options, sir."
    return f"I choose: {random.choice(opts)} (from {len(opts)} options)."

# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "get_datetime",
        "description": ("Current date and time with timezone. Use before answering "
                        "anything time-sensitive — the brain has no clock otherwise."),
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "calculate",
        "description": ("Evaluate an arithmetic expression safely. Use for any math — "
                        "never do arithmetic from memory."),
        "parameters": {"type": "object",
                       "properties": {"expression": {
                           "type": "string",
                           "description": "e.g. '(100 - 37) / 3', 'sqrt(16)', '2**10'"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "set_timer",
        "description": "Start a countdown timer that announces when done.",
        "parameters": {"type": "object",
                       "properties": {
                           "duration": {"type": "string",
                                        "description": "Seconds or '5m', '1h30m', '10 seconds'"},
                           "label": {"type": "string",
                                     "description": "What the timer is for"}},
                       "required": ["duration"]}}},
    {"type": "function", "function": {
        "name": "list_timers",
        "description": "List active and finished timers.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "cancel_timer",
        "description": "Cancel a timer by its number from list_timers.",
        "parameters": {"type": "object",
                       "properties": {"timer_id": {
                           "type": "string",
                           "description": "Timer number, e.g. '2'"}},
                       "required": ["timer_id"]}}},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Current weather. Leave location empty for the PC's area.",
        "parameters": {"type": "object",
                       "properties": {"location": {
                           "type": "string",
                           "description": "City name, optional"}}}}},
    {"type": "function", "function": {
        "name": "get_news",
        "description": "Latest headlines, optionally about a topic.",
        "parameters": {"type": "object",
                       "properties": {"topic": {
                           "type": "string",
                           "description": "Topic, optional"}}}}},
    {"type": "function", "function": {
        "name": "define_word",
        "description": "English dictionary definition with pronunciation.",
        "parameters": {"type": "object",
                       "properties": {"word": {
                           "type": "string", "description": "The word"}},
                       "required": ["word"]}}},
    {"type": "function", "function": {
        "name": "translate",
        "description": "Translate between English and Hindi.",
        "parameters": {"type": "object",
                       "properties": {
                           "text": {"type": "string"},
                           "target_lang": {"type": "string",
                                           "description": "'hi' or 'en' (default 'hi')"},
                           "source_lang": {"type": "string",
                                           "description": "'en' or 'hi' (default 'en')"}},
                       "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "pick_one",
        "description": "Decide between options — pass a comma-separated list.",
        "parameters": {"type": "object",
                       "properties": {"options": {
                           "type": "string",
                           "description": "'pizza, biryani, pasta'"}},
                       "required": ["options"]}}},
]


def handle(tool_name, args, services=None):
    """Run one everyday tool. Returns None for tools that aren't ours."""
    args = args or {}
    try:
        if tool_name == "get_datetime":
            return _get_datetime(args)
        if tool_name == "calculate":
            return _calculate(args)
        if tool_name == "set_timer":
            return _set_timer(args, services)
        if tool_name == "list_timers":
            return _list_timers(args)
        if tool_name == "cancel_timer":
            return _cancel_timer(args)
        if tool_name == "get_weather":
            return _get_weather(args)
        if tool_name == "get_news":
            return _get_news(args)
        if tool_name == "define_word":
            return _define_word(args)
        if tool_name == "translate":
            return _translate(args)
        if tool_name == "pick_one":
            return _pick_one(args)
    except Exception as e:
        return f"Everyday tool {tool_name} failed: {e}"
    return None

"""Everyday skill — the little tools a butler should just know.

  get_datetime  current date + time (the brain has no clock otherwise)
  calculate     safe arithmetic (LLMs are bad at math; this isn't)
  set_timer / list_timers / cancel_timer
                countdown timers with a spoken "done, sir"
  get_weather   Open-Meteo (no key), hourly + 16-day, wttr.in fallback
  get_news      Currents API when a key is set, DuckDuckGo fallback
  convert_currency  ECB rates via Frankfurter, no API key
  web_search    Tavily agent-search when a key is set, DuckDuckGo fallback
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
_WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
        55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain",
        66: "freezing rain", 67: "freezing rain", 71: "light snow",
        73: "snow", 75: "heavy snow", 77: "snow grains",
        80: "light showers", 81: "showers", 82: "violent showers",
        85: "light snow showers", 86: "snow showers", 95: "thunderstorm",
        96: "storm with hail", 99: "storm with hail"}


def _resolve_latlon(loc: str):
    """(lat, lon, place). Geocodes a city, or IP-locates when loc is empty."""
    if loc:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": loc, "count": 1, "language": "en"},
                         timeout=10, headers=_UA)
        hits = r.json().get("results") or []
        if not hits:
            raise ValueError("no match")
        h = hits[0]
        name = h.get("name", loc)
        if h.get("country"):
            name += f", {h['country']}"
        return h["latitude"], h["longitude"], name
    r = requests.get("http://ip-api.com/json/", timeout=10, headers=_UA)
    j = r.json()
    return j["lat"], j["lon"], j.get("city") or "your area"


def _get_weather(args):
    loc = str(args.get("location", "") or "").strip()
    try:
        lat, lon, place = _resolve_latlon(loc)
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,"
                               "apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "timezone": "auto"},
            timeout=10, headers=_UA)
        j = r.json()
        cur = j.get("current", {})
        daily = j.get("daily", {})
        desc = _WMO.get(cur.get("weather_code"), "fair skies")
        hi = (daily.get("temperature_2m_max") or ["?"])[0]
        lo = (daily.get("temperature_2m_min") or ["?"])[0]
        return (f"Weather in {place}: {desc}, {cur.get('temperature_2m', '?')}°C "
                f"(feels {cur.get('apparent_temperature', '?')}°C), "
                f"humidity {cur.get('relative_humidity_2m', '?')}%, "
                f"wind {cur.get('wind_speed_10m', '?')} km/h. "
                f"Today: {lo}–{hi}°C.")
    except Exception:
        pass
    try:  # fallback: wttr.in
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
    key = _secret("currents_api_key")
    if key:
        try:
            params = {"apiKey": key, "language": "en"}
            if topic == "top news today":
                url = "https://api.currentsapi.services/v1/latest-news"
            else:
                url = "https://api.currentsapi.services/v1/search"
                params["keywords"] = topic
            r = requests.get(url, params=params, timeout=10, headers=_UA)
            arts = r.json().get("news") or []
            titles = [a.get("title") for a in arts if a.get("title")][:4]
            if titles:
                return "Headlines: " + "; ".join(titles) + "."
        except Exception:
            pass
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

# ------------------------------------------------------------------ currency
def _convert_currency(args):
    amount = str(args.get("amount", "1") or "1").strip()
    frm = str(args.get("from", "USD") or "USD").strip().upper()
    to = str(args.get("to", "INR") or "INR").strip().upper()
    try:
        val = float(amount.replace(",", ""))
    except Exception:
        return "Give me a number to convert, sir."
    try:
        r = requests.get("https://api.frankfurter.app/latest",
                         params={"amount": val, "from": frm, "to": to},
                         timeout=10, headers=_UA)
        rate = (r.json().get("rates") or {}).get(to)
        if rate is None:
            raise ValueError("unknown currency")
        return f"{val:g} {frm} = {rate:,.2f} {to}, sir (ECB daily rate)."
    except Exception as e:
        return f"Couldn't convert that, sir ({type(e).__name__})."

# ---------------------------------------------------------------- web search
def _web_search(args):
    q = str(args.get("query", "") or "").strip()
    if not q:
        return "What should I search for, sir?"
    key = _secret("tavily_api_key")
    if key:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": q, "max_results": 5,
                      "include_answer": False},
                timeout=15, headers=_UA)
            res = r.json().get("results") or []
            lines = [f"— {x.get('title')}: {(x.get('content') or '')[:220]}"
                     for x in res[:4] if x.get("title")]
            if lines:
                return f"Search results for '{q}', sir:\n" + "\n".join(lines)
        except Exception:
            pass
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            items = list(ddgs.text(q, max_results=5))
        lines = [f"— {i.get('title')}: {(i.get('body') or '')[:220]}"
                 for i in items[:4] if i.get("title")]
        if not lines:
            return "Nothing found, sir."
        return f"Search results for '{q}', sir:\n" + "\n".join(lines)
    except Exception:
        return "Search unreachable, sir."


def _secret(name: str) -> str:
    """Read one key from secrets.local.yaml without importing the Qt UI."""
    try:
        import yaml
        from paths import user_file
        with open(user_file("secrets.local.yaml"), encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get(name) or "").strip()
    except Exception:
        return ""

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
    {"type": "function", "function": {
        "name": "convert_currency",
        "description": "Convert money between currencies at real ECB rates.",
        "parameters": {"type": "object",
                       "properties": {"amount": {"type": "string"},
                                      "from": {"type": "string",
                                               "description": "'USD'"},
                                      "to": {"type": "string",
                                             "description": "'INR'"}},
                       "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": ("Agent-grade web search (Tavily when a key is set, "
                        "DuckDuckGo otherwise). Use for anything the news "
                        "tool doesn't cover."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
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
        if tool_name == "convert_currency":
            return _convert_currency(args)
        if tool_name == "web_search":
            return _web_search(args)
    except Exception as e:
        return f"Everyday tool {tool_name} failed: {e}"
    return None

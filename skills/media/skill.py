"""Media skill — movies/TV via TMDB and YouTube search.

Keys live in secrets.local.yaml (Settings → API Keys), never in code.
Both are free with no credit card:
- TMDB: themoviedb.org → Settings → API → instant key
- YouTube: Google Cloud Console → enable YouTube Data API v3 → API key

Stdlib + requests only. Lazy imports throughout.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_NAME = "media"
SKILL_DESCRIPTION = ("Movies and TV (TMDB): search titles, trending, details. "
                     "YouTube: proper video search to pair with transcripts.")


def _secret(name: str) -> str:
    try:
        import yaml
        from paths import user_file
        with open(user_file("secrets.local.yaml"), encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get(name) or "").strip()
    except Exception:
        return ""


_UA = {"User-Agent": "curl/8"}


def _tmdb_search(args):
    q = str(args.get("query", "") or "").strip()
    if not q:
        return "Which movie or show, sir?"
    key = _secret("tmdb_api_key")
    if not key:
        return ("TMDB needs a free key, sir — themoviedb.org, sign up, "
                "Settings → API → paste it in Settings → API Keys.")
    try:
        import requests
        r = requests.get("https://api.themoviedb.org/3/search/multi",
                         params={"api_key": key, "query": q},
                         timeout=12, headers=_UA)
        res = r.json().get("results") or []
        lines = []
        for x in res[:5]:
            title = x.get("title") or x.get("name") or "?"
            year = (x.get("release_date") or x.get("first_air_date") or "")[:4]
            stars = x.get("vote_average")
            ov = (x.get("overview") or "")[:160]
            lines.append(f"— {title} ({year}) ★{stars}: {ov}")
        return f"On TMDB for '{q}', sir:\n" + "\n".join(lines) if lines \
            else f"Nothing on TMDB for '{q}', sir."
    except Exception as e:
        return f"TMDB didn't answer, sir: {type(e).__name__}."


def _tmdb_trending(args):
    key = _secret("tmdb_api_key")
    if not key:
        return ("TMDB needs a free key, sir — themoviedb.org → API → "
                "paste it in Settings → API Keys.")
    try:
        import requests
        r = requests.get("https://api.themoviedb.org/3/trending/movie/week",
                         params={"api_key": key}, timeout=12, headers=_UA)
        res = r.json().get("results") or []
        lines = []
        for x in res[:8]:
            title = x.get("title") or "?"
            year = (x.get("release_date") or "")[:4]
            lines.append(f"— {title} ({year}) ★{x.get('vote_average')}")
        return "Trending movies this week, sir:\n" + "\n".join(lines)
    except Exception as e:
        return f"TMDB didn't answer, sir: {type(e).__name__}."


def _youtube_search(args):
    q = str(args.get("query", "") or "").strip()
    if not q:
        return "What should I find on YouTube, sir?"
    key = _secret("youtube_api_key")
    if not key:
        return ("YouTube search needs a free API key, sir — Google Cloud "
                "Console → enable 'YouTube Data API v3' → create an API key → "
                "paste it in Settings → API Keys.")
    try:
        import requests
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
                         params={"part": "snippet", "type": "video",
                                 "maxResults": 5, "q": q, "key": key},
                         timeout=12, headers=_UA)
        items = r.json().get("items") or []
        lines = []
        for it in items:
            vid = (it.get("id") or {}).get("videoId", "")
            sn = it.get("snippet") or {}
            lines.append(f"— {sn.get('title')} [{sn.get('channelTitle')}] "
                         f"https://youtu.be/{vid}")
        if not lines:
            return f"Nothing on YouTube for '{q}', sir."
        return (f"On YouTube for '{q}', sir:\n" + "\n".join(lines) +
                "\nAsk me to watch any of them and I'll read the transcript.")
    except Exception as e:
        return f"YouTube didn't answer, sir: {type(e).__name__}."


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "tmdb_search",
        "description": ("Search movies and TV shows: ratings, year, overview. "
                        "Needs the free TMDB key."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "tmdb_trending",
        "description": "This week's trending movies with ratings.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "youtube_search",
        "description": ("Proper YouTube video search. Pair with "
                        "youtube_transcript to find-then-watch."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        fn = {"tmdb_search": _tmdb_search,
              "tmdb_trending": _tmdb_trending,
              "youtube_search": _youtube_search}.get(tool_name)
        if fn is None:
            return None
        return fn(args)
    except Exception as e:
        return f"Sorry, sir — that hit a snag: {e}"

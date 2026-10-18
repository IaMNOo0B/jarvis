"""Scout mode — parallel research agents for JARVIS.

"Jarvis, scout GitHub for screen-aware assistants and compare" ->
one tool call fans out: parallel searches across angles, top sources read
in parallel (READMEs included), GitHub repos enriched with stars /
description / language, and a comparison digest comes back for the brain
to rank and present.

Reuses the core research engine (actions.parallel_multi_search /
parallel_multi_browse). Stdlib + requests only.
"""

import re

import requests

SKILL_NAME = "scout"
SKILL_DESCRIPTION = ("Parallel research scouts: searches a topic from multiple "
                     "angles at once, reads the top sources, and returns a "
                     "comparison digest.")

_DEFAULT_ANGLES = ["overview", "best options", "comparison", "github"]
_GH_UA = {"User-Agent": "jarvis-scout",
          "Accept": "application/vnd.github+json"}


def _search(queries, per_query=4):
    from actions import parallel_multi_search
    return parallel_multi_search(queries, max_results_per_query=per_query)


def _browse(urls, chars=2500):
    from actions import parallel_multi_browse
    return parallel_multi_browse(urls, max_chars_per_page=chars)


def _extract_urls(search_output):
    """Pull URLs from the 'URL: ...' lines, deduped, github first."""
    seen, urls = set(), []
    for u in re.findall(r"URL:\s*(\S+)", search_output or ""):
        u = u.rstrip(").,")
        if u and u not in seen and u.startswith(("http://", "https://")):
            seen.add(u)
            urls.append(u)
    urls.sort(key=lambda u: 0 if "github.com/" in u else 1)  # stable: repos first
    return urls


def _github_meta(url):
    """Unauthenticated repo metadata: stars/description/language. None on failure."""
    m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s?#]+)", url or "")
    if not m:
        return None
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    if owner in ("topics", "orgs", "settings"):  # not a repo page
        return None
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}",
                         timeout=8, headers=_GH_UA)
        if r.status_code != 200:
            return None
        j = r.json()
        return {"path": f"{owner}/{repo}",
                "stars": j.get("stargazers_count", 0),
                "desc": (j.get("description") or "").strip(),
                "lang": j.get("language") or "",
                "updated": str(j.get("pushed_at") or "")[:10]}
    except Exception:
        return None


def _clean(text, limit=450):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _split_browse(browse_output):
    """{'url': content} from the '--- SOURCE: url ---' sections."""
    parts = re.split(r"--- SOURCE: (\S+) ---", browse_output or "")
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out


def _scout_research(args):
    topic = str(args.get("topic", "") or "").strip()
    if not topic:
        return "scout_research needs 'topic' — what should my scouts look into?"
    angles = args.get("angles") or _DEFAULT_ANGLES
    angles = [str(a).strip() for a in angles if str(a).strip()][:4] or _DEFAULT_ANGLES
    try:
        max_sources = min(8, max(2, int(args.get("max_sources", 5))))
    except (TypeError, ValueError):
        max_sources = 5

    queries = [f"{topic} {a}" for a in angles]
    search_out = _search(queries)
    urls = _extract_urls(search_out)[:max_sources]
    if not urls:
        return (f"My scouts found nothing on '{topic}', sir. "
                f"Try different words?")
    contents = _split_browse(_browse(urls))

    lines = [f"SCOUT REPORT: {topic} ({len(urls)} sources)"]
    for i, url in enumerate(urls, 1):
        meta = _github_meta(url)
        if meta:
            stars = f"⭐{meta['stars']:,}" if meta["stars"] else "⭐?"
            head = f"{meta['path']} — {stars}"
            if meta["lang"]:
                head += f" · {meta['lang']}"
            if meta["updated"]:
                head += f" · updated {meta['updated']}"
            lines.append(f"{i}. {head}")
            if meta["desc"]:
                lines.append(f'   "{_clean(meta["desc"], 200)}"')
        else:
            title = url.split("//", 1)[-1].split("/", 1)[0]
            lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
        key = _clean(contents.get(url, ""))
        lines.append(f"   Key points: {key}" if key else "   Key points: (page unreadable)")
    lines.append("Rank these for the user with a clear winner and why.")
    return "\n".join(lines)


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "scout_research",
        "description": (
            "Send out parallel research scouts on a topic. Searches multiple "
            "angles at once, reads the top sources in parallel (GitHub READMEs "
            "included), enriches repos with stars/description/language, and "
            "returns a comparison digest. Use when the user says 'scout', "
            "'research and compare', or 'find the best X'."),
        "parameters": {"type": "object",
                       "properties": {
                           "topic": {"type": "string",
                                     "description": "What to research, e.g. 'screen-aware AI assistants'"},
                           "angles": {"type": "string",
                                      "description": "Comma-separated search angles (default: overview, best options, comparison, github)"},
                           "max_sources": {"type": "integer",
                                           "description": "Sources to read, 2-8 (default 5)"}},
                       "required": ["topic"]}}},
]


def handle(tool_name, args, services=None):
    """Run the scout. Returns None for tools that aren't ours."""
    args = args or {}
    try:
        if tool_name == "scout_research":
            angles = args.get("angles")
            if isinstance(angles, str):
                args = dict(args, angles=[a for a in
                                          (x.strip() for x in angles.split(","))
                                          if a])
            return _scout_research(args)
    except Exception as e:
        return f"Scout failed, sir: {e}"
    return None

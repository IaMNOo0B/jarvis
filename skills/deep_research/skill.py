"""Deep research — multi-round investigation, not just one search.

scout_research does one broad round. deep_research goes further: up to 3
rounds, each with its own angles (breadth → depth → latest/criticism),
reading fresh sources every round and compiling a dossier the brain then
synthesizes. Use when the user says 'research deeply', 'investigate',
or needs more than a quick scout.

Reuses actions' parallel search/browse + scout's URL helpers.
Stdlib + requests only.
"""

from skills.scout.skill import _clean, _extract_urls, _github_meta, _split_browse

SKILL_NAME = "deep_research"
SKILL_DESCRIPTION = ("Multi-round deep investigation on a topic: searches, reads, "
                     "then searches again with deeper angles, and returns a "
                     "compiled dossier with sources.")

_ROUND_ANGLES = [
    ["overview", "best options", "comparison", "github"],
    ["in-depth guide", "tutorial", "documentation", "vs"],
    ["latest 2026", "expert review", "criticism", "alternatives"],
]


def _search(queries, per_query=4):
    from actions import parallel_multi_search
    return parallel_multi_search(queries, max_results_per_query=per_query)


def _browse(urls, chars=3000):
    from actions import parallel_multi_browse
    return parallel_multi_browse(urls, max_chars_per_page=chars)


def _deep_research(args):
    topic = str(args.get("topic", "") or "").strip()
    if not topic:
        return "deep_research needs 'topic' — what should I investigate?"
    try:
        depth = min(3, max(1, int(args.get("depth", 2))))
    except (TypeError, ValueError):
        depth = 2
    try:
        per_round = min(6, max(2, int(args.get("sources_per_round", 4))))
    except (TypeError, ValueError):
        per_round = 4

    seen, dossier = set(), []
    for r in range(depth):
        queries = [f"{topic} {a}" for a in _ROUND_ANGLES[r]]
        urls = [u for u in _extract_urls(_search(queries)) if u not in seen]
        urls = urls[:per_round]
        if not urls:
            break
        seen.update(urls)
        contents = _split_browse(_browse(urls))
        for u in urls:
            dossier.append((u, _github_meta(u), contents.get(u, "")))

    if not dossier:
        return f"Deep research on '{topic}' turned up nothing, sir."

    lines = [f"DEEP RESEARCH: {topic} ({len(dossier)} sources, {depth} rounds)",
             "", "## Key findings"]
    for i, (url, meta, content) in enumerate(dossier, 1):
        if meta:
            label = f"{meta['path']} (⭐{meta['stars']:,})"
        else:
            label = url.split("//", 1)[-1].split("/", 1)[0]
        lines.append(f"### {i}. {label}")
        key = _clean(content, 550)
        lines.append(key or "(page unreadable)")
        lines.append("")
    lines.append("## Sources")
    for i, (url, meta, _) in enumerate(dossier, 1):
        lines.append(f"{i}. {url}")
    lines.extend(["", "## Suggested follow-ups",
                  f"- Ask me to scout '{topic}' against a specific alternative.",
                  f"- Ask me to go deeper on any source above by number."])
    return "\n".join(lines)


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "deep_research",
        "description": ("Investigate a topic across multiple rounds (breadth, then "
                        "depth, then latest/criticism) and return a compiled "
                        "dossier with sources. For 'research deeply' requests — "
                        "heavier than scout_research."),
        "parameters": {"type": "object",
                       "properties": {
                           "topic": {"type": "string"},
                           "depth": {"type": "integer",
                                     "description": "Rounds 1-3 (default 2)"},
                           "sources_per_round": {"type": "integer",
                                                 "description": "Sources per round, 2-6 (default 4)"}},
                       "required": ["topic"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "deep_research":
            return _deep_research(args)
    except Exception as e:
        return f"Deep research failed, sir: {e}"
    return None

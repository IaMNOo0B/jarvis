# Scout skill

"Jarvis, scout GitHub for X and compare" — one tool call fans out:

1. `parallel_multi_search` across angles (overview, best options,
   comparison, github — or caller-supplied angles)
2. URLs extracted, GitHub repos first, top N kept
3. `parallel_multi_browse` reads them in parallel (READMEs included)
4. Repo URLs enriched via the public GitHub API
   (stars / description / language / last push — no key needed)
5. A comparison digest comes back; the brain ranks and presents

The tool does the legwork, the brain does the judgment.
The persona (`persona.py`) tells JARVIS to reach for `scout_research`
on "scout / research and compare / find the best X" requests.

Stdlib + requests only.

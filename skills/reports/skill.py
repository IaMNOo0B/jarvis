"""Reports — JARVIS makes things you can open, not just chat text.

make_report(title, body): markdown in, styled dark-theme HTML page out,
saved under the user data dir and auto-opened in the browser on Windows.
The brain's equivalent of my artifacts. Stdlib only.
"""

import html
import os
import re
import time

SKILL_NAME = "reports"
SKILL_DESCRIPTION = ("Create styled HTML reports/documents from markdown and "
                     "open them. For 'make me a report/page/document' requests.")


def _md_to_html(md):
    """Compact markdown → HTML: headings, bold/italic/code, lists, quotes, links."""
    out, in_list, in_code, code_buf = [], False, False, []
    for line in (md or "").split("\n"):
        s = line.rstrip()
        if s.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        def inline(t):
            t = html.escape(t)
            t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
            t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
            t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
            t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
            return t

        if not s.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", s)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"^(\-|\*)\s+", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(re.sub(r'^(\-|\*)\s+', '', s))}</li>")
            continue
        if s.strip().startswith(">"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{inline(s.strip()[1:].strip())}</blockquote>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
body{{background:#06090d;color:#d7e6f0;font-family:Segoe UI,Arial,sans-serif;
max-width:760px;margin:0 auto;padding:32px 20px;line-height:1.65}}
h1,h2,h3{{color:#7df3ff}} a{{color:#7df3ff}}
code{{background:#0d1620;padding:2px 6px;border-radius:4px;color:#aef}}
pre{{background:#0d1620;padding:14px;border-radius:8px;overflow-x:auto}}
pre code{{background:none;padding:0}}
blockquote{{border-left:3px solid #7df3ff;margin:12px 0;padding:6px 14px;color:#9db8c8}}
ul{{padding-left:22px}} li{{margin:4px 0}}
.footer{{margin-top:40px;color:#5b7183;font-size:12px}}
</style></head><body>
{body}
<div class="footer">Prepared by JARVIS</div>
</body></html>"""


def _make_report(args):
    title = str(args.get("title", "") or "").strip() or "JARVIS report"
    body = str(args.get("body", "") or "").strip()
    if not body:
        return "make_report needs 'body' (markdown)."
    open_it = str(args.get("open", "yes")).lower() not in ("no", "false", "0")

    from paths import data_dir
    rdir = os.path.join(data_dir(), "reports")
    os.makedirs(rdir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "report"
    path = os.path.join(rdir, f"{slug}-{int(time.time())}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_PAGE.format(title=html.escape(title),
                             body=_md_to_html(body)))
    if open_it:
        try:
            os.startfile(path)  # Windows
        except Exception:
            pass
    return f"Report ready, sir: {path}"


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "make_report",
        "description": ("Create a styled HTML report/document from markdown and "
                        "open it. Use for 'make me a report/page/document'."),
        "parameters": {"type": "object",
                       "properties": {
                           "title": {"type": "string"},
                           "body": {"type": "string",
                                    "description": "Markdown content"},
                           "open": {"type": "string",
                                    "description": "'yes' (default) opens it at once"}},
                       "required": ["title", "body"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "make_report":
            return _make_report(args)
    except Exception as e:
        return f"Report failed, sir: {e}"
    return None

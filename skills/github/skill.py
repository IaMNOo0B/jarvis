"""GitHub hands — read any public repo, file issues on yours.

Reading is unauthenticated (public API, 60 req/hr). Creating issues needs a
token: GITHUB_TOKEN env or github_token in secrets.local.yaml (same file the
settings panel writes). Stdlib + requests only.
"""

import base64

import requests

SKILL_NAME = "github"
SKILL_DESCRIPTION = ("GitHub: read files from any public repo, list issues, "
                     "and create issues (needs a token).")

_API = "https://api.github.com"
_UA = {"User-Agent": "jarvis", "Accept": "application/vnd.github+json"}


def _token():
    import os
    val = os.environ.get("GITHUB_TOKEN", "").strip()
    if val:
        return val
    try:
        import yaml
        from paths import user_file
        sp = user_file("secrets.local.yaml")
        if os.path.isfile(sp):
            with open(sp, "r", encoding="utf-8") as f:
                return str((yaml.safe_load(f) or {}).get("github_token") or "").strip()
    except Exception:
        pass
    return ""


def _api_call(path, token=None, method="GET", data=None):
    headers = dict(_UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.request(method, _API + path, headers=headers,
                             json=data, timeout=10)
    except Exception as e:
        return None, f"GitHub unreachable ({type(e).__name__})"
    if r.status_code in (401, 403):
        return None, "GitHub refused (bad token or rate limit), sir."
    if r.status_code == 404:
        return None, "Not found on GitHub, sir — check owner/repo/path."
    if r.status_code >= 400:
        return None, f"GitHub error {r.status_code}, sir."
    try:
        return r.json(), None
    except Exception:
        return None, "GitHub sent an unreadable reply, sir."


def _read_file(args):
    repo = str(args.get("repo", "") or "").strip().strip("/")
    path = str(args.get("path", "") or "").strip().lstrip("/")
    if not repo or not path or "/" not in repo:
        return "github_read_file needs 'repo' (owner/name) and 'path'."
    j, err = _api_call(f"/repos/{repo}/contents/{path}")
    if err:
        return err
    if not isinstance(j, dict) or j.get("encoding") != "base64":
        return "That path isn't a single file, sir."
    try:
        text = base64.b64decode(j["content"]).decode("utf-8", "replace")
    except Exception:
        return "Couldn't decode that file, sir."
    if len(text) > 6000:
        text = text[:6000] + "\n… (truncated)"
    return f"{repo}/{path}:\n{text}"


def _list_issues(args):
    repo = str(args.get("repo", "") or "").strip().strip("/")
    if not repo or "/" not in repo:
        return "github_list_issues needs 'repo' (owner/name)."
    j, err = _api_call(f"/repos/{repo}/issues",
                       token=_token() or None,
                       )
    if err:
        return err
    items = [i for i in (j or []) if "pull_request" not in i][:10]
    if not items:
        return f"No open issues on {repo}, sir."
    lines = [f"Open issues on {repo}:"]
    for i in items:
        lines.append(f"#{i.get('number')} {i.get('title')} ({i.get('html_url')})")
    return "\n".join(lines)


def _create_issue(args):
    repo = str(args.get("repo", "") or "").strip().strip("/")
    title = str(args.get("title", "") or "").strip()
    body = str(args.get("body", "") or "").strip()
    if not repo or "/" not in repo or not title:
        return "github_create_issue needs 'repo' (owner/name) and 'title'."
    token = _token()
    if not token:
        return ("Creating issues needs a GitHub token, sir — put github_token "
                "in secrets.local.yaml or set GITHUB_TOKEN.")
    j, err = _api_call(f"/repos/{repo}/issues", token=token, method="POST",
                       data={"title": title, "body": body})
    if err:
        return err
    return f"Issue created, sir: {j.get('html_url')}"


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "github_read_file",
        "description": "Read a file from any public GitHub repo.",
        "parameters": {"type": "object",
                       "properties": {
                           "repo": {"type": "string", "description": "owner/name"},
                           "path": {"type": "string", "description": "file path in the repo"}},
                       "required": ["repo", "path"]}}},
    {"type": "function", "function": {
        "name": "github_list_issues",
        "description": "List open issues on a repo (pull requests excluded).",
        "parameters": {"type": "object",
                       "properties": {"repo": {"type": "string", "description": "owner/name"}},
                       "required": ["repo"]}}},
    {"type": "function", "function": {
        "name": "github_create_issue",
        "description": "Create an issue on a repo. Needs a GitHub token.",
        "parameters": {"type": "object",
                       "properties": {
                           "repo": {"type": "string", "description": "owner/name"},
                           "title": {"type": "string"},
                           "body": {"type": "string", "description": "Optional details"}},
                       "required": ["repo", "title"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        if tool_name == "github_read_file":
            return _read_file(args)
        if tool_name == "github_list_issues":
            return _list_issues(args)
        if tool_name == "github_create_issue":
            return _create_issue(args)
    except Exception as e:
        return f"GitHub tool failed, sir: {e}"
    return None

"""
Store JARVIS's online-brain API key — once, safely.

    python set_cloud_key.py YOUR_GEMINI_API_KEY
    python set_cloud_key.py --test          # ping Gemini with the stored key

The key is written to secrets.local.yaml (never commit it; the README's
troubleshooting section covers deletion). brain.py reads it automatically,
so no environment variables are required.

Get a free key at https://aistudio.google.com/apikey
"""

import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(BASE, "secrets.local.yaml")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-3.8-flash"


def _load_yaml(text: str) -> dict:
    import yaml
    return yaml.safe_load(text) or {}


def _dump_yaml(data: dict) -> str:
    import yaml
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=True)


def store_key(key: str) -> None:
    key = key.strip()
    data = {}
    if os.path.isfile(SECRETS):
        try:
            data = _load_yaml(open(SECRETS, encoding="utf-8").read()) or {}
        except Exception:
            data = {}
    data["gemini_api_key"] = key
    with open(SECRETS, "w", encoding="utf-8") as f:
        f.write(_dump_yaml(data))
    print(f"[key] stored in secrets.local.yaml ({len(key)} chars, "
          f"starts {key[:4]}…)")


def get_key() -> str:
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    if os.path.isfile(SECRETS):
        try:
            data = _load_yaml(open(SECRETS, encoding="utf-8").read()) or {}
            for k in ("gemini_api_key", "cloud_api_key", "api_key"):
                v = str(data.get(k) or "").strip()
                if v:
                    return v
        except Exception:
            pass
    return ""


def test_key() -> int:
    key = get_key()
    if not key:
        print("[key] no key found — run:  python set_cloud_key.py YOUR_KEY")
        return 1
    print(f"[key] testing Gemini with {'env' if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') else 'secrets.local.yaml'} key ({key[:4]}…)")
    try:
        import requests
        r = requests.post(
            GEMINI_URL,
            json={"model": GEMINI_MODEL,
                  "messages": [{"role": "user",
                                "content": "Reply with exactly: JARVIS online"}]},
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[FAIL] HTTP {r.status_code}: {r.text[:300]}")
            return 1
        msg = r.json()["choices"][0]["message"]
        print(f"[PASS] Gemini replied: {msg.get('content')!r} "
              f"(model {GEMINI_MODEL})")
        # second call: verify function calling works end to end
        tools = [{"type": "function", "function": {
            "name": "get_time", "description": "Get current time",
            "parameters": {"type": "object", "properties": {}}}}]
        r2 = requests.post(
            GEMINI_URL,
            json={"model": GEMINI_MODEL, "tools": tools, "tool_choice": "auto",
                  "messages": [{"role": "user",
                                "content": "What time is it? Use the tool."}]},
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if r2.status_code != 200:
            print(f"[FAIL] tool call HTTP {r2.status_code}: {r2.text[:300]}")
            return 1
        m2 = r2.json()["choices"][0]["message"]
        tcs = m2.get("tool_calls") or []
        if tcs:
            print(f"[PASS] function calling works — model requested "
                  f"{tcs[0]['function']['name']}()")
        else:
            print(f"[WARN] no tool call in reply (model answered directly): "
                  f"{(m2.get('content') or '')[:80]!r}")
        print("[key] online brain ready — launch JARVIS normally.")
        return 0
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}")
        return 1


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "--test":
        return test_key()
    if len(args) != 1 or args[0].startswith("-"):
        print("usage: python set_cloud_key.py <GEMINI_API_KEY> | --test")
        return 2
    store_key(args[0])
    return test_key()


if __name__ == "__main__":
    sys.exit(main())

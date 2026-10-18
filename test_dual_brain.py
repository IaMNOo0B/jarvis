"""
JARVIS dual-brain + desktop launcher verification.

    python test_dual_brain.py

Exit code 0 = pass. Steps 1-8 are offline logic tests (they run anywhere);
live steps (Gemini round trip, cross-brain consults) run only when a key /
Ollama are actually available and are reported as SKIP otherwise.
"""

import json
import os
import struct
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

FAILS = []
SKIPS = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        FAILS.append(name)


def skip(name, why):
    print(f"[SKIP] {name} — {why}", flush=True)
    SKIPS.append(name)


def make_engine(cfg_overrides=None, key=None):
    from brain import BrainEngine, load_config
    cfg = load_config()
    for k, v in (cfg_overrides or {}).items():
        cfg.setdefault(k, {}).update(v)
    engine = BrainEngine(cfg=cfg)
    if key:
        engine.cloud_key = key          # simulate a configured key
    return engine


# ---------------------------------------------------------------- 1. config
def t_config():
    e = make_engine()
    check("provider defaults to gemini", e.provider == "gemini", e.provider)
    check("gemini base url resolved",
          e.cloud_base.endswith("generativelanguage.googleapis.com/v1beta/openai"),
          e.cloud_base)
    check("gemini model defaulted", e.cloud_model == "gemini-3.8-flash", e.cloud_model)
    check("mode is dual-brain aware", e.mode in ("local_first", "cloud_first"), e.mode)
    check("consult budget loaded", e.consult_budget_max >= 1 and e.consult_rounds >= 1,
          f"budget={e.consult_budget_max} rounds={e.consult_rounds}")


# ------------------------------------------------------- 2. tool visibility
def t_tool_visibility():
    cloudless = make_engine()
    check("local brain sees NO consult tool when cloud unconfigured",
          not any("consult" in t["function"]["name"]
                  for t in cloudless._tools_for("local")))
    e = make_engine(key="fake-key")
    names = [t["function"]["name"] for t in e._tools_for("local")]
    check("local brain gets consult_online_brain when key present",
          "consult_online_brain" in names and "consult_local_brain" not in names,
          ",".join(n for n in names if "consult" in n) or "no consult tool")
    names = [t["function"]["name"] for t in e._tools_for("cloud")]
    check("cloud brain gets consult_local_brain, never consult_online",
          "consult_local_brain" in names and "consult_online_brain" not in names)
    names = [t["function"]["name"] for t in e._tools_for("cloud", allow_consult=False)]
    check("sub-turns run with consult tools stripped",
          not any("consult" in n for n in names))
    base = [t["function"]["name"] for t in e._tools_for("local")]
    check("both brains share the same base toolset",
          all(t in base for t in ("run_diagnostics", "system_control",
                                  "web_search", "execute_code")),
          f"{len(base)} tools")


# ------------------------------------------------------------- 3. guards
def t_guards():
    e = make_engine(key="fake")
    e._consult_depth = 1
    r = e._run_consult("consult_online_brain", {"question": "hi"})
    check("depth guard blocks nested consults",
          "disabled inside a consultation" in r, r[:70])
    e._consult_depth = 0
    e._consult_used = e.consult_budget_max
    r = e._run_consult("consult_online_brain", {"question": "hi"})
    check("budget guard blocks excess consults", "budget" in r, r[:70])
    e._consult_used = 0
    cloudless = make_engine()
    r = cloudless._run_consult("consult_online_brain", {"question": "hi"})
    check("unconfigured consult returns actionable message",
          "set_cloud_key" in r, r[:90])
    check("failed consult does not burn budget", cloudless._consult_used == 0)
    r = e._run_consult("consult_online_brain", {"question": ""})
    check("empty question rejected", "no question" in r, r[:70])


# -------------------------------------------------- 4. consult flow (stub)
def t_consult_flow():
    e = make_engine(key="fake")
    seen = {}

    def stub_sub(question, focus, provider):
        seen.update(question=question, focus=focus, provider=provider)
        return "stub answer from the other brain"

    e._sub_turn = stub_sub
    r = e._run_consult("consult_online_brain",
                       {"question": "what is 2+2?", "focus": "execute"})
    check("consult routes to the cloud brain",
          seen.get("provider") == "cloud" and seen.get("focus") == "execute",
          str(seen))
    check("result labelled with brain origin",
          "[Gemini (online) brain answered]" in r and "stub answer" in r, r[:80])
    check("budget consumed after consult", e._consult_used == 1)
    check("depth restored after consult", e._consult_depth == 0)

    e2 = make_engine(key="fake")
    e2._sub_turn = lambda q, f, p: "local stub"
    r = e2._run_consult("consult_local_brain", {"question": "x"})
    check("consult_local routes to the local brain",
          "[local core brain answered]" in r, r[:80])


# ------------------------------------------------ 5. sub-turn loop (stub)
def t_sub_turn_loop():
    e = make_engine(key="fake")
    calls = {"tools": [], "rounds": 0}

    def stub_cloud(force_no_tools=False, messages=None, tools=None):
        calls["rounds"] += 1
        calls["tools"].append([t["function"]["name"] for t in (tools or [])])
        if calls["rounds"] == 1:
            return {"content": "", "tool_calls": [{
                "id": "sub1", "type": "function",
                "function": {"name": "run_diagnostics", "arguments": "{}"}}]}, None
        return {"content": "All nominal, sir — subsystems verified."}, None

    ran = []
    e._call_cloud = stub_cloud              # no network in this test
    import brain as brain_mod
    orig = brain_mod.execute_tools_in_parallel
    brain_mod.execute_tools_in_parallel = lambda tcs, services, emit: (
        ran.append(tcs[0]["function"]["name"]) or ["diag ok"])
    try:
        out = e._sub_turn("check the machine", "execute", "cloud")
    finally:
        brain_mod.execute_tools_in_parallel = orig
    check("sub-turn ran a tool then answered",
          out.startswith("All nominal") and ran == ["run_diagnostics"],
          out[:60])
    check("sub-turn tools exclude consultation",
          all(not any(n.startswith("consult") for n in ts)
              for ts in calls["tools"]),
          str(calls["tools"]))
    check("sub-turn bounded by consult_rounds",
          calls["rounds"] <= e.consult_rounds, f"{calls['rounds']} calls")


# ------------------------------------------- 6. provider message formatting
def t_message_prep():
    from brain import BrainEngine
    history = [
        {"role": "system", "content": "x"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "web_search",
                                      "arguments": {"query": "q"}}}]},
        {"role": "tool", "content": "results", "tool_name": "web_search",
         "tool_call_id": "c1"},
    ]
    out = BrainEngine._prepare(history, "openai")
    check("openai/gemini: tool_name stripped (Gemini rejects extras)",
          "tool_name" not in out[2])
    check("openai/gemini: tool_call_id preserved",
          out[2].get("tool_call_id") == "c1")
    check("openai/gemini: arguments JSON-stringified",
          out[1]["tool_calls"][0]["function"]["arguments"] == json.dumps({"query": "q"}))
    out = BrainEngine._prepare(history, "ollama")
    check("ollama: arguments stay dicts",
          isinstance(out[1]["tool_calls"][0]["function"]["arguments"], dict))
    check("ollama: tool_name kept", out[2].get("tool_name") == "web_search")


# -------------------------------------------------- 7. primary/secondary
def t_mode_selection():
    e = make_engine(cfg_overrides={"brain": {"mode": "cloud_first"}}, key="k")
    check("cloud_first + key -> cloud drives", e._primary == "cloud", e._primary)
    e = make_engine(cfg_overrides={"brain": {"mode": "cloud_first"}})
    check("cloud_first without key falls back to local", e._primary == "local")
    e = make_engine(cfg_overrides={"brain": {"mode": "local_first"}}, key="k")
    check("local_first keeps local in charge", e._primary == "local")


# --------------------------------------------------- 8. offline smoke turn
def t_offline_turn():
    e = make_engine()
    res = e.respond("hello")
    check("engine survives a full turn with no backends",
          res is not None and (res.reply or res.error) is not None,
          (res.reply or res.error)[:70])
    check("history grew by the turn", len(e.history) >= 2, f"{len(e.history)} msgs")


# --------------------------------------------- 9. key storage (temp file)
def t_key_storage():
    import set_cloud_key as sck
    tmp = os.path.join(tempfile.mkdtemp(), "secrets.test.yaml")
    orig = sck.SECRETS
    sck.SECRETS = tmp
    try:
        sck.store_key("AIzaTESTKEY123")
        got = sck.get_key()
        check("key round-trips through secrets file", got == "AIzaTESTKEY123",
              f"{len(got)} chars")
        check("secrets file is small yaml", os.path.getsize(tmp) < 200)
    finally:
        sck.SECRETS = orig
        if os.path.isfile(tmp):
            os.remove(tmp)


# ------------------------------------------------- 10. desktop icon artifact
def t_icon():
    from shortcut import _write_ico, ICON_SIZES
    tmp = os.path.join(tempfile.mkdtemp(), "test.ico")
    fake = {s: b"\x89PNG\r\n\x1a\n" + b"\x00" * (s * 4) for s in ICON_SIZES}
    _write_ico(tmp, fake)
    with open(tmp, "rb") as f:
        data = f.read()
    reserved, typ, count = struct.unpack("<HHH", data[:6])
    check(".ico header valid", (reserved, typ, count) == (0, 1, len(ICON_SIZES)),
          f"type={typ} images={count}")
    w, h, _, _, _, _, size, off = struct.unpack("<BBBBHHII", data[6:22])
    check(".ico first entry points at real data",
          off + size <= len(data) and data[off:off + 8].startswith(b"\x89PNG"),
          f"offset={off} size={size}")
    os.remove(tmp)

    # real render needs Qt — warn only if unavailable here
    try:
        from shortcut import ensure_icon
        icon = ensure_icon(os.path.join(tempfile.mkdtemp(), "render.ico"))
        check("Qt renders jarvis.ico", os.path.getsize(icon) > 2000,
              f"{os.path.getsize(icon)} bytes")
    except Exception as e:
        skip("Qt icon render", f"{type(e).__name__}: {e}")

    if sys.platform.startswith("win"):
        from shortcut import ensure_desktop_shortcut
        lnk = ensure_desktop_shortcut()
        check("desktop shortcut created", lnk and os.path.isfile(lnk), str(lnk))
    else:
        skip("desktop .lnk", "not on Windows — runs on the JARVIS machine")


# ------------------------------------------------------- 11. live cross-talk
def t_live():
    from brain import BrainEngine, load_config
    e = BrainEngine(cfg=load_config())
    if e.cloud_configured:
        msg, err = e._call_cloud(force_no_tools=True,
                                 messages=[{"role": "user",
                                            "content": "Reply with exactly: ONLINE READY"}])
        text = ((msg or {}).get("content") or "")
        check("live Gemini round trip", err is None and "ONLINE" in text.upper(),
              f"err={err} reply={text[:50]!r}")
    else:
        skip("live Gemini", "no key yet — run: python set_cloud_key.py <key>")

    try:
        import ollama
        ollama.list()
        msg, err = e._call_local(force_no_tools=True,
                                 messages=[{"role": "user",
                                            "content": "Reply with exactly: LOCAL READY"}])
        text = ((msg or {}).get("content") or "")
        check("live local round trip", err is None and "LOCAL" in text.upper(),
              f"err={err} reply={text[:50]!r}")
    except Exception as e2:
        skip("live local core", str(e2)[:70])
        return

    if e.cloud_configured:
        out = e._sub_turn("Reply with exactly the word: DELEGATED", "answer", "cloud")
        check("cross-brain consult (local driver -> Gemini)", "DELEGATED" in out.upper(),
              out[:70])
        out = e._sub_turn("Reply with exactly the word: DELEGATED", "answer", "local")
        check("cross-brain consult (Gemini driver -> local)", "DELEGATED" in out.upper(),
              out[:70])


def main() -> int:
    print("=" * 62)
    print(" dual-brain / desktop-launcher self-test")
    print("=" * 62)
    for fn in (t_config, t_tool_visibility, t_guards, t_consult_flow,
               t_sub_turn_loop, t_message_prep, t_mode_selection,
               t_offline_turn, t_key_storage, t_icon, t_live):
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    print("=" * 62)
    n_skip = len(SKIPS)
    print(f" dual-brain self-test: {len(FAILS)} failed, {n_skip} skipped")
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

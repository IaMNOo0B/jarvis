"""
JARVIS Brain — the dual-brain orchestrator.

One turn = user text in -> spoken reply out. Inside:

  * A driving brain (local Ollama by default, Gemini in `cloud_first` mode)
    runs a parallel tool loop up to N rounds.
  * Both brains share the SAME toolset — either one can research, run code,
    control this PC, and make changes.
  * They cooperate: each sees a consult tool for the other
    (consult_online_brain / consult_local_brain) with per-turn budget and a
    depth guard so consultations can never nest into a loop.
  * Automatic failover to the other brain on errors, timeouts, or hedged
    ("I don't know") answers — spoken replies never stop at a hedge.
  * Every step emits events (status / tool / round) for the HUD via `emit`.

Also home of the shared tool executor used by both voice and text mode.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

import yaml

import actions
from memory import memory_instance
from persona import (CONSULT_SYSTEM_PROMPT, RESEARCH_AGAIN_PROMPT,
                     SYSTEM_PROMPT, is_hedged)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "secrets.local.yaml")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.local.yaml")


def _deep_merge(base: dict, over: dict) -> dict:
    """Recursively merge `over` into `base` (in place)."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base

# ------------------------------------------------------- cross-brain consult
# Each brain only ever sees the tool that points at the OTHER brain.
CONSULT_ONLINE_TOOL = {
    "type": "function",
    "function": {
        "name": "consult_online_brain",
        "description": (
            "Delegate a question or sub-task to the ONLINE brain (Gemini). It "
            "runs with the same tools as you — it can research the web, run "
            "code, and control this PC to get work done. Use it for hard "
            "reasoning, a second opinion, or work to run in parallel. Returns "
            "its final answer or a report of what it did."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The full question or task, with all context the other brain needs.",
                },
                "focus": {
                    "type": "string",
                    "enum": ["answer", "execute"],
                    "description": "'answer' = just answer; 'execute' = use tools to actually do work on this PC.",
                },
            },
            "required": ["question"],
        },
    },
}

CONSULT_LOCAL_TOOL = {
    "type": "function",
    "function": {
        "name": "consult_local_brain",
        "description": (
            "Delegate a question or sub-task to the LOCAL JARVIS core "
            "(Ollama). It has this machine's memory, workspace files, and "
            "full PC control. Use it for local context, execution on this "
            "machine, privacy-sensitive work, or a second opinion. Returns "
            "its final answer or a report of what it did."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The full question or task, with all context the local core needs.",
                },
                "focus": {
                    "type": "string",
                    "enum": ["answer", "execute"],
                    "description": "'answer' = just answer; 'execute' = use tools to actually do work on this PC.",
                },
            },
            "required": ["question"],
        },
    },
}


# --------------------------------------------------------------------- config
def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # User overrides from the settings panel (settings.local.yaml, gitignored)
    # are deep-merged over the shipped config.yaml defaults.
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                over = yaml.safe_load(f) or {}
            if isinstance(over, dict):
                _deep_merge(cfg, over)
    except Exception:
        pass
    return cfg


# ------------------------------------------------------------- tool executor
def execute_single_tool(name: str, args: dict, services: dict | None = None) -> str:
    """Dispatch one tool call. Never raises — failures return speakable text."""
    try:
        if name == "parallel_multi_search":
            return actions.parallel_multi_search(args.get("queries", []))
        if name == "parallel_multi_browse":
            return actions.parallel_multi_browse(args.get("urls", []))
        if name == "web_search":
            return actions.web_search(args.get("query", ""))
        if name == "browse_url":
            return actions.browse_url(args.get("url", ""))
        if name == "execute_code":
            return actions.execute_code(args.get("language", "python"), args.get("code", ""))
        if name == "write_workspace_file":
            return actions.write_workspace_file(args.get("filepath", ""), args.get("content", ""))
        if name == "read_workspace_file":
            return actions.read_workspace_file(args.get("filepath", ""))
        if name == "list_workspace_files":
            return actions.list_workspace_files(args.get("subfolder", ""))
        if name == "save_learned_knowledge":
            return memory_instance.save_knowledge(
                title=args.get("title", "Pattern"),
                content=args.get("content", ""),
                source=args.get("source", "system"),
            )
        if name == "recall_memory":
            return memory_instance.search_memory(args.get("query", ""))

        import system_actions
        result = system_actions.dispatch(name, args, services)
        if result is not None:
            return result
        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool execution error ({name}): {e}"


def execute_tools_in_parallel(tool_calls: list, services: dict | None = None,
                              emit=None) -> list:
    """Run a batch of tool calls concurrently; returns results in call order."""
    emit = emit or (lambda *_: None)
    parsed = []
    for idx, tool in enumerate(tool_calls):
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = fn.get("name")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        parsed.append((idx, name, args or {}))

    results = [None] * len(parsed)

    def _worker(i, n, a):
        emit("tool", f"{n}({json.dumps(a, default=str)[:180]})")
        r = execute_single_tool(n, a, services)
        emit("tool_result", f"{n}: {str(r)[:150]}")
        return i, r

    with ThreadPoolExecutor(max_workers=max(1, len(parsed))) as ex:
        futures = [ex.submit(_worker, i, n, a) for i, n, a in parsed]
        for f in as_completed(futures):
            i, r = f.result()
            results[i] = r
    return results


# -------------------------------------------------------------------- result
@dataclass
class BrainResult:
    reply: str
    tools_used: list = field(default_factory=list)
    rounds: int = 0
    escalated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.reply.strip())


# -------------------------------------------------------------------- engine
class BrainEngine:
    """Serialises turns (one conversation at a time)."""

    def __init__(self, cfg: dict | None = None, services: dict | None = None,
                 emit=None):
        self.cfg = cfg or load_config()
        b = self.cfg.get("brain", {})
        self.model = b.get("local_model") or "llama3"
        self.num_ctx = int(b.get("num_ctx", 8192))
        self.temperature = float(b.get("temperature", 0.6))
        self.local_timeout = float(b.get("local_timeout", 120))
        self.max_rounds = int(b.get("max_tool_rounds", 6))
        cloud = b.get("cloud", {}) or {}
        self.mode = (b.get("mode", "local_first") or "local_first").lower()
        self.provider = (cloud.get("provider", "openai") or "openai").lower()
        self.cloud_base = self._resolve_base(cloud)
        self.cloud_model = self._resolve_model(cloud)
        self.cloud_key = self._resolve_key(cloud)
        self.cloud_timeout = float(cloud.get("timeout", 60))
        self.consult_budget_max = int(cloud.get("consult_budget", 2))
        self.consult_rounds = int(cloud.get("consult_rounds", 3))
        self._consult_depth = 0
        self._consult_used = 0

        self.services = services or {}
        self.emit = emit or (lambda kind, payload: None)

        self._client = None
        self._lock = threading.Lock()
        self.reset()

    # ----------------------------------------------------------- conversation
    def reset(self) -> None:
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    @property
    def cloud_configured(self) -> bool:
        return bool(self.cloud_base and self.cloud_key and self.cloud_model)

    # ------------------------------------------------------ provider defaults
    def _resolve_base(self, cloud: dict) -> str:
        explicit = (cloud.get("base_url")
                    or os.environ.get("JARVIS_CLOUD_BASE_URL", "")).rstrip("/")
        if explicit:
            return explicit
        if self.provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/openai"
        return ""

    def _resolve_model(self, cloud: dict) -> str:
        explicit = cloud.get("model") or os.environ.get("JARVIS_CLOUD_MODEL", "")
        if explicit:
            return explicit
        if self.provider == "gemini":
            return "gemini-3.8-flash"
        return ""

    def _resolve_key(self, cloud: dict) -> str:
        envs = [cloud.get("api_key_env", "")]
        if self.provider == "gemini":
            envs += ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
        for var in dict.fromkeys(v for v in envs if v):
            val = os.environ.get(var, "")
            if val:
                return val
        # secrets.local.yaml — written once by `python set_cloud_key.py <key>`
        try:
            if os.path.isfile(SECRETS_PATH):
                with open(SECRETS_PATH, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                keys = (["gemini_api_key"] if self.provider == "gemini"
                        else ["cloud_api_key", "api_key"])
                keys += ["gemini_api_key", "cloud_api_key", "api_key"]
                for k in dict.fromkeys(keys):
                    val = str(data.get(k) or "").strip()
                    if val:
                        return val
        except Exception:
            pass
        return ""

    @property
    def _primary(self) -> str:
        """Which brain drives the conversation."""
        if self.mode == "cloud_first" and self.cloud_configured:
            return "cloud"
        return "local"

    def _ollama_client(self):
        if self._client is None and ollama is not None:
            try:
                self._client = ollama.Client(timeout=self.local_timeout)
            except TypeError:
                self._client = ollama.Client()
        return self._client

    # ------------------------------------------------------------------ turns
    def respond(self, user_text: str) -> BrainResult:
        """Blocking: run one full turn (tool loop + synthesis)."""
        if not self._lock.acquire(blocking=False):
            return BrainResult(reply="", error="busy")
        try:
            return self._respond_locked(user_text.strip())
        finally:
            self._lock.release()

    def _respond_locked(self, user_text: str) -> BrainResult:
        if not user_text:
            return BrainResult(reply="")
        # drop an unused research-directive left over from a previous turn
        while len(self.history) > 1 and self.history[-1].get("role") == "user" \
                and self.history[-1].get("content") == RESEARCH_AGAIN_PROMPT:
            self.history.pop()
        self.history.append({"role": "user", "content": user_text})
        tools_used: list[str] = []
        escalated = False
        hedged_rounds = 0
        self._consult_used = 0          # fresh consultation budget each turn
        self._consult_depth = 0

        # --- pick the driving brain (dual-brain mode) ---
        primary = self._primary
        secondary = ("local" if primary == "cloud"
                     else ("cloud" if self.cloud_configured else None))
        active = primary
        switched = False

        for rnd in range(1, self.max_rounds + 1):
            use_cloud = active == "cloud"

            self.emit("round", rnd)
            self.emit("status", "researching" if tools_used or hedged_rounds else "thinking")

            if use_cloud:
                msg, err = self._call_cloud()
            else:
                msg, err = self._call_local()

            if err:
                # driving brain stumbled — hand the turn to the other brain
                if secondary and not switched:
                    switched = True
                    escalated = True
                    active = secondary
                    self.emit("status", "escalating")
                    msg, err = (self._call_cloud() if active == "cloud"
                                else self._call_local())
                if err:
                    return BrainResult(
                        reply=self._offline_reply(err),
                        tools_used=tools_used, rounds=rnd, escalated=escalated, error=err,
                    )

            tool_calls = self._tool_calls(msg)
            content = (msg.get("content") or "").strip()

            if not tool_calls:
                # ---- final answer: apply the no-hedge guarantee ----
                if is_hedged(content):
                    hedged_rounds += 1
                    if hedged_rounds == 1 and rnd < self.max_rounds:
                        self.history.append({"role": "user", "content": RESEARCH_AGAIN_PROMPT})
                        continue
                    if secondary and not switched:
                        # let the OTHER brain take a swing at it
                        switched = True
                        escalated = True
                        active = secondary
                        self.emit("status", "escalating")
                        self.history.append({"role": "user", "content": RESEARCH_AGAIN_PROMPT})
                        continue
                if not content:
                    content = self._synthesize_from_tools(tools_used)
                return BrainResult(reply=content, tools_used=tools_used,
                                   rounds=rnd, escalated=escalated)

            # ---- run tools (incl. cross-brain consults), feed results back ----
            for i, tc in enumerate(tool_calls):
                if not tc.get("id"):        # cloud providers need matching ids
                    tc["id"] = f"call_{rnd}_{i}"
            self.history.append(self._assistant_msg_for_history(msg, tool_calls))
            results = self._execute_tools(tool_calls, active)
            for tc, res in zip(tool_calls, results):
                name = (tc.get("function", {}) or {}).get("name", "?")
                tools_used.append(name)
                self.history.append({
                    "role": "tool",
                    "content": str(res),
                    "tool_name": name,
                    "tool_call_id": tc.get("id", ""),
                })

        # budget exhausted — force a final spoken answer from the active brain
        self.emit("status", "thinking")
        if active == "cloud":
            msg, err = self._call_cloud(force_no_tools=True)
        else:
            msg, err = self._call_local(force_no_tools=True)
        content = ((msg or {}).get("content") or "").strip() if not err else ""
        if not content:
            content = ("I have the research in front of me, sir — allow me one more "
                       "moment to compose it.") if tools_used else self._offline_reply(err or "no reply")
        if is_hedged(content) and tools_used:
            content = self._pivot_to_action(content, tools_used)
        return BrainResult(reply=content, tools_used=tools_used,
                           rounds=self.max_rounds, escalated=escalated,
                           error=None if content else err)

    # ------------------------------------------------------------- providers
    def _call_local(self, force_no_tools: bool = False,
                    messages: list | None = None,
                    tools: list | None = None) -> tuple[dict | None, str | None]:
        if ollama is None:
            return None, "ollama library not installed"
        try:
            client = self._ollama_client()
            kwargs = dict(
                model=self.model,
                messages=self._prepare(self.history if messages is None else messages,
                                       "ollama"),
                stream=False,
                options={"num_ctx": self.num_ctx, "temperature": self.temperature},
            )
            if not force_no_tools:
                kwargs["tools"] = tools if tools is not None else self._tools_for("local")
            resp = client.chat(**kwargs)
            data = _as_dict(resp)
            msg = data.get("message") or {}
            if isinstance(msg, dict):
                return msg, None
            return _msg_to_dict(msg), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def _call_cloud(self, force_no_tools: bool = False,
                    messages: list | None = None,
                    tools: list | None = None) -> tuple[dict | None, str | None]:
        if not self.cloud_configured:
            return None, "cloud endpoint not configured"
        try:
            import requests
            url = f"{self.cloud_base}/chat/completions"
            payload = {
                "model": self.cloud_model,
                "messages": self._prepare(self.history if messages is None else messages,
                                           "openai"),
            }
            if self.provider != "gemini":
                # Gemini 3 deprecates temperature tuning — omit it there
                payload["temperature"] = self.temperature
            if not force_no_tools:
                payload["tools"] = tools if tools is not None else self._tools_for("cloud")
                payload["tool_choice"] = "auto"
            r = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self.cloud_key}"},
                timeout=self.cloud_timeout,
            )
            if r.status_code != 200:
                return None, f"cloud HTTP {r.status_code}: {r.text[:200]}"
            msg = r.json()["choices"][0]["message"]
            return _normalize_cloud_msg(msg), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ----------------------------------------------------------- formatting
    @staticmethod
    def _prepare(messages: list[dict], provider: str) -> list[dict]:
        """Normalise shared history for the target provider's schema."""
        out = []
        for m in messages:
            m = dict(m)
            if provider == "ollama":
                tcs = m.get("tool_calls")
                if tcs:
                    norm = []
                    for tc in tcs:
                        fn = tc.get("function", {})
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        norm.append({"function": {"name": fn.get("name"), "arguments": args}})
                    m["tool_calls"] = norm
                m.pop("tool_call_id", None)
            else:  # openai (incl. Gemini's OpenAI-compatible endpoint)
                tcs = m.get("tool_calls")
                if tcs:
                    norm = []
                    for i, tc in enumerate(tcs):
                        fn = tc.get("function", {})
                        args = fn.get("arguments", {})
                        if not isinstance(args, str):
                            args = json.dumps(args, ensure_ascii=False)
                        norm.append({
                            "id": tc.get("id") or f"call_{abs(hash(fn.get('name'))) % 10**8}_{i}",
                            "type": "function",
                            "function": {"name": fn.get("name"), "arguments": args},
                        })
                    m["tool_calls"] = norm
                if m.get("role") == "tool":
                    m.pop("tool_name", None)   # ollama-only field: Gemini rejects unknowns
                    if not m.get("tool_call_id"):
                        m["tool_call_id"] = "call_unknown"
            out.append(m)
        return out

    @staticmethod
    def _assistant_msg_for_history(msg: dict, tool_calls: list) -> dict:
        out = {"role": "assistant", "content": msg.get("content", "")}
        norm = []
        for i, tc in enumerate(tool_calls):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            norm.append({
                "id": tc.get("id") or f"call_{i}",
                "type": "function",
                "function": {"name": fn.get("name"), "arguments": args},
            })
        out["tool_calls"] = norm
        return out

    @staticmethod
    def _tool_calls(msg: dict) -> list:
        tcs = msg.get("tool_calls") or []
        return [tc for tc in tcs if (tc.get("function", {}) or {}).get("name")]

    # ------------------------------------------------------- dual-brain tools
    def _tools_for(self, provider: str, allow_consult: bool = True) -> list:
        """Full shared toolset; each brain only sees the consult tool for the other."""
        tools = list(actions.TOOL_DEFINITIONS)
        if allow_consult:
            if provider == "cloud":
                tools.append(CONSULT_LOCAL_TOOL)
            elif self.cloud_configured:
                tools.append(CONSULT_ONLINE_TOOL)
        return tools

    def _execute_tools(self, tool_calls: list, provider: str) -> list:
        """Run a batch: regular tools in parallel, consults sequentially.

        Results come back in the original call order so the tool loop can zip
        them against the calls.
        """
        results: list = [None] * len(tool_calls)
        regular: list[tuple[int, dict]] = []
        consults: list[tuple[int, dict]] = []
        for i, tc in enumerate(tool_calls):
            name = (tc.get("function", {}) or {}).get("name", "")
            if name in ("consult_online_brain", "consult_local_brain"):
                consults.append((i, tc))
            else:
                regular.append((i, tc))

        if regular:
            out = execute_tools_in_parallel([tc for _, tc in regular],
                                            self.services, self.emit)
            for (i, _), r in zip(regular, out):
                results[i] = r

        for i, tc in consults:
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            results[i] = self._run_consult(fn.get("name", ""), args)
        return results

    def _run_consult(self, name: str, args: dict) -> str:
        """Ask the OTHER brain — with budget and no-nesting guards."""
        question = str(args.get("question") or "").strip()
        focus = str(args.get("focus") or "answer").strip()
        if not question:
            return "Consult failed: no question was supplied."
        if self._consult_depth > 0:
            return ("Consulting is disabled inside a consultation — complete "
                    "this task yourself using your tools.")
        if self._consult_used >= self.consult_budget_max:
            return (f"Consultation budget used ({self.consult_budget_max} per "
                    "turn) — answer from your own research.")
        target = "cloud" if name == "consult_online_brain" else "local"
        if target == "cloud" and not self.cloud_configured:
            return ("The online brain is not configured yet — run "
                    "`python set_cloud_key.py <key>` to enable it. Answer "
                    "from local research.")
        if target == "local" and ollama is None:
            return "The local brain is unavailable (ollama library not installed)."

        self._consult_used += 1
        self._consult_depth += 1
        who = "Gemini (online)" if target == "cloud" else "local core"
        self.emit("tool", f"{name} -> {who}")
        try:
            answer = self._sub_turn(question, focus, target)
        finally:
            self._consult_depth -= 1
        return f"[{who} brain answered]: {answer}"

    def _sub_turn(self, question: str, focus: str, provider: str) -> str:
        """Run a bounded side-conversation for the other brain (own history)."""
        messages = [
            {"role": "system", "content": self._consult_prompt(provider, focus)},
            {"role": "user", "content": question},
        ]
        tools = self._tools_for(provider, allow_consult=False)
        last = ""
        for rnd in range(1, self.consult_rounds + 1):
            if provider == "cloud":
                msg, err = self._call_cloud(messages=messages, tools=tools)
            else:
                msg, err = self._call_local(messages=messages, tools=tools)
            if err or msg is None:
                return last or f"the {provider} brain is unreachable ({err})."
            content = (msg.get("content") or "").strip()
            tcs = self._tool_calls(msg)
            if not tcs:
                return content or last or "the consulted brain produced no answer."
            last = content
            for i, tc in enumerate(tcs):
                if not tc.get("id"):
                    tc["id"] = f"sub_{rnd}_{i}"
            messages.append(self._assistant_msg_for_history(msg, tcs))
            results = execute_tools_in_parallel(tcs, self.services, self.emit)
            for tc, r in zip(tcs, results):
                messages.append({
                    "role": "tool",
                    "content": str(r),
                    "tool_name": (tc.get("function", {}) or {}).get("name", "?"),
                    "tool_call_id": tc.get("id", ""),
                })
        return last or "the consulted brain ran out of rounds before answering."

    @staticmethod
    def _consult_prompt(provider: str, focus: str) -> str:
        partner = ("Gemini — the online brain" if provider == "cloud"
                   else "JARVIS local core (Ollama, on this PC)")
        mode = ("actually DO the work with your tools, then report what you did"
                if focus == "execute"
                else "answer thoroughly, using tools to research/verify first")
        return CONSULT_SYSTEM_PROMPT.format(partner=partner, mode=mode)

    # ------------------------------------------------------------ fallbacks
    def _offline_reply(self, err: str | None) -> str:
        print(f"[brain] core unavailable: {err}")
        return ("My core processors are unreachable, sir — the local model appears "
                "to be offline. Do start Ollama and I shall be with you immediately.")

    def _synthesize_from_tools(self, tools_used: list) -> str:
        if tools_used:
            return ("The data has been gathered, sir: " +
                    ", ".join(sorted(set(tools_used))) +
                    " — but my synthesis pass failed. Do try me again.")
        return "All systems ready, sir. Do ask me anything."

    def _pivot_to_action(self, content: str, tools_used: list) -> str:
        """Last-resort rewrite so we never speak a bare hedge."""
        return (f"{content} In the meantime, I have already looked into it via "
                f"{', '.join(sorted(set(tools_used)))} — give me a moment and I shall "
                "keep digging, sir.")


# -------------------------------------------------------------------- helpers
def _as_dict(obj):
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "keys"):  # Mapping-like
        return {k: obj[k] for k in obj.keys()}
    return dict(obj.__dict__)


def _msg_to_dict(msg) -> dict:
    d = _as_dict(msg)
    out = {
        "role": d.get("role", "assistant"),
        "content": d.get("content") or "",
    }
    if d.get("tool_calls"):
        out["tool_calls"] = d["tool_calls"]
    return out


def _normalize_cloud_msg(msg: dict) -> dict:
    out = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = [
            {
                "id": tc.get("id", ""),
                "function": {
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments", {}),
                },
            }
            for tc in msg["tool_calls"]
        ]
    return out

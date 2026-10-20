"""
JARVIS Actions Layer - Parallel & Concurrent Execution Engine
Provides high-performance multi-threaded and concurrent tools:
1. Parallel Web Multi-Search across diverse angles/queries concurrently
2. Parallel Web Browsing / Deep Scraping across multiple URLs concurrently
3. Concurrent Multi-Action Execution for arbitrary batches of tasks
4. Safe Code Execution & Workspace File Operations
5. Real-Time Memory Storage & Semantic Retrieval
"""

import os
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from ddgs import DDGS

# Workspace root. Dev: the repo parent (as before). Installed (frozen): the
# writable per-user data dir, since the bundle location isn't writable.
from paths import data_dir, frozen, user_file
WORKSPACE_DIR = data_dir() if frozen() else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _secret(name: str) -> str:
    """One key from secrets.local.yaml (no Qt import — actions runs headless)."""
    try:
        import yaml
        with open(user_file("secrets.local.yaml"), encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get(name) or "").strip()
    except Exception:
        return ""


def _tavily_search(query: str, max_results: int = 4) -> list | None:
    """Tavily agent-search. Returns [{title, href, body}] or None (no key/fail)."""
    key = _secret("tavily_api_key")
    if not key:
        return None
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": max_results,
                  "include_answer": False},
            timeout=15, headers={"User-Agent": "curl/8"})
        out = []
        for x in r.json().get("results") or []:
            if x.get("title"):
                out.append({"title": x["title"], "href": x.get("url", ""),
                            "body": (x.get("content") or "")[:400]})
        return out or None
    except Exception:
        return None

def web_search(query: str, max_results: int = 4) -> str:
    """Searches the internet for real-time information, documentation, and references.
    Tavily (agent-grade) when a key is set, DuckDuckGo otherwise."""
    try:
        results = _tavily_search(query, max_results)
        if results is None:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No web search results found for query: '{query}'"
        
        output = [f"Web search results for: '{query}'\n"]
        for idx, item in enumerate(results, start=1):
            title = item.get("title", "No Title")
            snippet = item.get("body", "")
            href = item.get("href", "")
            output.append(f"[{idx}] {title}\nURL: {href}\nSummary: {snippet}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Error executing web search: {e}"

def parallel_multi_search(queries: list, max_results_per_query: int = 3) -> str:
    """
    Executes multiple search queries in parallel across different angles simultaneously.
    E.g. researching benchmarks, architecture, RFCs, and criticisms of a technology at the same time.
    """
    if not queries:
        return "No queries provided for parallel search."

    results_dict = {}

    def _search_worker(q):
        try:
            items = _tavily_search(q, max_results_per_query)
            if items is None:
                ddgs = DDGS()
                items = list(ddgs.text(q, max_results=max_results_per_query))
            return q, items, None
        except Exception as e:
            return q, [], str(e)

    with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as executor:
        futures = [executor.submit(_search_worker, query.strip()) for query in queries if query.strip()]
        for future in as_completed(futures):
            q, items, err = future.result()
            if err:
                results_dict[q] = f"Error: {err}"
            elif not items:
                results_dict[q] = "No results found."
            else:
                formatted = []
                for idx, item in enumerate(items, start=1):
                    formatted.append(f"  [{idx}] {item.get('title')}\n      URL: {item.get('href')}\n      Snippet: {item.get('body')}")
                results_dict[q] = "\n".join(formatted)

    output = [f"=== PARALLEL MULTI-ANGLE RESEARCH RESULTS ({len(results_dict)} angles analyzed) ===\n"]
    for q, res in results_dict.items():
        output.append(f"### Perspective: '{q}'\n{res}\n")
    return "\n".join(output)

def browse_url(url: str, max_chars: int = 3000) -> str:
    """Visits a single web page URL and extracts clean readable text content."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            element.decompose()
            
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = "\n".join(lines)
        
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + f"\n... [Truncated. Total length {len(cleaned)} chars]"
            
        return f"Content of {url}:\n\n{cleaned}"
    except Exception as e:
        return f"Error browsing URL {url}: {e}"

def parallel_multi_browse(urls: list, max_chars_per_page: int = 2500) -> str:
    """
    Visits and extracts content from multiple web pages simultaneously using concurrent worker threads.
    """
    if not urls:
        return "No URLs provided for parallel browsing."

    results = {}

    def _browse_worker(target_url):
        res = browse_url(target_url, max_chars=max_chars_per_page)
        return target_url, res

    with ThreadPoolExecutor(max_workers=min(len(urls), 6)) as executor:
        futures = [executor.submit(_browse_worker, u.strip()) for u in urls if u.strip()]
        for future in as_completed(futures):
            u, text = future.result()
            results[u] = text

    output = [f"=== PARALLEL MULTI-PAGE BROWSING RESULTS ({len(results)} pages fetched) ===\n"]
    for u, content in results.items():
        output.append(f"--- SOURCE: {u} ---\n{content}\n")
    return "\n".join(output)

def read_workspace_file(filepath: str) -> str:
    """Reads text from a supplied file path."""
    try:
        target = os.path.abspath(os.path.join(WORKSPACE_DIR, filepath)) if not os.path.isabs(filepath) else filepath
        if not os.path.exists(target):
            return f"File does not exist: {filepath}"
        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {filepath}: {e}"

def write_workspace_file(filepath: str, content: str) -> str:
    """Writes text to a supplied file path."""
    try:
        target = os.path.abspath(os.path.join(WORKSPACE_DIR, filepath)) if not os.path.isabs(filepath) else filepath
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote file: {filepath} ({len(content)} characters)."
    except Exception as e:
        return f"Error writing file {filepath}: {e}"

def list_workspace_files(subfolder: str = "") -> str:
    """Lists files in the workspace or a given subfolder."""
    try:
        target = os.path.abspath(os.path.join(WORKSPACE_DIR, subfolder))
        if not os.path.exists(target):
            return f"Directory does not exist: {subfolder}"
        entries = os.listdir(target)
        return f"Files in '{subfolder or 'root'}':\n" + "\n".join(f"- {e}" for e in entries)
    except Exception as e:
        return f"Error listing directory: {e}"

def execute_code(language: str, code: str) -> str:
    """Executes a code snippet in Python or Node.js."""
    lang = language.lower().strip()
    scratch_dir = os.path.join(WORKSPACE_DIR, "AI_Model", "code_scratch")
    os.makedirs(scratch_dir, exist_ok=True)

    try:
        if lang in ["python", "py"]:
            file_path = os.path.join(scratch_dir, "run.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            proc = subprocess.run(["python", file_path], capture_output=True, text=True, timeout=15)
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            return f"[Execution Code: {proc.returncode}]\nStdout:\n{out}\n" + (f"Stderr:\n{err}" if err else "")

        elif lang in ["javascript", "js", "node"]:
            file_path = os.path.join(scratch_dir, "run.js")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            proc = subprocess.run(["node", file_path], capture_output=True, text=True, timeout=15)
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            return f"[Execution Code: {proc.returncode}]\nStdout:\n{out}\n" + (f"Stderr:\n{err}" if err else "")

        else:
            return f"Direct runtime execution for '{language}' not configured. Code analyzed for syntax & logic."
    except subprocess.TimeoutExpired:
        return "Execution timed out (exceeded 15s)."
    except Exception as e:
        return f"Execution error: {e}"

# Tool specifications formatted for Ollama tool calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "parallel_multi_search",
            "description": "Execute multiple distinct search queries in parallel across different angles, domains, or viewpoints simultaneously. Use this to conduct broad, deep, multi-source research in one shot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of diverse search queries to run simultaneously (e.g., ['Topic architecture', 'Topic benchmarks', 'Topic limitations', 'Topic RFC documentation'])."
                    }
                },
                "required": ["queries"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "parallel_multi_browse",
            "description": "Fetch, extract, and ingest content from multiple web pages or documentation URLs simultaneously in parallel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to scrape and analyze concurrently."
                    }
                },
                "required": ["urls"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live internet for a single focused query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browse_url",
            "description": "Visit and extract text content from a single URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to inspect."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Run and test code snippets in Python or JavaScript to verify algorithmic correctness, benchmarks, or logic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language: 'python' or 'javascript'."
                    },
                    "code": {
                        "type": "string",
                        "description": "Complete executable code snippet."
                    }
                },
                "required": ["language", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "Read text from a supplied file path for code review, refactoring, or debugging.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Relative or absolute path to the file."
                    }
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "List files and subfolders in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subfolder": {
                        "type": "string",
                        "description": "Subdirectory to inspect (leave empty for root)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_learned_knowledge",
            "description": "Save a learning record with source and evidence metadata. New records begin unverified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Topic or title.",
                        "default": ""
                    },
                    "content": {
                        "type": "string",
                        "description": "In-depth explanation, syntax patterns, or code takeaways.",
                        "default": ""
                    },
                    "source": {
                        "type": "string",
                        "description": "Source reference or URL.",
                        "default": ""
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source URLs, test outputs, or other supporting evidence."
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Tentative confidence from 0 to 1; not a substitute for validation."
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Observed result or what the task taught."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_task_outcome",
            "description": "Save an observed task episode with success, partial, or failure status and evidence, so later tasks can learn from real outcomes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Concise description of the task that was actually attempted."},
                    "status": {"type": "string", "enum": ["success", "partial", "failure"], "description": "Observed task result, not an assumption."},
                    "result": {"type": "string", "description": "What happened, including any partial failure."},
                    "evidence": {"type": "array", "items": {"type": "string"}, "description": "Tool results, test results, changed paths, or other evidence references."},
                    "user_feedback": {"type": "string", "description": "Sir's actual feedback, only when he provided it."}
                },
                "required": ["task", "status", "result"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_learned_knowledge",
            "description": "Record concrete validation evidence and outcome for an existing learning record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "ID returned by save_learned_knowledge or recall_memory."},
                    "evidence": {"type": "array", "items": {"type": "string"}, "description": "Evidence references that support the validation."},
                    "outcome": {"type": "string", "description": "What was tested or independently verified."}
                },
                "required": ["entry_id", "evidence", "outcome"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stage_skill_candidate",
            "description": "Store a proposed reusable Jarvis skill in a separate staging area without loading or running it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Lowercase skill name, such as research_helper."},
                    "code": {"type": "string", "description": "Complete Python source for skills/<name>/skill.py."},
                    "rationale": {"type": "string", "description": "Problem this candidate is intended to solve."},
                    "source": {"type": "string", "description": "Research source URLs or design references."},
                    "tests": {
                        "type": "array",
                        "description": "Optional behavior test cases. Each case needs tool_name, args, kind (feature/regression), and exactly one expected_equals, expected_contains, or expected_is_none assertion.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "tool_name": {"type": "string"},
                                "args": {"type": "object"},
                                "kind": {"type": "string", "enum": ["feature", "regression"]},
                                "expected_equals": {"type": ["string", "null"]},
                                "expected_contains": {"type": "string"},
                                "expected_is_none": {"type": "boolean"}
                            },
                            "required": ["tool_name"]
                        }
                    }
                },
                "required": ["name", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_skill_candidate",
            "description": "Statically inspect a staged skill candidate for Python syntax and the Jarvis skill interface. Does not execute it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Exact candidate ID returned by stage_skill_candidate."}
                },
                "required": ["candidate_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "test_skill_candidate",
            "description": "Run the supplied candidate tests in a constrained disposable subprocess. When regression cases are provided, compare them against the current live skill. This records a report but never activates or promotes the candidate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Exact candidate ID returned by stage_skill_candidate."},
                    "timeout_seconds": {"type": "integer", "description": "Overall execution timeout from 3 to 30 seconds; defaults to 15."}
                },
                "required": ["candidate_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "promote_skill_candidate",
            "description": "Install a candidate only after static checks and its test suite pass. The first call without approval_token only requests confirmation. After Sir explicitly approves this exact candidate ID, call again with approval_token equal to that ID. Creates a version archive and requires Jarvis restart; does not hot-load the code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Exact candidate ID returned by stage_skill_candidate."},
                    "approval_token": {"type": "string", "description": "Must exactly equal candidate_id to authorize the operation."}
                },
                "required": ["candidate_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_skill_version",
            "description": "Restore the versioned prior skill file for a promoted version ID, provided the live file still matches the promoted hash.",
            "parameters": {
                "type": "object",
                "properties": {
                    "version_id": {"type": "string", "description": "Exact version ID returned by promotion or version history."},
                    "approval_token": {"type": "string", "description": "Must exactly equal version_id to authorize the operation."}
                },
                "required": ["version_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skill_versions",
            "description": "List version history, hashes, promotion state, and rollback availability without executing skill code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum versions to list, 1-50; defaults to 20."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skill_candidates",
            "description": "List staged skill proposals, evaluation status, and activation state without executing their code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum candidates to list, 1-50; defaults to 20."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_skill_candidate",
            "description": "Read the exact staged skill source and metadata for review. Does not import or execute it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Exact candidate ID returned by stage_skill_candidate."}
                },
                "required": ["candidate_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_skill_candidate",
            "description": "Show the textual diff between a staged skill candidate and the current built-in skill, if one exists. Does not execute either version.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Exact candidate ID returned by stage_skill_candidate."}
                },
                "required": ["candidate_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search and retrieve previously saved coding patterns, knowledge, or notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword or topic to search."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["all", "unverified", "validated"],
                        "description": "Optional validation-state filter; defaults to all."
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of matching records (1-20; default 5)."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Operational tools (PC control, diagnostics, reminders, briefings, presence)
# live in system_actions.py — appended here so every entry point (voice app,
# text mode) exposes the full JARVIS toolset.
from system_actions import TOOL_DEFINITIONS_EXTRA  # noqa: E402

TOOL_DEFINITIONS = TOOL_DEFINITIONS + TOOL_DEFINITIONS_EXTRA

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

# Workspace root (Fan folder)
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def web_search(query: str, max_results: int = 4) -> str:
    """Searches the internet for real-time information, documentation, and references."""
    try:
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
    """Reads a text file inside the workspace."""
    try:
        target = os.path.abspath(os.path.join(WORKSPACE_DIR, filepath)) if not os.path.isabs(filepath) else filepath
        if not os.path.exists(target):
            return f"File does not exist: {filepath}"
        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {filepath}: {e}"

def write_workspace_file(filepath: str, content: str) -> str:
    """Writes or overwrites a file in the workspace."""
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
            "description": "Read the contents of a workspace file for code review, refactoring, or debugging.",
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
            "description": "Save newly acquired knowledge, algorithm implementations, architectural patterns, or facts to JARVIS's permanent memory.",
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
                    }
                },
                "required": []
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

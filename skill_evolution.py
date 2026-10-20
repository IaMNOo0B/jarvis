"""Staged skill improvement workflow.

Candidates are stored separately from live skills, parsed without importing or
executing them, and never become active automatically.
"""

import ast
import difflib
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime

from paths import user_file


CANDIDATE_ROOT = user_file("skill_candidates")
LIVE_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}-[0-9a-f]{10}$")
_MAX_SOURCE_BYTES = 100_000


def _write_json_atomic(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="candidate-", suffix=".tmp",
                                     dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _candidate_dir(candidate_id: str) -> str:
    candidate_id = str(candidate_id or "").strip()
    if not _ID_RE.fullmatch(candidate_id):
        raise ValueError("Invalid candidate ID. Use the ID returned when the candidate was staged.")
    root = os.path.abspath(CANDIDATE_ROOT)
    target = os.path.abspath(os.path.join(root, candidate_id))
    if os.path.commonpath([root, target]) != root:
        raise ValueError("Candidate path is outside the staging directory.")
    return target


def _live_skill_path(name: str) -> str:
    return os.path.abspath(os.path.join(LIVE_SKILLS_DIR, name, "skill.py"))


def _sha256_file(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def _read_candidate(candidate_id: str) -> tuple[str, dict, str]:
    folder = _candidate_dir(candidate_id)
    with open(os.path.join(folder, "candidate.json"), "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    with open(os.path.join(folder, "skill.py"), "r", encoding="utf-8") as handle:
        source = handle.read()
    return folder, metadata, source


def list_skill_candidates(limit: int = 20) -> str:
    """List staged versions and their evaluation state, without executing them."""
    try:
        os.makedirs(CANDIDATE_ROOT, exist_ok=True)
        entries = []
        for candidate_id in sorted(os.listdir(CANDIDATE_ROOT), reverse=True):
            if not _ID_RE.fullmatch(candidate_id):
                continue
            try:
                _, metadata, source = _read_candidate(candidate_id)
                digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
                entries.append({
                    "candidate_id": candidate_id,
                    "name": metadata.get("name", ""),
                    "state": metadata.get("state", "staged"),
                    "sha_matches": digest == metadata.get("sha256"),
                    "tests_run": bool(metadata.get("tests_run")),
                    "activated": bool(metadata.get("activated")),
                    "created_at": metadata.get("created_at", ""),
                })
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                entries.append({"candidate_id": candidate_id, "state": "metadata_error", "error": str(exc)})
            if len(entries) >= max(1, min(int(limit), 50)):
                break
    except OSError as exc:
        return f"Could not list staged skills: {exc}"
    if not entries:
        return "No staged skill candidates found."
    return "Staged skill candidates (none are activated by this listing):\n" + json.dumps(entries, indent=2)


def inspect_skill_candidate(candidate_id: str) -> str:
    """Return the saved metadata and source for review; do not import candidate."""
    try:
        _, metadata, source = _read_candidate(candidate_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Candidate inspection failed: {exc}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    result = {
        "metadata": metadata,
        "current_sha256": digest,
        "sha_matches_staged": digest == metadata.get("sha256"),
        "candidate_source": source[:18000],
        "source_truncated": len(source) > 18000,
        "execution": "Candidate source was read as text only; it was not imported or executed.",
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


def compare_skill_candidate(candidate_id: str) -> str:
    """Show candidate diff against the live built-in skill, if one exists."""
    try:
        _, metadata, candidate_source = _read_candidate(candidate_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Candidate comparison failed: {exc}"
    name = str(metadata.get("name", ""))
    baseline_path = _live_skill_path(name)
    try:
        with open(baseline_path, "r", encoding="utf-8") as handle:
            baseline_source = handle.read()
    except FileNotFoundError:
        baseline_source = ""
    except OSError as exc:
        return f"Could not read baseline skill: {exc}"

    baseline_sha = hashlib.sha256(baseline_source.encode("utf-8")).hexdigest() if baseline_source else None
    staged_baseline_sha = metadata.get("base_sha256")
    changed_since_staging = baseline_sha != staged_baseline_sha
    diff = "".join(difflib.unified_diff(
        baseline_source.splitlines(keepends=True),
        candidate_source.splitlines(keepends=True),
        fromfile=f"current/{name}/skill.py" if baseline_source else "/dev/null",
        tofile=f"candidate/{name}/skill.py",
        n=3,
    ))
    if changed_since_staging:
        status = "WARNING: live baseline changed since this candidate was staged; review against the current version."
    elif baseline_source:
        status = "Baseline unchanged since staging."
    else:
        status = "No built-in baseline existed when this comparison ran (or candidate was staged as a new skill)."
    return (
        f"Candidate: {candidate_id}\n"
        f"Candidate SHA-256: {metadata.get('sha256')}\n"
        f"Current live SHA-256: {baseline_sha or 'no live skill'}\n"
        f"SHA-256 at staging: {staged_baseline_sha or 'no live skill'}\n"
        f"{status}\n\n"
        f"{diff[:16000] or 'No diff available.'}"
    )


def stage_skill_candidate(name: str, code: str, rationale: str = "",
                          source: str = "") -> str:
    """Store a candidate in staging without loading or executing it."""
    name = str(name or "").strip().lower()
    code = str(code or "")
    rationale = str(rationale or "").strip()
    source = str(source or "").strip()
    if not _NAME_RE.fullmatch(name):
        return "Candidate not staged: name must be 2-40 lowercase letters, digits, or underscores and start with a letter."
    if not code.strip():
        return "Candidate not staged: source code is empty."
    if len(code.encode("utf-8")) > _MAX_SOURCE_BYTES:
        return "Candidate not staged: source code exceeds the 100 KB limit."
    try:
        tree = ast.parse(code, filename=f"{name}/skill.py")
    except SyntaxError as exc:
        return f"Candidate not staged: Python syntax error at line {exc.lineno}: {exc.msg}."

    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    candidate_id = f"{name}-{digest[:10]}"
    folder = _candidate_dir(candidate_id)
    os.makedirs(CANDIDATE_ROOT, exist_ok=True)
    os.makedirs(folder, exist_ok=True)
    code_path = os.path.join(folder, "skill.py")
    meta_path = os.path.join(folder, "candidate.json")
    if os.path.exists(meta_path):
        return f"Candidate already staged: {candidate_id}. No files were overwritten."

    baseline_sha = _sha256_file(_live_skill_path(name))
    metadata = {
        "candidate_id": candidate_id,
        "name": name,
        "sha256": digest,
        "base_sha256": baseline_sha,
        "rationale": rationale,
        "source": source,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "state": "staged",
        "static_evaluation": None,
        "tests_run": False,
        "activated": False,
    }
    with open(code_path, "x", encoding="utf-8") as handle:
        handle.write(code)
    _write_json_atomic(meta_path, metadata)
    return (
        f"Staged skill candidate '{candidate_id}'. It was parsed but not imported, "
        "executed, tested, or activated. Run evaluate_skill_candidate next."
    )


def _top_level_assignment(tree: ast.Module, variable: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == variable
            for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == variable:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
    return None


def evaluate_skill_candidate(candidate_id: str) -> str:
    """Run static checks only. Never import or execute staged candidate code."""
    try:
        folder = _candidate_dir(candidate_id)
        with open(os.path.join(folder, "candidate.json"), "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        code_path = os.path.join(folder, "skill.py")
        with open(code_path, "r", encoding="utf-8") as handle:
            code = handle.read()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Candidate evaluation failed: {exc}"

    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    errors = []
    warnings = []
    if digest != metadata.get("sha256"):
        errors.append("Source hash no longer matches the staged metadata.")
    current_baseline_sha = _sha256_file(_live_skill_path(str(metadata.get("name", ""))))
    if current_baseline_sha != metadata.get("base_sha256"):
        warnings.append("The live skill baseline changed since staging; compare and review the candidate against the current version before considering promotion.")
    metadata["current_base_sha256_at_evaluation"] = current_baseline_sha
    try:
        tree = ast.parse(code, filename=code_path)
    except SyntaxError as exc:
        tree = None
        errors.append(f"Python syntax error at line {exc.lineno}: {exc.msg}.")

    if tree is not None:
        allowed_top_level = (
            ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom,
            ast.FunctionDef, ast.AsyncFunctionDef, ast.Pass,
        )
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue  # module docstring
            if not isinstance(node, allowed_top_level):
                errors.append(
                    f"Top-level {type(node).__name__} statements are not allowed in a staged skill; "
                    "move runtime work inside handle()."
                )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    errors.append("Top-level assignments must contain literal data only.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.decorator_list:
                    errors.append(f"Function {node.name} uses decorators that would execute during import.")
                defaults = list(node.args.defaults) + [v for v in node.args.kw_defaults if v is not None]
                for value in defaults:
                    if any(isinstance(part, ast.Call) for part in ast.walk(value)):
                        errors.append(f"Function {node.name} has a call in its default argument.")
                annotations = [
                    arg.annotation for arg in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
                    if arg.annotation is not None
                ]
                if node.args.vararg and node.args.vararg.annotation is not None:
                    annotations.append(node.args.vararg.annotation)
                if node.args.kwarg and node.args.kwarg.annotation is not None:
                    annotations.append(node.args.kwarg.annotation)
                if node.returns is not None:
                    annotations.append(node.returns)
                if any(isinstance(part, ast.Call) for annotation in annotations for part in ast.walk(annotation)):
                    errors.append(f"Function {node.name} has a call in an annotation that may execute during import.")
        declared_name = _top_level_assignment(tree, "SKILL_NAME")
        description = _top_level_assignment(tree, "SKILL_DESCRIPTION")
        schemas = _top_level_assignment(tree, "TOOL_DEFINITIONS")
        handlers = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "handle"
        ]
        has_handler = bool(handlers)
        if declared_name != metadata.get("name"):
            errors.append("SKILL_NAME must be a literal string matching the candidate name.")
        if not isinstance(description, str) or not description.strip():
            errors.append("SKILL_DESCRIPTION must be a non-empty literal string.")
        if not isinstance(schemas, list) or not schemas:
            errors.append("TOOL_DEFINITIONS must be a non-empty literal list of tool schemas.")
        else:
            tool_names = []
            for schema in schemas:
                if not isinstance(schema, dict):
                    errors.append("Each tool schema must be a dictionary literal.")
                    continue
                function = schema.get("function")
                tool_name = function.get("name") if isinstance(function, dict) else None
                if not isinstance(tool_name, str) or not tool_name:
                    errors.append("Each tool schema needs function.name.")
                else:
                    tool_names.append(tool_name)
            if len(tool_names) != len(set(tool_names)):
                errors.append("Tool names inside the candidate must be unique.")
        if not has_handler:
            errors.append("Candidate must define a top-level handle(tool_name, args, services=None) function.")
        else:
            signature = handlers[0].args
            positional = list(signature.posonlyargs) + list(signature.args)
            if len(positional) < 3 and signature.vararg is None:
                errors.append("handle must accept the three arguments passed by the Jarvis skill loader.")

        risky_imports = set()
        risky_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                risky_imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                risky_imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"eval", "exec", "compile", "__import__"}:
                    risky_calls.add(func.id)
                elif isinstance(func, ast.Attribute) and func.attr in {"system", "popen", "Popen", "run", "spawn"}:
                    risky_calls.add(func.attr)
        watched = sorted(risky_imports.intersection({"subprocess", "socket", "ctypes", "winreg", "multiprocessing"}))
        if watched:
            warnings.append("Requires manual review for privileged/system/network modules: " + ", ".join(watched))
        if risky_calls:
            warnings.append("Requires manual review for dynamic execution or process-launch calls: " + ", ".join(sorted(risky_calls)))
        warnings.append("Static inspection cannot prove runtime safety. No candidate code or candidate tests were executed.")

    status = "STATIC_FAIL" if errors else "STATIC_PASS_REVIEW_REQUIRED"
    evaluation = {
        "status": status,
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_sha256": digest,
        "errors": errors,
        "warnings": warnings,
        "tests_run": False,
        "activated": False,
    }
    metadata["static_evaluation"] = evaluation
    metadata["state"] = status
    metadata["tests_run"] = False
    metadata["activated"] = False
    _write_json_atomic(os.path.join(folder, "candidate.json"), metadata)

    lines = [
        f"Candidate: {candidate_id}",
        f"Static result: {status}",
        "Runtime tests: NOT RUN",
        "Activated: NO",
    ]
    if errors:
        lines.append("Errors: " + " | ".join(errors))
    if warnings:
        lines.append("Review notes: " + " | ".join(warnings))
    if not errors:
        lines.append("Next: inspect the diff, supply focused tests, run them in an isolated test environment, and review before promotion.")
    return "\n".join(lines)

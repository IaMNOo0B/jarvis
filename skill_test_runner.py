"""Constrained subprocess runner for reviewed JARVIS skill test cases.

This reduces accidental access during tests; it is not a hardened OS sandbox.
Candidate code must remain inactive and should only be tested in a disposable
environment with no credentials or unrelated user data.
"""

import importlib.util
import json
import os
import sys
import sysconfig
import traceback


_BLOCKED_IMPORTS = {
    "subprocess", "ctypes", "multiprocessing", "winreg", "webbrowser",
    "_ctypes", "_multiprocessing", "_winapi", "_overlapped", "win32api",
    "win32file", "pywintypes", "mmap", "pycurl", "curl_cffi",
}
_BLOCKED_EVENTS = {
    "os.system", "os.exec", "os.fork", "os.forkpty", "os.spawn",
    "os.posix_spawn", "os.kill", "os.putenv", "os.unsetenv",
    "socket.__new__", "subprocess.Popen",
}


def _within(path, roots):
    try:
        real = os.path.realpath(os.fspath(path))
        for root in roots:
            root = os.path.realpath(root)
            if os.path.commonpath([root, real]) == root:
                return True
    except (TypeError, ValueError, OSError):
        return False
    return False


def _install_audit_guard(work_root):
    paths = sysconfig.get_paths()
    stdlib_roots = [paths.get("stdlib"), paths.get("platstdlib")]
    package_roots = [paths.get("purelib"), paths.get("platlib")]
    read_roots = [work_root] + [p for p in stdlib_roots + package_roots if p]
    write_root = os.path.realpath(work_root)
    # -S prevents site startup hooks; allow imports from global site-packages
    # explicitly only after this runner has started, with the audit guard on.
    for package_root in package_roots:
        if package_root and os.path.isdir(package_root) and package_root not in sys.path:
            sys.path.append(package_root)

    def guard(event, args):
        if event in _BLOCKED_EVENTS or event.startswith("socket.") or event.startswith("subprocess."):
            raise PermissionError(f"Blocked by JARVIS candidate-test policy: {event}")

        if event == "import" and args:
            name = str(args[0]).split(".", 1)[0].lower()
            if name in _BLOCKED_IMPORTS:
                raise PermissionError(f"Blocked import during candidate test: {name}")

        if event == "open" and args:
            path = args[0]
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if isinstance(path, int):
                if path not in (0, 1, 2):
                    raise PermissionError("Opening inherited file descriptors is blocked.")
                return
            if not isinstance(path, (str, bytes, os.PathLike)):
                raise PermissionError("Unsupported file path in candidate test.")
            writable = (
                isinstance(mode, str) and any(mark in mode for mark in ("w", "a", "x", "+"))
            ) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            allowed = _within(path, [write_root] if writable else read_roots)
            if not allowed:
                raise PermissionError("Candidate tests may only write inside the temporary test directory and read standard-library or temporary test files.")

        if event in {"os.remove", "os.unlink", "os.rename", "os.replace",
                     "os.mkdir", "os.rmdir", "os.chmod", "os.chown",
                     "os.link", "os.symlink", "os.truncate"}:
            for path in args[:2]:
                if isinstance(path, (str, bytes, os.PathLike)) and not _within(path, [write_root]):
                    raise PermissionError(f"Filesystem operation {event} is restricted to the temporary test directory.")

        if event in {"os.listdir", "os.scandir"} and args:
            path = args[0] if args[0] is not None else os.getcwd()
            if not _within(path, read_roots):
                raise PermissionError(f"Directory listing via {event} is restricted to the temporary test directory.")

        if event == "os.chdir" and args and not _within(args[0], [write_root]):
            raise PermissionError("Changing directory outside the temporary test directory is blocked.")

    sys.addaudithook(guard)


def _load_skill(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create a Python module loader for the skill.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    handle = getattr(module, "handle", None)
    if not callable(handle):
        raise TypeError("Skill has no callable handle() function.")
    return handle


def _assert_case(result, case):
    if result is not None and not isinstance(result, str):
        return False, f"handle() returned {type(result).__name__}, expected a string or None."

    if "expected_is_none" in case:
        expected = bool(case["expected_is_none"])
        if (result is None) != expected:
            return False, f"Expected is_none={expected}, got {result!r}."
    elif "expected_equals" in case:
        if result != case["expected_equals"]:
            return False, f"Expected {case['expected_equals']!r}, got {result!r}."
    elif "expected_contains" in case:
        needle = case["expected_contains"]
        if not isinstance(result, str) or needle not in result:
            return False, f"Expected result to contain {needle!r}, got {result!r}."
    else:
        return False, "Test case has no valid expectation."
    return True, "Expectation matched."


def _run_suite_for_skill(path, cases, label):
    handle = _load_skill(path, "jarvis_candidate_" + label)
    results = []
    for index, case in enumerate(cases):
        case_name = str(case.get("name") or f"case_{index + 1}")
        try:
            value = handle(str(case["tool_name"]), dict(case.get("args") or {}), None)
            passed, detail = _assert_case(value, case)
            results.append({
                "name": case_name,
                "kind": case.get("kind", "feature"),
                "passed": passed,
                "detail": detail,
                "actual": value if value is None or isinstance(value, str) else repr(value)[:500],
            })
        except BaseException as exc:
            results.append({
                "name": case_name,
                "kind": case.get("kind", "feature"),
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}",
                "actual": None,
            })
    return results


def _child(candidate_path, cases_path, baseline_path):
    work_root = os.path.realpath(os.path.dirname(candidate_path))
    os.chdir(work_root)
    try:
        with open(cases_path, "r", encoding="utf-8") as handle:
            cases = json.load(handle)
        _install_audit_guard(work_root)
        candidate_results = _run_suite_for_skill(candidate_path, cases, "candidate")
        baseline_results = None
        baseline_error = None
        regression_cases = [c for c in cases if c.get("kind", "feature") == "regression"]
        if baseline_path and os.path.isfile(baseline_path):
            try:
                baseline_results = _run_suite_for_skill(baseline_path, regression_cases, "baseline")
            except BaseException as exc:
                baseline_error = f"{type(exc).__name__}: {exc}"

        report = {
            "candidate_results": candidate_results,
            "baseline_results": baseline_results,
            "baseline_error": baseline_error,
            "regression_case_count": len(regression_cases),
            "runner_mode": "constrained_subprocess",
            "network_access": "blocked by Python audit policy",
            "filesystem": "writes limited to the temporary test directory; reads limited to temporary files and the standard library",
            "warning": "This is not a hardened OS security sandbox. Do not test untrusted candidates on a machine containing secrets or sensitive data.",
        }
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 0
    except BaseException as exc:
        print(json.dumps({
            "runner_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=5),
            "runner_mode": "constrained_subprocess",
        }), flush=True)
        return 2


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        return _child(sys.argv[2], sys.argv[3], sys.argv[4] or "")
    print("This module is an internal candidate-test runner.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

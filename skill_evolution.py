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
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from paths import user_file


CANDIDATE_ROOT = user_file("skill_candidates")
LIVE_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}-[0-9a-f]{10}$")
_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}-[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
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
    root = os.path.realpath(CANDIDATE_ROOT)
    target = os.path.realpath(os.path.join(root, candidate_id))
    if os.path.commonpath([root, target]) != root:
        raise ValueError("Candidate path is outside the staging directory.")
    return target


def _live_skill_path(name: str) -> str:
    name = str(name or "")
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Invalid live skill name.")
    root = os.path.realpath(LIVE_SKILLS_DIR)
    raw_folder = os.path.join(LIVE_SKILLS_DIR, name)
    raw_target = os.path.join(raw_folder, "skill.py")
    if os.path.islink(raw_folder) or os.path.islink(raw_target):
        raise ValueError("Live skill folders and skill.py files must not be symlinks.")
    target = os.path.realpath(raw_target)
    if os.path.commonpath([root, target]) != root:
        raise ValueError("Live skill path resolves outside the skills directory.")
    return target


def _sha256_file(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="skill-version-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _atomic_write_text(path: str, payload: str) -> None:
    _atomic_write_bytes(path, payload.encode("utf-8"))


def _version_root() -> str:
    return os.path.join(os.path.realpath(CANDIDATE_ROOT), "versions")


def _version_dir(version_id: str) -> str:
    version_id = str(version_id or "").strip()
    if not _VERSION_RE.fullmatch(version_id):
        raise ValueError("Invalid version ID.")
    root = os.path.realpath(_version_root())
    target = os.path.realpath(os.path.join(root, version_id))
    if os.path.commonpath([root, target]) != root:
        raise ValueError("Version path resolves outside the version archive.")
    return target


def _read_version(version_id: str) -> tuple[str, dict]:
    folder = _version_dir(version_id)
    with open(os.path.join(folder, "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or manifest.get("version_id") != version_id:
        raise ValueError("Version manifest does not match the requested version ID.")
    if not _NAME_RE.fullmatch(str(manifest.get("name") or "")):
        raise ValueError("Version manifest contains an invalid skill name.")
    return folder, manifest


def _read_candidate(candidate_id: str) -> tuple[str, dict, str]:
    folder = _candidate_dir(candidate_id)
    with open(os.path.join(folder, "candidate.json"), "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict):
        raise ValueError("Candidate metadata must be a JSON object.")
    name = str(metadata.get("name") or "")
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Candidate metadata contains an invalid skill name.")
    if metadata.get("candidate_id") != candidate_id or not candidate_id.startswith(name + "-"):
        raise ValueError("Candidate ID does not match its metadata.")
    with open(os.path.join(folder, "skill.py"), "r", encoding="utf-8") as handle:
        source = handle.read()
    return folder, metadata, source


def test_skill_candidate(candidate_id: str, timeout_seconds: int = 15) -> str:
    """Run supplied feature/regression cases in a constrained, disposable child process."""
    static_report = evaluate_skill_candidate(candidate_id)
    if "Static result: STATIC_PASS_REVIEW_REQUIRED" not in static_report:
        return (
            "Candidate tests not run: static evaluation must pass first.\n"
            + static_report
        )

    try:
        folder, metadata, candidate_source = _read_candidate(candidate_id)
        cases = _validate_test_cases(metadata.get("test_cases"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Candidate tests not run: {exc}"

    runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_test_runner.py")
    if not os.path.isfile(runner_path):
        return "Candidate tests not run: skill_test_runner.py is missing from the application bundle."
    if getattr(sys, "frozen", False):
        interpreter = shutil.which("python") or shutil.which("python3")
        if not interpreter:
            return "Candidate tests not run: a standalone Python interpreter is required; static evaluation remains available."
    else:
        interpreter = sys.executable

    name = str(metadata.get("name") or "")
    current_baseline_path = _live_skill_path(name)
    current_baseline_sha = _sha256_file(current_baseline_path)
    has_regressions = any(case["kind"] == "regression" for case in cases)
    baseline_source = ""
    if current_baseline_sha:
        try:
            with open(current_baseline_path, "r", encoding="utf-8") as handle:
                baseline_source = handle.read()
        except OSError as exc:
            return f"Candidate tests not run: could not read the current baseline: {exc}"
    baseline_available = bool(baseline_source and has_regressions)

    if has_regressions and not baseline_available:
        return (
            "Candidate tests not run: regression cases were supplied, but there is no readable "
            "current baseline skill to compare. Use feature cases for a new skill."
        )

    try:
        test_timeout = max(3, min(int(timeout_seconds), 30))
    except (TypeError, ValueError):
        test_timeout = 15

    metadata["state"] = "TESTING"
    metadata["activated"] = False
    _write_json_atomic(os.path.join(folder, "candidate.json"), metadata)

    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-skill-tests-") as temp_root:
            candidate_path = os.path.join(temp_root, "candidate_skill.py")
            cases_path = os.path.join(temp_root, "test_cases.json")
            baseline_path = os.path.join(temp_root, "baseline_skill.py") if baseline_available else ""
            with open(candidate_path, "x", encoding="utf-8") as handle:
                handle.write(candidate_source)
            with open(cases_path, "x", encoding="utf-8") as handle:
                json.dump(cases, handle, ensure_ascii=False)
            if baseline_available:
                with open(baseline_path, "x", encoding="utf-8") as handle:
                    handle.write(baseline_source)

            stdout_path = os.path.join(temp_root, "runner.stdout")
            stderr_path = os.path.join(temp_root, "runner.stderr")
            env = {
                key: os.environ[key]
                for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "LANG", "LC_ALL")
                if os.environ.get(key)
            }
            env["PYTHONUTF8"] = "1"
            cmd = [
                interpreter, "-I", "-S", runner_path, "--child",
                candidate_path, cases_path, baseline_path,
            ]
            start = time.monotonic()
            with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
                proc = subprocess.Popen(
                    cmd, cwd=temp_root, env=env, stdout=out, stderr=err,
                    stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                timed_out = False
                output_limited = False
                while proc.poll() is None:
                    if time.monotonic() - start > test_timeout:
                        timed_out = True
                        proc.kill()
                        break
                    if os.path.getsize(stdout_path) > 1_000_000 or os.path.getsize(stderr_path) > 1_000_000:
                        output_limited = True
                        proc.kill()
                        break
                    time.sleep(0.05)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            with open(stdout_path, "r", encoding="utf-8", errors="replace") as handle:
                stdout = handle.read()[-1_000_000:]
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as handle:
                stderr = handle.read()[-1_000_000:]

        if timed_out:
            report = {"status": "TEST_TIMEOUT", "error": f"Candidate test process exceeded {test_timeout} seconds."}
        elif output_limited:
            report = {"status": "TEST_OUTPUT_LIMIT", "error": "Candidate test process exceeded the 1 MB output limit."}
        else:
            report = None
            for line in reversed(stdout.splitlines()):
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict) and ("candidate_results" in parsed or "runner_error" in parsed):
                    report = parsed
                    break
            if report is None:
                report = {
                    "status": "TEST_RUNNER_ERROR",
                    "error": "Runner did not return a structured report.",
                    "return_code": proc.returncode,
                    "stderr": stderr[-3000:],
                }

        if "candidate_results" in report:
            candidate_rows = report.get("candidate_results") or []
            baseline_rows = report.get("baseline_results") or []
            baseline_by_name = {row.get("name"): row for row in baseline_rows}
            failures = [row for row in candidate_rows if not row.get("passed")]
            regression_rows = [row for row in candidate_rows if row.get("kind") == "regression"]
            baseline_failures = []
            candidate_regressions = []
            for row in regression_rows:
                baseline_row = baseline_by_name.get(row.get("name"))
                if not baseline_row or not baseline_row.get("passed"):
                    baseline_failures.append(row.get("name"))
                elif not row.get("passed"):
                    candidate_regressions.append(row.get("name"))

            report["candidate_passed"] = len(candidate_rows) - len(failures)
            report["candidate_failed"] = len(failures)
            report["baseline_failures"] = baseline_failures
            report["candidate_regressions"] = candidate_regressions
            if report.get("baseline_error"):
                final_state = "BASELINE_TEST_INVALID"
            elif baseline_failures:
                final_state = "BASELINE_TEST_INVALID"
            elif failures:
                final_state = "TEST_FAIL"
            elif not regression_rows:
                final_state = "TEST_PASS_NO_REGRESSION_COVERAGE"
            else:
                final_state = "TEST_PASS_REVIEW_REQUIRED"
            report["status"] = final_state
            report["live_baseline_sha256"] = current_baseline_sha
            report["base_changed_since_staging"] = current_baseline_sha != metadata.get("base_sha256")
        else:
            runner_error = str(report.get("runner_error") or report.get("error") or "")
            if "PermissionError" in runner_error or "Blocked import" in runner_error or "Blocked by JARVIS" in runner_error:
                final_state = "TEST_BLOCKED"
            else:
                final_state = str(report.get("status") or "TEST_RUNNER_ERROR")

        metadata["state"] = final_state
        metadata["tests_run"] = True
        metadata["test_report"] = report
        metadata["tested_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata["tested_source_sha256"] = hashlib.sha256(candidate_source.encode("utf-8")).hexdigest()
        metadata["tested_baseline_sha256"] = current_baseline_sha
        metadata["activated"] = False
        _write_json_atomic(os.path.join(folder, "candidate.json"), metadata)
        return json.dumps({
            "candidate_id": candidate_id,
            "status": final_state,
            "tests_run": True,
            "activated": False,
            "report": report,
        }, indent=2, ensure_ascii=False)
    except Exception as exc:
        metadata["state"] = "TEST_RUNNER_ERROR"
        metadata["tests_run"] = False
        metadata["activated"] = False
        metadata["test_report"] = {"error": f"{type(exc).__name__}: {exc}"}
        _write_json_atomic(os.path.join(folder, "candidate.json"), metadata)
        return f"Candidate test runner failed: {type(exc).__name__}: {exc}"


def promote_skill_candidate(candidate_id: str, approval_token: str = "") -> str:
    """Atomically install a tested candidate with a versioned rollback snapshot."""
    if str(approval_token or "") != str(candidate_id or ""):
        return (
            f"CONFIRM_REQUIRED:{candidate_id}. No files were changed. "
            "Ask Sir to explicitly approve promotion of this exact candidate ID; "
            "then pass that exact ID as approval_token."
        )
    try:
        folder, metadata, candidate_source = _read_candidate(candidate_id)
        name = str(metadata["name"])
        source_sha = hashlib.sha256(candidate_source.encode("utf-8")).hexdigest()
        if metadata.get("sha256") != source_sha:
            return "Promotion refused: candidate source no longer matches its recorded hash."
        if not metadata.get("tests_run") or metadata.get("tested_source_sha256") != source_sha:
            return "Promotion refused: this exact candidate source has not completed its test suite."
        accepted_states = {"TEST_PASS_REVIEW_REQUIRED", "TEST_PASS_NO_REGRESSION_COVERAGE"}
        report = metadata.get("test_report") or {}
        if metadata.get("state") not in accepted_states or report.get("status") not in accepted_states:
            return f"Promotion refused: latest candidate state is {metadata.get('state')!r}, not a passing review state."
        if report.get("candidate_failed", 0) != 0:
            return "Promotion refused: one or more candidate tests failed."
        if metadata.get("activated") or metadata.get("promoted"):
            return "Promotion refused: candidate has already been promoted; inspect its version history."
        live_path = _live_skill_path(name)
        current_sha = _sha256_file(live_path)
        tested_baseline_sha = metadata.get("tested_baseline_sha256")
        if current_sha != tested_baseline_sha:
            return (
                "Promotion refused: the live skill changed after testing. "
                "Compare the new baseline, then run the candidate tests again."
            )

        previous_bytes = None
        if current_sha is not None:
            with open(live_path, "rb") as handle:
                previous_bytes = handle.read()
            if hashlib.sha256(previous_bytes).hexdigest() != current_sha:
                return "Promotion refused: could not verify the live baseline before backup."

        created = datetime.now().astimezone()
        version_id = f"{name}-{created.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        version_folder = _version_dir(version_id)
        os.makedirs(version_folder, exist_ok=False)
        previous_sha = current_sha
        if previous_bytes is not None:
            _atomic_write_bytes(os.path.join(version_folder, "previous_skill.py"), previous_bytes)

        manifest = {
            "version_id": version_id,
            "name": name,
            "candidate_id": candidate_id,
            "created_at": created.isoformat(timespec="seconds"),
            "state": "PROMOTION_PREPARED",
            "live_relative_path": os.path.join(name, "skill.py"),
            "previous_exists": previous_bytes is not None,
            "previous_sha256": previous_sha,
            "promoted_sha256": source_sha,
            "backup_file": "previous_skill.py" if previous_bytes is not None else None,
            "tested_at": metadata.get("tested_at"),
            "tested_baseline_sha256": tested_baseline_sha,
            "tests_status": report.get("status"),
            "rollback_available": previous_bytes is not None,
        }
        _write_json_atomic(os.path.join(version_folder, "manifest.json"), manifest)

        try:
            _atomic_write_text(live_path, candidate_source)
            if _sha256_file(live_path) != source_sha:
                raise OSError("Installed skill hash did not match the tested candidate hash.")
            manifest["state"] = "PROMOTED_PENDING_RESTART"
            manifest["promoted_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _write_json_atomic(os.path.join(version_folder, "manifest.json"), manifest)
        except Exception as exc:
            try:
                if previous_bytes is not None:
                    _atomic_write_bytes(live_path, previous_bytes)
                elif os.path.isfile(live_path) and not os.path.islink(live_path):
                    os.remove(live_path)
                manifest["state"] = "PROMOTION_FAILED_RESTORED"
                manifest["failure"] = f"{type(exc).__name__}: {exc}"
                _write_json_atomic(os.path.join(version_folder, "manifest.json"), manifest)
            except Exception as rollback_exc:
                return (
                    f"CRITICAL: promotion verification failed ({exc}) and automatic recovery "
                    f"also failed ({rollback_exc}). Version archive: {version_id}. "
                    "Do not restart Jarvis until the live skill has been inspected."
                )
            return f"Promotion failed and the previous live file was restored: {exc}. Version archive: {version_id}."

        metadata["state"] = "PROMOTED_PENDING_RESTART"
        metadata["promoted"] = True
        metadata["promoted_at"] = manifest["promoted_at"]
        metadata["version_id"] = version_id
        metadata["promoted_sha256"] = source_sha
        metadata["activated"] = False
        _write_json_atomic(os.path.join(folder, "candidate.json"), metadata)
        return json.dumps({
            "status": "PROMOTED_PENDING_RESTART",
            "candidate_id": candidate_id,
            "version_id": version_id,
            "live_path": live_path,
            "installed_sha256": source_sha,
            "previous_sha256": previous_sha,
            "backup_saved": previous_bytes is not None,
            "restart_required": True,
            "activated": False,
            "message": "Candidate file was atomically installed and versioned. Restart Jarvis to load it; tests do not prove it is risk-free.",
        }, indent=2, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Promotion refused or failed without a verified install: {type(exc).__name__}: {exc}"


def rollback_skill_version(version_id: str, approval_token: str = "") -> str:
    """Restore a promoted version's previous file after exact-version approval."""
    if str(approval_token or "") != str(version_id or ""):
        return (
            f"CONFIRM_REQUIRED:{version_id}. No files were changed. "
            "Ask Sir to explicitly approve rollback of this exact version ID; "
            "then pass that exact ID as approval_token."
        )
    try:
        version_folder, manifest = _read_version(version_id)
        if manifest.get("state") == "ROLLED_BACK":
            return f"Version {version_id} has already been rolled back."
        if manifest.get("state") != "PROMOTED_PENDING_RESTART":
            return f"Rollback refused: version state is {manifest.get('state')!r}."
        name = str(manifest["name"])
        live_path = _live_skill_path(name)
        current_sha = _sha256_file(live_path)
        if current_sha != manifest.get("promoted_sha256"):
            return (
                "Rollback refused: the live file differs from this promotion. "
                "Inspect the current diff and create a reviewed recovery action."
            )

        if manifest.get("previous_exists"):
            backup_path = os.path.join(version_folder, "previous_skill.py")
            with open(backup_path, "rb") as handle:
                backup_bytes = handle.read()
            if hashlib.sha256(backup_bytes).hexdigest() != manifest.get("previous_sha256"):
                return "Rollback refused: the archived previous file failed its SHA-256 check."
            _atomic_write_bytes(live_path, backup_bytes)
            restored_sha = _sha256_file(live_path)
            if restored_sha != manifest.get("previous_sha256"):
                return "CRITICAL: rollback file verification failed; inspect the live skill before restarting."
        else:
            if not os.path.isfile(live_path) or os.path.islink(live_path):
                return "Rollback refused: expected newly created skill file is missing or is a symlink."
            os.remove(live_path)
            restored_sha = None

        manifest["state"] = "ROLLED_BACK"
        manifest["rolled_back_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        manifest["restored_sha256"] = restored_sha
        _write_json_atomic(os.path.join(version_folder, "manifest.json"), manifest)

        candidate_id = str(manifest.get("candidate_id") or "")
        try:
            candidate_folder, candidate_metadata, _ = _read_candidate(candidate_id)
            candidate_metadata["state"] = "ROLLED_BACK"
            candidate_metadata["promoted"] = False
            candidate_metadata["activated"] = False
            candidate_metadata["rolled_back_at"] = manifest["rolled_back_at"]
            _write_json_atomic(os.path.join(candidate_folder, "candidate.json"), candidate_metadata)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        return json.dumps({
            "status": "ROLLED_BACK",
            "version_id": version_id,
            "live_path": live_path,
            "restored_sha256": restored_sha,
            "previous_file_restored": bool(manifest.get("previous_exists")),
            "restart_required": True,
            "message": "The live file was restored atomically. Restart Jarvis to load the restored skill.",
        }, indent=2, ensure_ascii=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"Rollback refused or failed: {type(exc).__name__}: {exc}"


def list_skill_versions(limit: int = 20) -> str:
    """List version manifests and rollback state without executing skill code."""
    root = _version_root()
    if not os.path.isdir(root):
        return "No promoted skill versions found."
    rows = []
    try:
        for version_id in sorted(os.listdir(root), reverse=True):
            if not _VERSION_RE.fullmatch(version_id):
                continue
            try:
                _, manifest = _read_version(version_id)
                rows.append({
                    "version_id": version_id,
                    "name": manifest.get("name"),
                    "candidate_id": manifest.get("candidate_id"),
                    "state": manifest.get("state"),
                    "created_at": manifest.get("created_at"),
                    "promoted_at": manifest.get("promoted_at"),
                    "rolled_back_at": manifest.get("rolled_back_at"),
                    "previous_sha256": manifest.get("previous_sha256"),
                    "promoted_sha256": manifest.get("promoted_sha256"),
                    "rollback_available": manifest.get("rollback_available", False),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                rows.append({"version_id": version_id, "state": "manifest_error"})
            if len(rows) >= max(1, min(int(limit), 50)):
                break
    except OSError as exc:
        return f"Could not list skill versions: {exc}"
    return "Skill version history:\n" + json.dumps(rows, indent=2, ensure_ascii=False)


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


def _validate_test_cases(test_cases):
    if not isinstance(test_cases, list) or not test_cases:
        raise ValueError("Provide a non-empty list of test cases.")
    if len(test_cases) > 20:
        raise ValueError("At most 20 test cases are allowed per candidate.")
    clean = []
    allowed_keys = {
        "name", "tool_name", "args", "kind", "expected_equals",
        "expected_contains", "expected_is_none",
    }
    for index, raw in enumerate(test_cases, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Test case {index} must be an object.")
        unknown = set(raw) - allowed_keys
        if unknown:
            raise ValueError(f"Test case {index} has unsupported keys: {', '.join(sorted(unknown))}.")
        tool_name = raw.get("tool_name")
        args = raw.get("args", {})
        kind = raw.get("kind", "feature")
        if not isinstance(tool_name, str) or not tool_name.strip() or len(tool_name) > 128:
            raise ValueError(f"Test case {index} needs a tool_name (1-128 characters).")
        if not isinstance(args, dict):
            raise ValueError(f"Test case {index} args must be an object.")
        if kind not in {"feature", "regression"}:
            raise ValueError(f"Test case {index} kind must be feature or regression.")
        expectations = [key for key in ("expected_equals", "expected_contains", "expected_is_none") if key in raw]
        if len(expectations) != 1:
            raise ValueError(f"Test case {index} must contain exactly one expected_* assertion.")
        if "expected_equals" in raw and not isinstance(raw["expected_equals"], (str, type(None))):
            raise ValueError(f"Test case {index} expected_equals must be text or null.")
        if "expected_contains" in raw and not isinstance(raw["expected_contains"], str):
            raise ValueError(f"Test case {index} expected_contains must be text.")
        if "expected_is_none" in raw and not isinstance(raw["expected_is_none"], bool):
            raise ValueError(f"Test case {index} expected_is_none must be true or false.")
        try:
            encoded_args = json.dumps(args, ensure_ascii=False)
            if len(encoded_args.encode("utf-8")) > 10_000:
                raise ValueError(f"Test case {index} args exceed 10 KB.")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Test case {index} args must be JSON data: {exc}") from exc
        item = {
            "name": str(raw.get("name") or f"case_{index}")[:120],
            "tool_name": tool_name.strip(),
            "args": args,
            "kind": kind,
            expectations[0]: raw[expectations[0]],
        }
        clean.append(item)
    return clean


def stage_skill_candidate(name: str, code: str, rationale: str = "",
                          source: str = "", tests=None) -> str:
    """Store a candidate in staging without loading or executing it."""
    name = str(name or "").strip().lower()
    code = str(code or "")
    rationale = str(rationale or "").strip()
    source = str(source or "").strip()
    try:
        clean_tests = _validate_test_cases(tests) if tests is not None else []
    except ValueError as exc:
        return f"Candidate tests were not accepted: {exc}"
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
        "test_cases": clean_tests,
        "static_evaluation": None,
        "test_report": None,
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
        folder, metadata, code = _read_candidate(candidate_id)
        code_path = os.path.join(folder, "skill.py")
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

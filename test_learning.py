import json
import os
import tempfile
import unittest

import memory
import skill_evolution


class MemoryLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_paths = (memory.MEMORY_FILE, memory.MEMORY_DIR, memory.NOTES_FILE)
        memory.MEMORY_DIR = self.temp.name
        memory.MEMORY_FILE = os.path.join(self.temp.name, "knowledge.json")
        memory.NOTES_FILE = os.path.join(self.temp.name, "notes.md")
        self.bank = memory.MemoryBank()

    def tearDown(self):
        memory.MEMORY_FILE, memory.MEMORY_DIR, memory.NOTES_FILE = self.old_paths
        self.temp.cleanup()

    def test_learning_record_keeps_evidence_and_starts_unverified(self):
        message = self.bank.save_knowledge(
            title="Retry pattern",
            content="Retry only transient network failures.",
            source="https://example.test/docs",
            evidence=["https://example.test/docs", "test: retry_transient_error"],
            confidence=0.7,
            outcome="The bounded retry test passed.",
        )
        self.assertIn("unverified", message)
        with open(memory.MEMORY_FILE, encoding="utf-8") as handle:
            entries = json.load(handle)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["validation_status"], "unverified")
        self.assertEqual(len(entries[0]["evidence"]), 2)
        self.assertEqual(entries[0]["confidence"], 0.7)

    def test_task_outcome_keeps_reward_evidence_and_status(self):
        result = self.bank.record_task_outcome(
            task="Load a candidate skill",
            status="failure",
            result="The Python import failed with a syntax error.",
            evidence=["tool: execute_code returned SyntaxError", "path: skill_candidates/demo/skill.py"],
            user_feedback="Sir asked to fix the syntax error.",
        )
        self.assertIn("failure", result)
        with open(memory.MEMORY_FILE, encoding="utf-8") as handle:
            entries = json.load(handle)
        episode = entries[0]
        self.assertEqual(episode["record_type"], "task_outcome")
        self.assertEqual(episode["outcome_status"], "failure")
        self.assertEqual(episode["reward"], -1.0)
        self.assertEqual(episode["validation_status"], "unverified")
        self.assertEqual(episode["validation_evidence"], [])
        self.assertEqual(len(episode["evidence"]), 2)
        summary = self.bank.search_memory("candidate skill", status="unverified")
        self.assertIn("Reward signal: -1.0", summary)
        self.assertIn("Task status: failure", summary)

    def test_recall_searches_provenance_and_evidence(self):
        self.bank.save_knowledge(
            title="Provider quota handling",
            content="Retry only after transient limit responses.",
            source="provider documentation",
            evidence=["https://docs.example.test/rate-limit"],
        )
        result = self.bank.search_memory("rate-limit")
        self.assertIn("Provider quota handling", result)
        self.assertIn("https://docs.example.test/rate-limit", result)

    def test_validated_record_wins_relevance_ties(self):
        self.bank.save_knowledge("Verified ledger guide", "The ledger stores learning outcomes.")
        with open(memory.MEMORY_FILE, encoding="utf-8") as handle:
            entry_id = json.load(handle)[0]["id"]
        self.bank.validate_knowledge(
            entry_id, ["test: ledger behaviour"], "The focused memory test passed."
        )
        self.bank.save_knowledge("Recent ledger note", "The ledger stores learning outcomes.")
        result = self.bank.search_memory("ledger", top_k=2)
        self.assertLess(result.find("Verified ledger guide"), result.find("Recent ledger note"))

    def test_validation_requires_evidence_and_records_outcome(self):
        self.bank.save_knowledge("Lesson", "Test-backed lesson", source="test")
        with open(memory.MEMORY_FILE, encoding="utf-8") as handle:
            entry_id = json.load(handle)[0]["id"]
        missing = self.bank.validate_knowledge(entry_id, [], "Passed")
        self.assertIn("not validated", missing)
        success = self.bank.validate_knowledge(
            entry_id, ["test: test_lesson", "https://docs.example.test"], "Passed"
        )
        self.assertIn("validated", success)
        self.assertIn("status: validated", self.bank.search_memory("lesson", status="validated"))

    def test_corrupt_memory_is_not_silently_reset(self):
        with open(memory.MEMORY_FILE, "w", encoding="utf-8") as handle:
            handle.write("{ this is not valid JSON")
        with self.assertRaises(memory.MemoryDataError):
            self.bank.save_knowledge("Do not overwrite", "Keep the broken file for recovery.")
        with open(memory.MEMORY_FILE, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{ this is not valid JSON")


class SkillCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = skill_evolution.CANDIDATE_ROOT
        self.old_live_root = skill_evolution.LIVE_SKILLS_DIR
        skill_evolution.CANDIDATE_ROOT = self.temp.name
        skill_evolution.LIVE_SKILLS_DIR = os.path.join(self.temp.name, "live")

    def tearDown(self):
        skill_evolution.CANDIDATE_ROOT = self.old_root
        skill_evolution.LIVE_SKILLS_DIR = self.old_live_root
        self.temp.cleanup()

    def test_candidate_is_staged_and_static_checked_without_activation(self):
        source = '''"""Tiny demonstration skill."""
SKILL_NAME = "demo_skill"
SKILL_DESCRIPTION = "A test-only demonstration skill."
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "demo_tool",
            "description": "Demo tool",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def handle(tool_name, args, services=None):
    return None
'''
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "demo_skill", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write('SKILL_NAME = "demo_skill"\\n# previous version\\n')
        message = skill_evolution.stage_skill_candidate(
            "demo_skill", source, rationale="Unit test", source="test suite"
        )
        self.assertIn("Staged skill candidate", message)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("STATIC_PASS_REVIEW_REQUIRED", result)
        self.assertIn("Runtime tests: NOT RUN", result)
        self.assertIn("Activated: NO", result)
        listing = skill_evolution.list_skill_candidates()
        self.assertIn(candidate_id, listing)
        inspection = json.loads(skill_evolution.inspect_skill_candidate(candidate_id))
        self.assertIn("candidate_source", inspection)
        self.assertIn('SKILL_NAME = "demo_skill"', inspection["candidate_source"])
        diff = skill_evolution.compare_skill_candidate(candidate_id)
        self.assertIn("Baseline unchanged since staging", diff)
        self.assertIn("previous version", diff)
        with open(os.path.join(self.temp.name, candidate_id, "candidate.json"), encoding="utf-8") as handle:
            metadata = json.load(handle)
        self.assertEqual(metadata["base_sha256"], metadata["current_base_sha256_at_evaluation"])
        self.assertFalse(metadata["activated"])
        self.assertFalse(metadata["tests_run"])

    def test_candidate_flags_live_baseline_change(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "change_skill", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write('SKILL_NAME = "change_skill"\\n')
        source = '''SKILL_NAME = "change_skill"
SKILL_DESCRIPTION = "Baseline change test."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "change_tool", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return None
'''
        message = skill_evolution.stage_skill_candidate("change_skill", source)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write('SKILL_NAME = "change_skill"\\n# changed after staging\\n')
        result = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("STATIC_PASS_REVIEW_REQUIRED", result)
        self.assertIn("live skill baseline changed since staging", result)

    def test_candidate_metadata_path_traversal_is_rejected(self):
        source = '''SKILL_NAME = "path_skill"
SKILL_DESCRIPTION = "Metadata path check."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "path_tool", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return None
'''
        message = skill_evolution.stage_skill_candidate("path_skill", source)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        metadata_path = os.path.join(self.temp.name, candidate_id, "candidate.json")
        with open(metadata_path, encoding="utf-8") as handle:
            metadata = json.load(handle)
        metadata["name"] = "../../outside"
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle)
        result = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("invalid skill name", result)

    def test_class_body_and_decorator_side_effect_patterns_are_rejected(self):
        source = '''SKILL_NAME = "risk_skill"
SKILL_DESCRIPTION = "Import-time side-effect test."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "risk_tool", "parameters": {"type": "object"}}}]
def decorate(fn):
    return fn
@decorate
def handle(tool_name, args, services=None):
    return None
'''
        message = skill_evolution.stage_skill_candidate("risk_skill", source)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("STATIC_FAIL", result)
        self.assertIn("decorators that would execute during import", result)

    def test_candidate_feature_and_baseline_regression_suite(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "demo_suite", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "demo_suite"
SKILL_DESCRIPTION = "Known-good baseline."
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "demo_suite_echo", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}},
]
def handle(tool_name, args, services=None):
    if tool_name == "demo_suite_echo":
        return "OK:" + str((args or {}).get("text", ""))
    return None
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        candidate = '''SKILL_NAME = "demo_suite"
SKILL_DESCRIPTION = "Echo and uppercase text."
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "demo_suite_echo", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "demo_suite_upper", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}},
]
def handle(tool_name, args, services=None):
    args = args or {}
    if tool_name == "demo_suite_echo":
        return "OK:" + str(args.get("text", ""))
    if tool_name == "demo_suite_upper":
        return str(args.get("text", "")).upper()
    return None
'''
        test_cases = [
            {
                "name": "existing echo behaviour",
                "kind": "regression",
                "tool_name": "demo_suite_echo",
                "args": {"text": "hello"},
                "expected_equals": "OK:hello",
            },
            {
                "name": "new uppercase feature",
                "kind": "feature",
                "tool_name": "demo_suite_upper",
                "args": {"text": "hello"},
                "expected_equals": "HELLO",
            },
        ]
        message = skill_evolution.stage_skill_candidate(
            "demo_suite", candidate, source="test fixture", tests=test_cases
        )
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        static = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("STATIC_PASS_REVIEW_REQUIRED", static)
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_PASS_REVIEW_REQUIRED", report)
        self.assertEqual(report["report"]["candidate_passed"], 2)
        self.assertEqual(report["report"]["candidate_failed"], 0)
        self.assertEqual(report["report"]["regression_case_count"], 1)
        self.assertEqual(report["report"]["candidate_regressions"], [])
        self.assertFalse(report["activated"])
        with open(os.path.join(self.temp.name, candidate_id, "candidate.json"), encoding="utf-8") as handle:
            metadata = json.load(handle)
        self.assertTrue(metadata["tests_run"])
        self.assertFalse(metadata["activated"])

    def test_candidate_regression_is_detected(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "regress_demo", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "regress_demo"
SKILL_DESCRIPTION = "Known-good baseline."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "regress_demo_echo", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "baseline-ok"
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        candidate = '''SKILL_NAME = "regress_demo"
SKILL_DESCRIPTION = "Broken replacement."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "regress_demo_echo", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "broken"
'''
        test_cases = [{
            "name": "preserve existing echo",
            "kind": "regression",
            "tool_name": "regress_demo_echo",
            "args": {},
            "expected_equals": "baseline-ok",
        }]
        message = skill_evolution.stage_skill_candidate("regress_demo", candidate, tests=test_cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_FAIL", report)
        self.assertEqual(report["report"]["candidate_regressions"], ["preserve existing echo"])
        self.assertFalse(report["activated"])

    def test_candidate_test_runner_blocks_network_imports(self):
        candidate = '''import socket
SKILL_NAME = "blocked_demo"
SKILL_DESCRIPTION = "Network socket creation must be blocked."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "blocked_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    try:
        sock = socket.socket()
        sock.close()
    except PermissionError:
        return "network blocked"
    return "unexpected"
'''
        test_cases = [{
            "name": "network socket creation blocked",
            "kind": "feature",
            "tool_name": "blocked_demo_run",
            "args": {},
            "expected_equals": "network blocked",
        }]
        message = skill_evolution.stage_skill_candidate("blocked_demo", candidate, tests=test_cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_PASS_NO_REGRESSION_COVERAGE", report)
        self.assertFalse(report["activated"])

    def test_candidate_test_runner_blocks_direct_low_level_socket_creation(self):
        candidate = '''import _socket
SKILL_NAME = "raw_socket_demo"
SKILL_DESCRIPTION = "Direct low-level socket creation must be blocked."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "raw_socket_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    try:
        sock = _socket.socket()
        sock.close()
    except PermissionError:
        return "low-level network blocked"
    return "unexpected"
'''
        cases = [{
            "name": "raw socket creation blocked",
            "kind": "feature",
            "tool_name": "raw_socket_demo_run",
            "args": {},
            "expected_equals": "low-level network blocked",
        }]
        staged = skill_evolution.stage_skill_candidate("raw_socket_demo", candidate, tests=cases)
        candidate_id = staged.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(result["status"], "TEST_PASS_NO_REGRESSION_COVERAGE", result)
        self.assertFalse(result["activated"])

    def test_candidate_test_runner_blocks_reads_outside_temporary_area(self):
        secret_path = os.path.join(self.temp.name, "outside_file.txt")
        with open(secret_path, "w", encoding="utf-8") as handle:
            handle.write("must not be readable")
        candidate = f'''SKILL_NAME = "file_guard_demo"
SKILL_DESCRIPTION = "Filesystem guard test."
TOOL_DEFINITIONS = [{{"type": "function", "function": {{"name": "file_guard_demo_read", "parameters": {{"type": "object"}}}}}}]
def handle(tool_name, args, services=None):
    try:
        open({secret_path!r}, "r", encoding="utf-8").read()
    except PermissionError:
        return "blocked"
    return "unexpected-read"
'''
        test_cases = [{
            "name": "outside read blocked",
            "kind": "feature",
            "tool_name": "file_guard_demo_read",
            "args": {},
            "expected_equals": "blocked",
        }]
        message = skill_evolution.stage_skill_candidate("file_guard_demo", candidate, tests=test_cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_PASS_NO_REGRESSION_COVERAGE", report)
        self.assertEqual(report["report"]["candidate_passed"], 1)
        self.assertFalse(report["activated"])

    def test_promoted_version_is_marked_active_when_imported(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "activation_demo", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "activation_demo"
SKILL_DESCRIPTION = "Old version."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "activation_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "old"
'''
        candidate = '''SKILL_NAME = "activation_demo"
SKILL_DESCRIPTION = "Preserves the existing tool and adds a new tool."
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "activation_demo_run", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "activation_demo_new", "parameters": {"type": "object"}}},
]
def handle(tool_name, args, services=None):
    if tool_name == "activation_demo_run":
        return "old"
    if tool_name == "activation_demo_new":
        return "new"
    return None
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        cases = [
            {
                "name": "existing behaviour",
                "kind": "regression",
                "tool_name": "activation_demo_run",
                "args": {},
                "expected_equals": "old",
            },
            {
                "name": "new feature",
                "kind": "feature",
                "tool_name": "activation_demo_new",
                "args": {},
                "expected_equals": "new",
            },
        ]
        staged = skill_evolution.stage_skill_candidate("activation_demo", candidate, tests=cases)
        candidate_id = staged.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_PASS_REVIEW_REQUIRED", report)
        promoted = json.loads(skill_evolution.promote_skill_candidate(candidate_id, approval_token=candidate_id))
        active = skill_evolution.mark_skill_version_active("activation_demo", live_path)
        self.assertTrue(active["activated"], active)
        self.assertEqual(active["version_id"], promoted["version_id"])
        with open(os.path.join(skill_evolution.CANDIDATE_ROOT, candidate_id, "candidate.json"), encoding="utf-8") as handle:
            metadata = json.load(handle)
        self.assertTrue(metadata["activated"])
        self.assertEqual(metadata["state"], "ACTIVE")
        rolled_back = json.loads(skill_evolution.rollback_skill_version(
            promoted["version_id"], approval_token=promoted["version_id"]
        ))
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), baseline)

    def test_loader_auto_rolls_back_a_failed_matching_promotion(self):
        from skills import loader
        old_user = loader.USER_SKILLS_DIR
        old_bundled = loader.BUNDLED_SKILLS_DIR
        name = "startup_recovery_demo"
        previous_source = '''SKILL_NAME = "startup_recovery_demo"
SKILL_DESCRIPTION = "Previous working version."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "startup_recovery_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "previous-ok"
'''
        broken_source = '''raise RuntimeError("simulated failed promoted import")
SKILL_NAME = "startup_recovery_demo"
SKILL_DESCRIPTION = "Broken promoted version."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "startup_recovery_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "broken"
'''
        candidate_id = name + "-" + "a" * 10
        version_id = name + "-20261020T210000-" + "b" * 8
        try:
            user_root = os.path.join(self.temp.name, "user_skills")
            bundled_root = os.path.join(self.temp.name, "bundled_skills")
            version_root = os.path.join(self.temp.name, "skill_candidates", "versions")
            skill_evolution.LIVE_SKILLS_DIR = user_root
            skill_evolution.CANDIDATE_ROOT = os.path.join(self.temp.name, "skill_candidates")
            loader.USER_SKILLS_DIR = user_root
            loader.BUNDLED_SKILLS_DIR = bundled_root
            live_path = os.path.join(user_root, name, "skill.py")
            os.makedirs(os.path.dirname(live_path), exist_ok=True)
            os.makedirs(os.path.join(bundled_root, name), exist_ok=True)
            with open(live_path, "wb") as handle:
                handle.write(broken_source.encode("utf-8"))
            with open(os.path.join(bundled_root, name, "skill.py"), "wb") as handle:
                handle.write(previous_source.encode("utf-8"))
            version_dir = os.path.join(version_root, version_id)
            os.makedirs(version_dir, exist_ok=True)
            backup = os.path.join(version_dir, "previous_skill.py")
            with open(backup, "wb") as handle:
                handle.write(previous_source.encode("utf-8"))
            digest = __import__("hashlib").sha256
            manifest = {
                "version_id": version_id,
                "name": name,
                "candidate_id": candidate_id,
                "state": "PROMOTED_PENDING_RESTART",
                "promoted_sha256": digest(broken_source.encode("utf-8")).hexdigest(),
                "previous_exists": True,
                "previous_sha256": digest(previous_source.encode("utf-8")).hexdigest(),
                "rollback_available": True,
            }
            with open(os.path.join(version_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)

            found = loader.discover()
            self.assertIn(name, found)
            self.assertIn("module", found[name], found[name])
            self.assertEqual(found[name]["module"].handle(name + "_run", {}, None), "previous-ok")
            self.assertTrue(found[name]["recovery"]["recovered"])
            with open(live_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), previous_source)
            with open(os.path.join(version_dir, "manifest.json"), encoding="utf-8") as handle:
                after = json.load(handle)
            self.assertEqual(after["state"], "AUTO_ROLLED_BACK_IMPORT_FAILURE")
        finally:
            loader.USER_SKILLS_DIR = old_user
            loader.BUNDLED_SKILLS_DIR = old_bundled
            skill_evolution.CANDIDATE_ROOT = self.temp.name
            skill_evolution.LIVE_SKILLS_DIR = os.path.join(self.temp.name, "live")

    def test_auto_recovery_refuses_to_overwrite_a_manually_changed_file(self):
        name = "manual_drift_demo"
        previous_source = "previous version"
        promoted_source = "promoted version"
        edited_source = "Sir's manual edit"
        skill_evolution.LIVE_SKILLS_DIR = os.path.join(self.temp.name, "live")
        skill_evolution.CANDIDATE_ROOT = os.path.join(self.temp.name, "skill_candidates")
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, name, "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(edited_source)
        version_id = name + "-20261020T210001-" + "c" * 8
        version_dir = os.path.join(skill_evolution.CANDIDATE_ROOT, "versions", version_id)
        os.makedirs(version_dir, exist_ok=True)
        import hashlib
        manifest = {
            "version_id": version_id,
            "name": name,
            "candidate_id": name + "-" + "d" * 10,
            "state": "PROMOTED_PENDING_RESTART",
            "promoted_sha256": hashlib.sha256(promoted_source.encode("utf-8")).hexdigest(),
            "previous_exists": True,
            "previous_sha256": hashlib.sha256(previous_source.encode("utf-8")).hexdigest(),
        }
        with open(os.path.join(version_dir, "previous_skill.py"), "w", encoding="utf-8") as handle:
            handle.write(previous_source)
        with open(os.path.join(version_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        result = skill_evolution.recover_failed_promotion_on_import_error(name, live_path, "ImportError")
        self.assertFalse(result["recovered"])
        self.assertIn("hash", result["reason"].lower())
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), edited_source)

    def test_versioned_promotion_requires_confirmation_and_rollback_restores_baseline(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "promote_demo", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "promote_demo"
SKILL_DESCRIPTION = "Existing working version."
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "promote_demo_echo", "parameters": {"type": "object"}}},
]
def handle(tool_name, args, services=None):
    if tool_name == "promote_demo_echo":
        return "legacy-value"
    return None
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        candidate = '''SKILL_NAME = "promote_demo"
SKILL_DESCRIPTION = "Preserves echo and adds uppercase."
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "promote_demo_echo", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "promote_demo_upper", "parameters": {"type": "object"}}},
]
def handle(tool_name, args, services=None):
    if tool_name == "promote_demo_echo":
        return "legacy-value"
    if tool_name == "promote_demo_upper":
        return str((args or {}).get("text", "")).upper()
    return None
'''
        tests = [
            {"name": "legacy echo", "kind": "regression", "tool_name": "promote_demo_echo", "args": {}, "expected_equals": "legacy-value"},
            {"name": "new uppercase", "kind": "feature", "tool_name": "promote_demo_upper", "args": {"text": "hello"}, "expected_equals": "HELLO"},
        ]
        staged = skill_evolution.stage_skill_candidate("promote_demo", candidate, tests=tests)
        candidate_id = staged.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        tested = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(tested["status"], "TEST_PASS_REVIEW_REQUIRED", tested)

        confirmation = skill_evolution.promote_skill_candidate(candidate_id)
        self.assertIn("CONFIRM_REQUIRED", confirmation)
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), baseline)

        promoted = json.loads(skill_evolution.promote_skill_candidate(
            candidate_id, approval_token=candidate_id
        ))
        self.assertEqual(promoted["status"], "PROMOTED_PENDING_RESTART")
        self.assertTrue(promoted["backup_saved"])
        self.assertTrue(promoted["restart_required"])
        self.assertFalse(promoted["activated"])
        version_id = promoted["version_id"]
        self.assertIn(version_id, skill_evolution.list_skill_versions())
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), candidate)

        confirmation = skill_evolution.rollback_skill_version(version_id)
        self.assertIn("CONFIRM_REQUIRED", confirmation)
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), candidate)

        rolled_back = json.loads(skill_evolution.rollback_skill_version(
            version_id, approval_token=version_id
        ))
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        self.assertTrue(rolled_back["previous_file_restored"])
        self.assertTrue(rolled_back["restart_required"])
        with open(live_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), baseline)
        self.assertIn("ROLLED_BACK", skill_evolution.list_skill_versions())

    def test_new_skill_promotion_can_be_rolled_back_by_removing_override(self):
        candidate = '''SKILL_NAME = "brand_new_demo"
SKILL_DESCRIPTION = "A new demo skill."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "brand_new_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    if tool_name == "brand_new_demo_run":
        return "new-skill-ok"
    return None
'''
        cases = [{
            "name": "new tool output",
            "kind": "feature",
            "tool_name": "brand_new_demo_run",
            "args": {},
            "expected_equals": "new-skill-ok",
        }]
        message = skill_evolution.stage_skill_candidate("brand_new_demo", candidate, tests=cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(result["status"], "TEST_PASS_NO_REGRESSION_COVERAGE", result)
        promoted = json.loads(skill_evolution.promote_skill_candidate(candidate_id, approval_token=candidate_id))
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "brand_new_demo", "skill.py")
        self.assertTrue(os.path.isfile(live_path))
        rolled_back = json.loads(skill_evolution.rollback_skill_version(
            promoted["version_id"], approval_token=promoted["version_id"]
        ))
        self.assertFalse(rolled_back["previous_file_restored"])
        self.assertFalse(os.path.exists(live_path))

    def test_promotion_refuses_when_baseline_changes_after_testing(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "stale_demo", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "stale_demo"
SKILL_DESCRIPTION = "Baseline."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "stale_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "old"
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        candidate = '''SKILL_NAME = "stale_demo"
SKILL_DESCRIPTION = "Candidate."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "stale_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "old"
'''
        cases = [{"name": "keep old tool", "kind": "regression", "tool_name": "stale_demo_run", "args": {}, "expected_equals": "old"}]
        message = skill_evolution.stage_skill_candidate("stale_demo", candidate, tests=cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(result["status"], "TEST_PASS_REVIEW_REQUIRED", result)
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline + "\n# changed after tests\n")
        refused = skill_evolution.promote_skill_candidate(candidate_id, approval_token=candidate_id)
        self.assertIn("effective baseline changed after testing", refused)
        with open(live_path, encoding="utf-8") as handle:
            self.assertIn("changed after tests", handle.read())

    def test_rollback_refuses_if_live_file_drifted_after_promotion(self):
        live_path = os.path.join(skill_evolution.LIVE_SKILLS_DIR, "drift_demo", "skill.py")
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        baseline = '''SKILL_NAME = "drift_demo"
SKILL_DESCRIPTION = "Baseline."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "drift_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "stable"
'''
        with open(live_path, "w", encoding="utf-8") as handle:
            handle.write(baseline)
        candidate = baseline.replace("return \"stable\"", "return \"candidate\"")
        cases = [{"name": "stable contract", "kind": "regression", "tool_name": "drift_demo_run", "args": {}, "expected_equals": "candidate"}]
        # The replacement is intentionally expected to fail regression; use a passing baseline-preserving candidate.
        candidate = baseline.replace('SKILL_DESCRIPTION = "Baseline."', 'SKILL_DESCRIPTION = "Candidate version."')
        cases[0]["expected_equals"] = "stable"
        message = skill_evolution.stage_skill_candidate("drift_demo", candidate, tests=cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        tested = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(tested["status"], "TEST_PASS_REVIEW_REQUIRED", tested)
        promoted = json.loads(skill_evolution.promote_skill_candidate(candidate_id, approval_token=candidate_id))
        with open(live_path, "a", encoding="utf-8") as handle:
            handle.write("\n# manually changed after promotion\n")
        refused = skill_evolution.rollback_skill_version(
            promoted["version_id"], approval_token=promoted["version_id"]
        )
        self.assertIn("live file differs from this promotion", refused)
        with open(live_path, encoding="utf-8") as handle:
            self.assertIn("manually changed after promotion", handle.read())

    def test_packaged_loader_prefers_user_overrides_and_keeps_bundled_fallback(self):
        from skills import loader
        old_user = loader.USER_SKILLS_DIR
        old_bundled = loader.BUNDLED_SKILLS_DIR
        try:
            user_root = os.path.join(self.temp.name, "user_skills")
            bundled_root = os.path.join(self.temp.name, "bundled_skills")
            os.makedirs(os.path.join(user_root, "shared_skill"), exist_ok=True)
            os.makedirs(os.path.join(user_root, "user_only_skill"), exist_ok=True)
            os.makedirs(os.path.join(bundled_root, "shared_skill"), exist_ok=True)
            os.makedirs(os.path.join(bundled_root, "bundled_only_skill"), exist_ok=True)
            for path in (
                os.path.join(user_root, "shared_skill", "skill.py"),
                os.path.join(user_root, "user_only_skill", "skill.py"),
                os.path.join(bundled_root, "shared_skill", "skill.py"),
                os.path.join(bundled_root, "bundled_only_skill", "skill.py"),
            ):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("SKILL_NAME = 'fixture'\\n")
            loader.USER_SKILLS_DIR = user_root
            loader.BUNDLED_SKILLS_DIR = bundled_root
            entries = dict(loader._iter_skill_dirs())
            self.assertEqual(entries["shared_skill"], os.path.join(user_root, "shared_skill", "skill.py"))
            self.assertEqual(entries["user_only_skill"], os.path.join(user_root, "user_only_skill", "skill.py"))
            self.assertEqual(entries["bundled_only_skill"], os.path.join(bundled_root, "bundled_only_skill", "skill.py"))
            self.assertEqual(len([name for name in entries if name == "shared_skill"]), 1)
        finally:
            loader.USER_SKILLS_DIR = old_user
            loader.BUNDLED_SKILLS_DIR = old_bundled

    def test_top_level_execution_is_rejected_without_running_candidate(self):
        source = '''SKILL_NAME = "bad_skill"
SKILL_DESCRIPTION = "Must never run."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "bad_tool", "parameters": {"type": "object"}}}]
raise RuntimeError("candidate executed")
def handle(tool_name, args, services=None):
    return None
'''
        message = skill_evolution.stage_skill_candidate("bad_skill", source)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        result = skill_evolution.evaluate_skill_candidate(candidate_id)
        self.assertIn("STATIC_FAIL", result)
        self.assertIn("Top-level Raise statements", result)


if __name__ == "__main__":
    unittest.main()

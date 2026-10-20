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
SKILL_DESCRIPTION = "Network import should be blocked."
TOOL_DEFINITIONS = [{"type": "function", "function": {"name": "blocked_demo_run", "parameters": {"type": "object"}}}]
def handle(tool_name, args, services=None):
    return "unexpected"
'''
        test_cases = [{
            "name": "blocked network access",
            "kind": "feature",
            "tool_name": "blocked_demo_run",
            "args": {},
            "expected_contains": "unexpected",
        }]
        message = skill_evolution.stage_skill_candidate("blocked_demo", candidate, tests=test_cases)
        candidate_id = message.split("Staged skill candidate '", 1)[1].split("'", 1)[0]
        report = json.loads(skill_evolution.test_skill_candidate(candidate_id, timeout_seconds=10))
        self.assertEqual(report["status"], "TEST_BLOCKED", report)
        self.assertFalse(report["activated"])

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

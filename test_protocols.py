import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import protocols


class ProtocolsTests(unittest.TestCase):
    def test_repository_policy_loads(self):
        text = protocols.load_protocols()
        self.assertIn("FAIL-CLOSED RULE", text)
        self.assertIn("Google AI Studio", text)

    def test_missing_policy_fails_closed(self):
        original = protocols.BASE_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                protocols.BASE_DIR = Path(directory)
                with self.assertRaises(protocols.ProtocolsError):
                    protocols.load_protocols()
        finally:
            protocols.BASE_DIR = original

    def test_frozen_onefile_uses_bundled_policy_when_no_external_copy_exists(self):
        original_base = protocols.BASE_DIR
        source_policy = original_base / protocols.PROTOCOLS_FILENAME
        try:
            with tempfile.TemporaryDirectory() as executable_dir, tempfile.TemporaryDirectory() as bundle_dir:
                (Path(bundle_dir) / protocols.PROTOCOLS_FILENAME).write_text(
                    source_policy.read_text(encoding="utf-8"), encoding="utf-8"
                )
                protocols.BASE_DIR = Path(executable_dir)
                with patch.object(protocols.sys, "frozen", True, create=True):
                    with patch.dict(os.environ, {"_MEIPASS": bundle_dir}):
                        self.assertIn("FAIL-CLOSED RULE", protocols.load_protocols())
        finally:
            protocols.BASE_DIR = original_base

    def test_empty_policy_fails_closed(self):
        original = protocols.BASE_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                protocols.BASE_DIR = Path(directory)
                (Path(directory) / protocols.PROTOCOLS_FILENAME).write_text(
                    "   ", encoding="utf-8"
                )
                with self.assertRaises(protocols.ProtocolsError):
                    protocols.load_protocols()
        finally:
            protocols.BASE_DIR = original

    def test_apply_adds_editable_policy(self):
        result = protocols.apply_protocols("BASE SYSTEM PROMPT")
        self.assertIn("BASE SYSTEM PROMPT", result)
        self.assertIn("EDITABLE JARVIS PROTOCOLS", result)
        self.assertIn('Address the user as "Sir" only.', result)
        self.assertIn("Reply to Sir in clear English by default", result)

    def test_all_prompt_like_sections_are_editable(self):
        hedge_patterns = protocols.load_prompt("HEDGE_PATTERNS")
        transcription_prompt = protocols.load_prompt("STT_TRANSCRIPTION_PROMPT")
        self.assertIn("i don't know", hedge_patterns)
        self.assertIn("Hey Jarvis", transcription_prompt)
        self.assertIn("If a request must be declined for safety or legality", protocols.load_prompt("SYSTEM_PROMPT"))

    def test_hedge_detection_uses_txt_rules(self):
        import persona
        self.assertTrue(persona.is_hedged("I do not know the answer yet."))
        self.assertFalse(persona.is_hedged("I checked the source and verified the result."))

    def test_safety_refusal_is_not_treated_as_a_hedge(self):
        import persona
        self.assertFalse(
            persona.is_hedged(
                "I cannot assist with that unsafe request, but I can offer a safe alternative."
            )
        )

    def test_screen_watcher_prompt_is_editable(self):
        prompt = protocols.load_prompt("SCREEN_WATCHER_PROMPT")
        self.assertIn("stuck_score", prompt)
        self.assertIn("{style}", prompt)


if __name__ == "__main__":
    unittest.main()

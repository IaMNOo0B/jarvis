import tempfile
import unittest
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

    def test_screen_watcher_prompt_is_editable(self):
        prompt = protocols.load_prompt("SCREEN_WATCHER_PROMPT")
        self.assertIn("stuck_score", prompt)
        self.assertIn("{style}", prompt)


if __name__ == "__main__":
    unittest.main()

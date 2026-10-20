"""Lightweight regression checks for the PyInstaller spec.

These tests intentionally do not install runtime dependencies or download models.
They catch spec syntax/API mistakes before the heavyweight Windows packaging step.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC_PATH = ROOT / "AI_Model" / "Jarvis.spec"
BUILD_SCRIPT_PATH = ROOT / "AI_Model" / "build_wizard" / "build_jarvis_exe.bat"


class PackagingSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")
        cls.spec_tree = ast.parse(cls.spec_text, filename=str(SPEC_PATH))

    def test_spec_is_valid_python(self):
        self.assertIsInstance(self.spec_tree, ast.Module)

    def test_analysis_uses_supported_keyword_arguments(self):
        analysis_calls = [
            node for node in ast.walk(self.spec_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        ]
        self.assertEqual(len(analysis_calls), 1, "Expected exactly one Analysis() call.")
        keyword_names = {keyword.arg for keyword in analysis_calls[0].keywords}
        self.assertNotIn("patcher", keyword_names)
        self.assertIn("pathex", keyword_names)
        self.assertIn("datas", keyword_names)
        self.assertIn("hiddenimports", keyword_names)

    def test_editable_protocol_and_skill_runner_are_bundled(self):
        self.assertIn('"JARVIS_PROTOCOLS.txt"', self.spec_text)
        self.assertIn('"skill_test_runner.py"', self.spec_text)
        self.assertIn('_skills_root = os.path.join(_repo_root, "skills")', self.spec_text)
        self.assertIn('_filename.endswith(".py") or _filename.endswith(".md")', self.spec_text)

    def test_build_script_stops_when_runtime_dependency_install_fails(self):
        script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
        install_line = '!PIP! install -r requirements.txt'
        self.assertIn(install_line, script)
        install_pos = script.index(install_line)
        build_pos = script.index('!PYI! --clean --noconfirm --onedir')
        error_check = script.find('if %errorlevel% neq 0', install_pos, build_pos)
        self.assertNotEqual(
            error_check, -1,
            "Dependency installation must be checked before invoking PyInstaller.",
        )


if __name__ == "__main__":
    unittest.main()

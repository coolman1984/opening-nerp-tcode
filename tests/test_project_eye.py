"""Offline semantic guard for the final one-engine Project Eye record."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectEyeTruth(unittest.TestCase):
    def test_manifest_and_governance_agree(self):
        manifest = json.loads((ROOT / ".project-eye" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entrypoint"], "PROJECT_EYE.md")
        self.assertEqual(manifest["graph"], ".project-eye/graph.yaml")
        self.assertEqual(manifest["rules"], ".project-eye/rules.yaml")
        self.assertIn("test_project_eye.py", manifest["enforcement"])
        graph = (ROOT / ".project-eye" / "graph.yaml").read_text(encoding="utf-8")
        rules = (ROOT / ".project-eye" / "rules.yaml").read_text(encoding="utf-8")
        self.assertIn("name: nerp\n      status: active", graph)
        self.assertIn("name: gmes\n      status: active", graph)
        self.assertIn("primary: GMES_Workflow.bat", graph)
        for credential_path in ("%LOCALAPPDATA%/GMES_Automation/credentials.dat",
                                "%LOCALAPPDATA%/GMES/credentials.dat"):
            with self.subTest(credential_path=credential_path):
                self.assertIn(credential_path, graph)
                self.assertIn(credential_path, rules)
        self.assertIn("logs/", graph)
        self.assertIn("no-standalone-package-in-tree", rules)
        self.assertIn("gmes-screenshots-use-explicit-targets", rules)
        self.assertFalse((ROOT / "src" / "gmes").exists())
        self.assertFalse((ROOT / "pyproject.toml").exists())

        # These duplicate launchers are historical evidence only. No current
        # document may present a deleted executable entrance as available.
        deleted_entrances = ("GMES_Workflow_LEGACY_TEST.bat",
                             "run_gmes_workflow_LEGACY_TEST.py")
        for document in ROOT.glob("*.md"):
            if document.name == "HISTORY.md":
                continue
            text = document.read_text(encoding="utf-8")
            for entrance in deleted_entrances:
                with self.subTest(document=document.name, entrance=entrance):
                    self.assertNotIn(entrance, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

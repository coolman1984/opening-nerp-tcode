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
        self.assertIn("GMES_Automation", graph)
        self.assertIn("logs/", graph)
        self.assertIn("no-standalone-package-in-tree", rules)
        self.assertFalse((ROOT / "src" / "gmes").exists())
        self.assertFalse((ROOT / "pyproject.toml").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

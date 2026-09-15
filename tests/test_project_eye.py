"""Offline semantic guard: .project-eye/ and the .md files must agree with
the code that is actually in this tree.

Two systems have been removed from this repository, each after reaching real
live sessions, and each time the documents went on describing them for a
while afterwards. That is the failure this file exists to make impossible:
HISTORY.md Phase 57.1 found every governance document naming the engine that
was about to be deleted, so an agent could read one file and conclude the
opposite of another and be following the repository either way.
"""
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


class NerpIsGone(unittest.TestCase):
    """N-ERP was removed in HISTORY.md Phase 72 and is recoverable from
    `archive/nerp-before-removal`. It is not coming back into this tree by
    accident - and, more to the point, it must not come back WITHOUT the two
    defects it left unfixed being addressed first (Open Items #3 and #14,
    closed by removal rather than by fix)."""

    NERP_FILES = ("search_tcode.py", "execute_filters.py", "export_to_excel.py",
                  "run_nerp_workflow.py", "NERP_Workflow.bat",
                  "tests/mock_nerp_server.py", "tests/test_live_chrome.py")

    def test_no_nerp_entrance_is_back_in_the_tree(self):
        for name in self.NERP_FILES:
            with self.subTest(name=name):
                self.assertFalse(
                    (ROOT / name).exists(),
                    f"{name} is back. N-ERP was removed in Phase 72; if it is "
                    "being revived, Open Items #3 and #14 are still open in it.")

    def test_the_graph_does_not_present_nerp_as_active(self):
        graph = (ROOT / ".project-eye" / "graph.yaml").read_text(encoding="utf-8")
        self.assertNotIn("name: nerp\n      status: active", graph)
        self.assertIn("name: removed-nerp", graph)


class SharedCdpGuardsSurvive(unittest.TestCase):
    """The near-miss of Phase 72.2, turned into a test.

    `tests/test_unit.py` was named for N-ERP and documented as the N-ERP
    suite, and was simultaneously the only automated proof of two fixes that
    protect G-MES on every run. Deleting it on the strength of its name would
    have left every other suite green with nothing to show that anything had
    been lost. The guards now live in a file named after the module they
    protect - and this makes deleting THAT file fail loudly."""

    def test_the_shared_cdp_guard_file_exists(self):
        self.assertTrue(
            (ROOT / "tests" / "test_cdp_common.py").is_file(),
            "tests/test_cdp_common.py is gone. It holds the only automated "
            "proof of --disable-popup-blocking and capture_screenshot(tab=); "
            "see HISTORY.md Phase 72.2 for why that matters.")

    def test_it_still_guards_the_two_live_proven_fixes(self):
        text = (ROOT / "tests" / "test_cdp_common.py").read_text(encoding="utf-8")
        for needle in ("--disable-popup-blocking",
                       "TestUserProfileChromeLaunchArguments",
                       "TestScreenshotTabOverrideIsBackwardCompatible"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_rule_naming_it_is_still_in_force(self):
        rules = (ROOT / ".project-eye" / "rules.yaml").read_text(encoding="utf-8")
        self.assertIn("shared-cdp-guards-must-not-be-deleted-with-a-system", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)

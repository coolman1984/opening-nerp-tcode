"""Doctor is observational: useful facts without runtime mutation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gmes.contracts import DoctorReport, DoctorStatus


class DoctorTests(unittest.TestCase):
    def setUp(self):
        from gmes.diagnostics import doctor
        self.doctor = doctor
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "GMES"

    def test_missing_runtime_tree_is_reported_without_being_created(self):
        report = self.doctor.inspect(root=self.root, env={"NO_PROXY": "localhost,127.0.0.1"},
                                     chrome_locator=lambda: "C:/Chrome/chrome.exe",
                                     cdp_probe=lambda: False, profile_dir=self.root / "profile-copy")
        self.assertFalse(self.root.exists())
        self.assertTrue(any(check.name == "runtime root" and check.status is DoctorStatus.WARN
                            for check in report.checks))

    def test_existing_runtime_state_is_inspected_without_writes(self):
        profiles = self.root / "profiles"
        profiles.mkdir(parents=True)
        (profiles / "P1112UM00.json").write_text('{"screen":"P1112UM00"}', encoding="utf-8")
        (self.root / "credentials.dat").write_bytes(b"opaque")
        report = self.doctor.inspect(root=self.root, env={"NO_PROXY": "localhost,127.0.0.1"},
                                     chrome_locator=lambda: "C:/Chrome/chrome.exe",
                                     cdp_probe=lambda: True, tab_probe=lambda: [{"type": "page"}],
                                     profile_dir=self.root / "profile-copy")
        self.assertTrue(report.ok)
        self.assertIn("PASS", report.render())
        self.assertTrue((profiles / "P1112UM00.json").exists())

    def test_report_exit_code_fails_only_for_actual_failures(self):
        report = DoctorReport((self.doctor.DoctorCheck(DoctorStatus.PASS, "check", "ok"),))
        self.assertEqual(report.exit_code, 0)
        failed = DoctorReport((self.doctor.DoctorCheck(DoctorStatus.FAIL, "check", "bad"),))
        self.assertEqual(failed.exit_code, 1)

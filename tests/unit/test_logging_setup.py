"""Operation logging stays under the owned runtime tree and redacts secrets."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_operation_log_writes_under_localappdata_and_redacts_secret_values(self):
        from gmes.logging_setup import operation_log
        with operation_log("run"):
            print("password=not-for-log tokenId=also-not-for-log normal evidence")
        logs = list((Path(self.tmp.name) / "GMES" / "logs").glob("*.log"))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text(encoding="utf-8")
        self.assertIn("normal evidence", text)
        self.assertNotIn("not-for-log", text)

    def test_operation_log_flushes_live_evidence_before_the_operation_returns(self):
        from gmes.logging_setup import operation_log
        with operation_log("live") as path:
            print("observed transition")
            self.assertIn("observed transition", Path(path).read_text(encoding="utf-8"))

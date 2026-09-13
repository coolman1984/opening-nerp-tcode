"""Offline regression tests for the safety gates ported to the legacy path."""
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmes_core as core  # noqa: E402
import gmes_log  # noqa: E402


def _screen(info):
    return core.Screen(None, "P1112UM00", {"title": "Test"}, info)


class ResultVerification(unittest.TestCase):
    def test_checks_every_result_row_not_a_small_sample(self):
        result = {
            "found": True,
            "columns": ["planYmd"],
            "rows": [{"planYmd": "20260909"}] * 8 + [{"planYmd": "20260908"}],
        }
        with patch.object(core, "read_rows", return_value=result) as read:
            seen, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "20260909")
        read.assert_called_once_with(None, "P1112WM00", "dsResult", limit=-1)
        self.assertEqual(seen, ["20260908", "20260909"])
        self.assertIn("not exactly", problem)

    def test_requires_an_expected_value(self):
        result = {"found": True, "columns": ["planYmd"], "rows": [{"planYmd": "20260909"}]}
        with patch.object(core, "read_rows", return_value=result):
            _, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "")
        self.assertIn("expected value", problem)


class AmbiguityAndDates(unittest.TestCase):
    def test_comparable_grids_require_an_explicit_choice(self):
        screen = _screen({"grids": [
            {"name": "grdMaster", "dataset": "dsMaster", "area": 400000, "visible": True},
            {"name": "grdDetail", "dataset": "dsDetail", "area": 300000, "visible": True},
        ]})
        with self.assertRaisesRegex(RuntimeError, "more than one plausible"):
            screen.grid()

    def test_one_date_field_is_written_once_for_one_day_request(self):
        field = {"column": "planYmd", "control": "mskPlanDate", "value": "",
                 "bound": True, "dataset": "dsFilter", "form": "P1112WF00.xfdl.js"}
        screen = _screen({"filters": [field]})
        screen.apply = Mock(return_value="20260909")
        written = screen.set_date_range("20260909", "20260909")
        self.assertEqual(written, [(field, "20260909")])
        screen.apply.assert_called_once_with(field, "20260909")

    def test_one_date_field_rejects_a_range(self):
        field = {"column": "planYmd", "control": "mskPlanDate", "value": "",
                 "bound": True, "dataset": "dsFilter", "form": "P1112WF00.xfdl.js"}
        with self.assertRaisesRegex(RuntimeError, "no from/to pair"):
            _screen({"filters": [field]}).set_date_range("20260908", "20260909")


class ExportAndBatchSafety(unittest.TestCase):
    def test_rejects_a_large_file_that_is_not_an_excel_or_drm_workbook(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.xlsx")
            with open(path, "wb") as fh:
                fh.write(b"not a workbook" * 100)
            with self.assertRaisesRegex(RuntimeError, "not an XLSX"):
                core.check_download(path)

    def test_accepts_a_zip_workbook_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.xlsx")
            with open(path, "wb") as fh:
                fh.write(b"PK\x03\x04" + b"x" * 600)
            self.assertGreater(core.check_download(path), 512)

    def test_batch_stops_after_a_failure_and_marks_later_work_not_run(self):
        specs = [{"screen_code": "A1000"}, {"screen_code": "B1000"}, {"screen_code": "C1000"}]
        with patch.object(core, "run_screen", side_effect=[{"screen": "A1000", "ok": True}, RuntimeError("bad")]), \
             patch.object(core.cdp_common, "screenshot_on_failure"):
            results = core.run_many(None, specs, log=lambda _message: None)
        self.assertEqual([item["screen"] for item in results], ["A1000", "B1000", "C1000"])
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[2]["error"], "not run because the previous screen left an unknown state")


class LoggingSafety(unittest.TestCase):
    def test_secret_shaped_assignments_are_redacted_before_logging(self):
        line = 'password=do-not-store token: "also-do-not-store" ordinary=value'
        redacted = gmes_log._SECRET.sub(
            lambda match: f"{match.group(1)}{match.group(2)}***", line)
        self.assertNotIn("do-not-store", redacted)
        self.assertNotIn("also-do-not-store", redacted)
        self.assertIn("ordinary=value", redacted)


if __name__ == "__main__":
    unittest.main(verbosity=2)

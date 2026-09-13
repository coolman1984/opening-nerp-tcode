"""Offline contract tests for the standalone G-MES export split.

These tests deliberately stub the browser boundary.  They prove naming,
download-file validation, CSV page streaming, and Screen delegation without
opening Chrome or reading any G-MES data.
"""
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import DatasetPage, ExportResult, GridRef, ScreenInfo  # noqa: E402
from gmes.discovery.screen import Screen  # noqa: E402
from gmes.export import csv_export, excel, naming  # noqa: E402


class NamingTests(unittest.TestCase):
    def test_safe_name_replaces_windows_forbidden_characters(self):
        self.assertEqual(naming.safe_name("Plan / Actual: Shift A"),
                         "Plan - Actual- Shift A")
        self.assertEqual(naming.safe_name("   "), "report")

class ExcelValidationTests(unittest.TestCase):
    def test_drm_detection_recognises_nasca_prefix_and_missing_files_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            drm_path = os.path.join(directory, "drm.xlsx")
            with open(drm_path, "wb") as handle:
                handle.write(b"<## NASCA DRM FILE - VER1.00 ##>")
            self.assertTrue(excel.is_drm_protected(drm_path))
            self.assertFalse(excel.is_drm_protected(os.path.join(directory, "missing.xlsx")))

    def test_check_download_rejects_missing_and_small_files_but_returns_real_size(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing.xlsx")
            with self.assertRaisesRegex(RuntimeError, "is not there"):
                excel.check_download(missing)

            small = os.path.join(directory, "small.xlsx")
            with open(small, "wb") as handle:
                handle.write(b"x" * 511)
            with self.assertRaisesRegex(RuntimeError, "not a real export"):
                excel.check_download(small)

            complete = os.path.join(directory, "complete.xlsx")
            with open(complete, "wb") as handle:
                handle.write(b"PK\x03\x04" + b"x" * 508)
            self.assertEqual(excel.check_download(complete), 512)

            arbitrary = os.path.join(directory, "arbitrary.xlsx")
            with open(arbitrary, "wb") as handle:
                handle.write(b"x" * 512)
            with self.assertRaisesRegex(RuntimeError, "not an XLSX"):
                excel.check_download(arbitrary)


class ExportDialogTests(unittest.TestCase):
    """The confirm button is found by any of its known labels, not just 'OK'."""

    def test_the_dialog_is_confirmed_by_whichever_label_is_on_screen(self):
        for label in ("OK", "확인", "저장"):
            with self.subTest(label=label):
                clicks = []

                def answer(ws, text=None, **_kwargs):
                    clicks.append(text)
                    return {"text": text} if text == label else None

                with patch.object(excel, "click_control", side_effect=answer):
                    self.assertEqual(excel.confirm_export_dialog(object()), {"text": label})
                self.assertIn(label, clicks)

    def test_a_dialog_with_no_known_confirm_button_reports_what_was_looked_for(self):
        with patch.object(excel, "click_control", return_value=None):
            self.assertIsNone(excel.confirm_export_dialog(object(), timeout=0))


class UnattendedExportTests(unittest.TestCase):
    """Nobody is at the desk: one recoverable miss must not lose the report."""

    def setUp(self):
        self.uc = importlib.import_module("gmes.application.run_screen_uc")
        self.notices = self.enterContext(
            patch.object(self.uc.popups, "close_notices", return_value=([], [])))
        self.dialogs = self.enterContext(
            patch.object(self.uc.popups, "close_dialogs", return_value=([], [])))
        self.screen = Mock(ws=object())
        self.screen.activate.return_value = True

    def test_a_first_failed_attempt_is_retried_after_refocusing_and_clearing_popups(self):
        self.screen.export_excel.side_effect = [RuntimeError("no complete .xlsx"), "book.xlsx"]
        self.assertEqual(
            self.uc._download_workbook(self.screen, "out", lambda _: None), "book.xlsx")
        self.assertEqual(self.screen.activate.call_count, 2)
        self.assertEqual(self.notices.call_count, 2)
        # Only before the retry - the first attempt has raised no dialog yet.
        self.dialogs.assert_called_once()

    def test_a_dialog_left_by_a_failed_attempt_is_dismissed_before_clicking_excel_again(self):
        self.screen.export_excel.side_effect = [RuntimeError("no OK button"), "book.xlsx"]
        self.dialogs.return_value = (["Save to Excel"], [])
        self.assertEqual(
            self.uc._download_workbook(self.screen, "out", lambda _: None), "book.xlsx")
        self.dialogs.assert_called_once()

    def test_an_unrecognised_window_stops_the_retry_instead_of_clicking_past_it(self):
        self.screen.export_excel.side_effect = RuntimeError("no complete .xlsx")
        self.dialogs.return_value = ([], ["Approval Request (unknown)"])
        with self.assertRaisesRegex(RuntimeError, "unrecognised window"):
            self.uc._download_workbook(self.screen, "out", lambda _: None)
        self.assertEqual(self.screen.export_excel.call_count, 1)

    def test_every_attempt_failing_reports_the_last_reason_rather_than_a_bare_count(self):
        self.screen.export_excel.side_effect = RuntimeError("no complete .xlsx appeared")
        with self.assertRaisesRegex(RuntimeError, "no complete .xlsx appeared"):
            self.uc._download_workbook(self.screen, "out", lambda _: None, attempts=2)
        self.assertEqual(self.screen.export_excel.call_count, 2)

    def test_a_screen_that_cannot_be_brought_to_the_front_is_never_exported(self):
        self.screen.activate.return_value = False
        with self.assertRaisesRegex(RuntimeError, "active for Excel export"):
            self.uc._download_workbook(self.screen, "out", lambda _: None)
        self.screen.export_excel.assert_not_called()


class CsvStreamingTests(unittest.TestCase):
    def pages(self):
        return iter((
            DatasetPage(
                rows=(
                    {"poNo": "100", "qty": "2", "_rowtype": "N"},
                    {"poNo": "", "qty": "", "_rowtype": "N"},
                ),
                offset=0, returned=2, total=3),
            DatasetPage(
                rows=({"poNo": "200", "qty": "3", "_rowtype": "N"},),
                offset=2, returned=1, total=3),
        ))

    def test_write_csv_streams_pages_in_order_and_only_drops_completely_empty_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "result.csv")
            ws = object()
            with patch.object(csv_export, "read_dataset_paged", return_value=self.pages()) as read:
                result = csv_export.write_csv(ws, "P1112WM00", "dsMaster", path)

            self.assertEqual(result, ExportResult(path=path, format="csv", row_count=2,
                                                   checked=True))
            read.assert_called_once_with(ws, "P1112WM00", "dsMaster")
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(handle.read(), "poNo,qty\r\n100,2\r\n200,3\r\n")

    def test_write_csv_returns_an_unchecked_empty_result_when_no_pages_exist(self):
        with patch.object(csv_export, "read_dataset_paged", return_value=iter(())):
            result = csv_export.write_csv(object(), "P1112WM00", "dsEmpty", "unused.csv")
        self.assertEqual(result, ExportResult(path="", format="csv", row_count=0,
                                               checked=False))

    def test_write_csv_does_not_pull_the_next_page_before_writing_the_current_one(self):
        class Handle:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        writers = []

        class Writer:
            def __init__(self, *_args, **_kwargs):
                self.rows = []
                writers.append(self)

            def writeheader(self):
                pass

            def writerow(self, row):
                self.rows.append(row)

        first = DatasetPage(rows=({"poNo": "100"},), offset=0, returned=1, total=2)
        second = DatasetPage(rows=({"poNo": "200"},), offset=1, returned=1, total=2)

        def pages():
            yield first
            self.assertEqual(writers[0].rows, [{"poNo": "100"}])
            yield second

        with patch.object(csv_export, "read_dataset_paged", return_value=pages()), \
             patch.object(csv_export.csv, "DictWriter", Writer), \
             patch("builtins.open", return_value=Handle()):
            csv_export.write_csv(object(), "P1112WM00", "dsMaster", "unused.csv")


class ScreenExportDelegationTests(unittest.TestCase):
    def setUp(self):
        info = ScreenInfo(code="P1112UM00")
        self.screen = Screen(object(), "P1112UM00", {"title": "Plan"}, info)
        self.grid = GridRef(name="grdPlan", dataset="dsMasterProdPlan",
                            form="P1112WM00.xfdl.js")

    def test_export_excel_delegates_to_the_export_package(self):
        with patch("gmes.discovery.screen.excel.download_excel",
                   return_value="out.xlsx") as download:
            self.assertEqual(self.screen.export_excel("out", timeout=17), "out.xlsx")
        download.assert_called_once_with(self.screen.ws, "out", timeout=17)

    def test_to_csv_uses_the_discovered_grid_form_and_dataset(self):
        expected = ExportResult(path="out.csv", format="csv", row_count=1, checked=True)
        with patch("gmes.discovery.screen.csv_export.write_csv", return_value=expected) as write:
            self.assertEqual(self.screen.to_csv(self.grid, "out.csv"), expected)
        write.assert_called_once_with(self.screen.ws, "P1112WM00",
                                      "dsMasterProdPlan", "out.csv")


if __name__ == "__main__":
    unittest.main(verbosity=2)

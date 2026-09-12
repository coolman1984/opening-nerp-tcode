"""Offline contract tests for the standalone G-MES export split.

These tests deliberately stub the browser boundary.  They prove naming,
download-file validation, CSV page streaming, and Screen delegation without
opening Chrome or reading any G-MES data.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


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
                handle.write(b"x" * 512)
            self.assertEqual(excel.check_download(complete), 512)


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

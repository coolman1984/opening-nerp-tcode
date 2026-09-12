"""Offline contract tests for paged Nexacro dataset reads.

The real comparison against a large live G-MES dataset remains manual work.
These tests exercise the CDP-facing reader with a deterministic evaluate()
stub, so the paging boundaries and one-call bounded-read contract are
observable without opening Chrome.
"""
import os
import re
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.query import dataset_reader  # noqa: E402


class DatasetPagingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"row": str(index), "marker": f"row-{index:04d}"}
                     for index in range(850)]
        self.calls = []

    def evaluate(self, _ws, javascript):
        match = re.search(r"const start = (\d+), limit = (-?\d+);", javascript)
        self.assertIsNotNone(match, "the dataset JS must expose its offset and limit")
        offset, limit = map(int, match.groups())
        self.calls.append((offset, limit))
        rows = self.rows[offset:] if limit < 0 else self.rows[offset:offset + limit]
        return {
            "found": True,
            "path": "mainframe.work",
            "file": "P1112WM00.xfdl.js",
            "columns": ["row", "marker"],
            "total": len(self.rows),
            "rows": rows,
        }

    def test_paged_reader_yields_300_300_250_rows_with_correct_boundaries(self):
        with patch.object(dataset_reader, "evaluate", side_effect=self.evaluate):
            pages = list(dataset_reader.read_dataset_paged(
                object(), "P1112WM00", "dsMasterProdPlan"))

        self.assertEqual([page.returned for page in pages], [300, 300, 250])
        self.assertEqual([page.offset for page in pages], [0, 300, 600])
        self.assertEqual([page.rows[0]["marker"] for page in pages],
                         ["row-0000", "row-0300", "row-0600"])
        self.assertEqual([page.rows[-1]["marker"] for page in pages],
                         ["row-0299", "row-0599", "row-0849"])
        self.assertEqual(self.calls, [(0, 300), (300, 300), (600, 300)])

    def test_full_read_drains_pages_and_preserves_all_rows_in_order(self):
        with patch.object(dataset_reader, "evaluate", side_effect=self.evaluate):
            result = dataset_reader.read_dataset(
                object(), "P1112WM00", "dsMasterProdPlan", limit=-1)

        self.assertTrue(result["found"])
        self.assertEqual(result["total"], 850)
        self.assertEqual(result["rows"], self.rows)
        self.assertEqual(self.calls, [(0, 300), (300, 300), (600, 300)])

    def test_positive_bounded_read_keeps_the_single_cdp_call_contract(self):
        with patch.object(dataset_reader, "evaluate", side_effect=self.evaluate):
            result = dataset_reader.read_dataset(
                object(), "P1112WM00", "dsMasterProdPlan", limit=20)

        self.assertEqual(len(result["rows"]), 20)
        self.assertEqual(self.calls, [(0, 20)])

    def test_zero_row_dataset_yields_no_pages_and_terminates(self):
        self.rows = []
        with patch.object(dataset_reader, "evaluate", side_effect=self.evaluate):
            pages = list(dataset_reader.read_dataset_paged(
                object(), "P1112WM00", "dsMasterProdPlan"))

        self.assertEqual(pages, [])
        self.assertEqual(self.calls, [(0, 300)])

    def test_full_read_preserves_a_missing_dataset_dictionary(self):
        with patch.object(dataset_reader, "evaluate",
                          return_value={"found": False}) as evaluate:
            result = dataset_reader.read_dataset(
                object(), "P1112WM00", "missingDataset", limit=-1)

        self.assertEqual(result, {"found": False})
        evaluate.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Regression tests for explicit, reliable legacy dataset read limits."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gmes_data  # noqa: E402


def _fake_dataset_result():
    return {"found": True, "file": "P1112WM00.xfdl.js", "path": "app.mainframe...",
            "columns": ["paramFromDate"], "total": 0, "rows": []}


class ReadLimitArguments(unittest.TestCase):
    """Both documented positional and named limits must reach the reader."""

    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_documented_third_positional_limit_is_honoured(self, mock_read, mock_connect):
        mock_connect.return_value = MagicMock(close=MagicMock())
        mock_read.return_value = _fake_dataset_result()

        # Exactly the documented usage: read <SCREENCODE> <dataset> [limit].
        gmes_data.main(["read", "P1112WM00", "dsFilterDVO", "50"])

        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("limit"), 50)

    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_named_limit_is_honoured(self, mock_read, mock_connect):
        mock_connect.return_value = MagicMock(close=MagicMock())
        mock_read.return_value = _fake_dataset_result()

        gmes_data.main(["read", "P1112WM00", "dsFilterDVO", "--limit", "50"])

        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("limit"), 50)

    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_invalid_limit_is_a_usage_error_not_a_traceback(self, mock_read, mock_connect):
        mock_connect.return_value = MagicMock(close=MagicMock())
        self.assertEqual(gmes_data.main(["read", "P1112WM00", "dsFilterDVO", "many"]), 2)
        mock_read.assert_not_called()


class CsvOutputPathArgumentIsNotBugged(unittest.TestCase):
    """The `csv` command's own argv[3] (output path) is a different code
    path and is NOT affected by the read-limit bug above - confirms the
    diagnosis is scoped to `read`'s limit, not to argument parsing in
    general."""

    @patch("gmes_data.write_csv")
    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_csv_output_path_argument_is_honoured(self, mock_read, mock_connect, mock_write_csv):
        mock_connect.return_value = MagicMock(close=MagicMock())
        mock_read.return_value = _fake_dataset_result()
        mock_write_csv.return_value = "custom_out.csv"

        gmes_data.main(["csv", "P1112WM00", "dsFilterDVO", "custom_out.csv"])

        # csv always requests every row (limit=-1), regardless of the output
        # path argument - only `read`'s limit is broken.
        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("limit"), -1)
        mock_write_csv.assert_called_once()
        self.assertEqual(mock_write_csv.call_args[0][1], "custom_out.csv")


if __name__ == "__main__":
    unittest.main(verbosity=2)

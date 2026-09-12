"""Pins the confirmed gmes_data.py `read` limit-parsing bug (see ARCHITECTURE.md
§2, query/), before it gets fixed with a proper --limit flag in a later
migration phase.

gmes_data.py main() takes argv = sys.argv[1:], so for a `read` invocation
argv[0]="read", argv[1]=<SCREENCODE>, argv[2]=<dataset>. The module's own
docstring/usage documents a third positional, `read <SCREENCODE> <dataset>
[limit]`, which reads as argv[3]. The actual code instead does:

    limit = -1 if command == "csv" else int(argv[4]) if len(argv) > 4 else 20

i.e. it reads the limit from argv[4], one position further out than the
documented/intended argv[3]. A caller that follows the documented usage
exactly (`python gmes_data.py read P1112WM00 dsFilterDVO 50`) has argv =
["read", "P1112WM00", "dsFilterDVO", "50"], len(argv) == 4, so
`len(argv) > 4` is False and the requested limit of 50 is silently
discarded in favour of the default of 20.

This test asserts the CURRENT (buggy) behaviour on purpose. When
query/dataset_reader.py + cli/commands/data.py land with an explicit
--limit flag (removing the positional ambiguity entirely), this test
should be replaced by one asserting the corrected behaviour - see
ARCHITECTURE.md's query/ mapping entry.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gmes_data  # noqa: E402


def _fake_dataset_result():
    return {"found": True, "file": "P1112WM00.xfdl.js", "path": "app.mainframe...",
            "columns": ["paramFromDate"], "total": 0, "rows": []}


class ReadLimitArgvBug(unittest.TestCase):
    """Pins the KNOWN BUG: the documented `[limit]` positional (argv[3]) is
    silently ignored; only a phantom argv[4] is ever read."""

    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_documented_third_positional_limit_is_ignored(self, mock_read, mock_connect):
        mock_connect.return_value = MagicMock(close=MagicMock())
        mock_read.return_value = _fake_dataset_result()

        # Exactly the documented usage: read <SCREENCODE> <dataset> [limit].
        gmes_data.main(["read", "P1112WM00", "dsFilterDVO", "50"])

        # BUG: the requested limit of 50 (argv[3]) never reaches read_dataset.
        # The code falls back to its default of 20 because it looks for the
        # limit at argv[4], which does not exist in this (correctly-shaped)
        # call.
        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("limit"), 20,
                          "if this now fails with 50, the argv bug has been "
                          "fixed - replace this test with one asserting the "
                          "new --limit flag works correctly")

    @patch("gmes_data.connect_gmes")
    @patch("gmes_data.read_dataset")
    def test_a_fifth_argument_is_what_actually_reaches_limit_today(self, mock_read, mock_connect):
        mock_connect.return_value = MagicMock(close=MagicMock())
        mock_read.return_value = _fake_dataset_result()

        # One extra (undocumented) positional is what it actually takes to
        # move the limit today - confirms the off-by-one precisely.
        gmes_data.main(["read", "P1112WM00", "dsFilterDVO", "ignored", "50"])

        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("limit"), 50)


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

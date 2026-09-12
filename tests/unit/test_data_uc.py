"""The CLI gets dataset behavior through the application seam."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))


class DataUseCaseTests(unittest.TestCase):
    def test_read_delegates_to_the_dataset_reader_with_named_bounds(self):
        from gmes.application import data_uc
        response = {"found": True, "rows": [{"id": "1"}]}
        with patch.object(data_uc, "read_dataset", return_value=response) as read:
            self.assertIs(data_uc.read_open_dataset(object(), "P", "ds", limit=50, offset=2), response)
        read.assert_called_once_with(unittest.mock.ANY, "P", "ds", limit=50, offset=2)

    def test_forms_delegates_to_the_form_locator(self):
        from gmes.application import data_uc
        with patch.object(data_uc, "list_forms", return_value={"count": 0}) as forms:
            self.assertEqual(data_uc.list_open_forms(object()), {"count": 0})
        forms.assert_called_once()

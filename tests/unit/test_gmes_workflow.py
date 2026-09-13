"""Compatibility tests for the historical G-MES workflow entry point."""
import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import run_gmes_workflow as workflow  # noqa: E402


class LegacyWorkflowBridgeTests(unittest.TestCase):
    def test_historical_workflow_name_enters_the_standalone_guided_command(self):
        with patch.object(workflow, "gmes_main", return_value=0) as main:
            self.assertEqual(workflow.main(), 0)
        main.assert_called_once_with(["workflow"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

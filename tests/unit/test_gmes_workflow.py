"""Offline tests for the G-MES interactive summary renderer."""
import contextlib
import io
import os
import sys
import types
import unittest

# tests/unit/ is one level deeper than the original tests/, so this needs an
# extra dirname() to still reach the repo root and its flat gmes_*.py modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gmes_ui as ui  # noqa: E402
import run_gmes_workflow as workflow  # noqa: E402


class ScreenOffer(unittest.TestCase):
    @staticmethod
    def screen(unbound):
        info = {
            "datasets": {},
            "filters": [],
            "grids": [],
            "quickViews": [],
            "unbound": unbound,
        }
        return types.SimpleNamespace(
            info=info,
            title="PO Batch Monitoring",
            code="P1114WM00",
            menu_id="PPM0221",
            trees=lambda: [],
            options=lambda: [],
        )

    @staticmethod
    def render(screen):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            workflow.show_screen_offer(screen)
        return output.getvalue().replace("\033[0m", "")

    def test_lists_every_other_input_with_set_guidance(self):
        output = self.render(self.screen([
            {"label": "Category", "control": "edtCategory", "value": "A"},
            {"label": "", "control": "edtSecond", "value": ""},
        ]))

        self.assertIn("OTHER INPUTS (2)", output)
        self.assertIn("Category", output)
        self.assertIn("Control   edtCategory", output)
        self.assertIn("Current   A", output)
        self.assertIn('--set "Category=<value>"', output)
        self.assertIn("edtSecond", output)
        self.assertIn('--set "edtSecond=<value>"', output)
        self.assertIn("Current   (empty)", output)

    def test_long_details_wrap_inside_terminal_width(self):
        old_width = ui.WIDTH
        ui.WIDTH = 60
        try:
            output = self.render(self.screen([{
                "label": "A very long category filter label",
                "control": "edtCategoryWithAnUnusuallyLongGeneratedName",
                "value": "A value that is deliberately long enough to require wrapping",
            }]))
        finally:
            ui.WIDTH = old_width

        section = output.split("OTHER INPUTS", 1)[1].split(
            "    Divisions", 1)[0]
        self.assertTrue(all(len(line) <= 60 for line in section.splitlines()))
        self.assertIn("edtCategoryWithAnUnusuallyLongGeneratedNam", section)
        self.assertIn("                  e", section)
        self.assertIn("--set", section)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline tests for the G-MES interactive summary renderer."""
import contextlib
import io
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class RecordOrReplayQuestion(unittest.TestCase):
    """Live-caught (HISTORY.md Phase 62.4): a person typed the screen code
    they wanted straight into "Record or Replay?", and the old
    `answer.startswith("p")` read "P1114WM00" as Replay - almost every
    screen code in this account starts with P."""

    @staticmethod
    def run_with_answers(answers):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                mock.patch("builtins.input", side_effect=answers):
            mode = workflow.question_mode(workflow.Questions())
        return mode, output.getvalue()

    def test_a_screen_code_is_not_silently_read_as_replay(self):
        mode, out = self.run_with_answers(["P1114WM00", "p"])
        self.assertEqual(mode, "replay")
        self.assertIn("looks like a screen code, not R or P", out)

    def test_exact_letter_answers_still_work(self):
        self.assertEqual(self.run_with_answers(["r"])[0], "record")
        self.assertEqual(self.run_with_answers(["p"])[0], "replay")
        self.assertEqual(self.run_with_answers(["replay"])[0], "replay")

    def test_a_wrong_answer_does_not_renumber_the_question(self):
        # input()'s own prompt text (where the question label actually
        # appears) is never echoed to stdout by a mocked input(), so the
        # label is observed by patching the module's ask() instead - which
        # is exactly what Questions.ask()/again() call, and what carries
        # the number.
        labels = []
        answers = iter(["xyz", "p"])

        def fake_ask(label, hint="", default=""):
            labels.append(label)
            return next(answers).strip() or default

        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("run_gmes_workflow.ask", side_effect=fake_ask):
            workflow.question_mode(workflow.Questions())

        self.assertEqual(labels, ["1. Record or Replay?", "1. Record or Replay?"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

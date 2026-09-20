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


class RecordedScreensListShowsEveryRecording(unittest.TestCase):
    """HISTORY.md Phase 82.19, reported by the project owner from a
    screenshot: 17 screens were recorded and the Replay list showed nine.
    `question_screen()` sliced `saved[:9]` in BOTH the listing and the
    number-picker (on the assumption that "a single digit picks"), so the
    last eight recordings were neither displayed nor selectable by number -
    silently, with nothing saying the list was cut. `known()` itself was
    fine; every profile file on disk was returned."""

    CODES = [f"Q{2000 + i}UM00" for i in range(1, 18)]      # 17 recordings

    def profiles(self, count=17):
        return [{"screen": c, "title": f"Report number {i}",
                 "values": {"division": "VD"}}
                for i, c in enumerate(self.CODES[:count], start=1)]

    def ask(self, answers, count=17):
        """Run the real question with a mocked keyboard. Returns
        (chosen screen code, everything that was printed)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch("builtins.input", side_effect=answers), \
                mock.patch.object(workflow.gmes_profile, "known",
                                  return_value=self.profiles(count)):
            chosen = workflow.question_screen(workflow.Questions(), ws=None)
        return chosen, out.getvalue().replace("\033[0m", "")

    def test_all_seventeen_are_listed(self):
        _, printed = self.ask(["1"])
        for code in self.CODES:
            with self.subTest(code=code):
                self.assertIn(code, printed)

    def test_the_heading_says_how_many_there_are(self):
        # A list that states its own length cannot be silently short.
        _, printed = self.ask(["1"])
        self.assertIn("Screens already recorded (17):", printed)

    def test_a_number_above_nine_picks_that_screen(self):
        for number in (10, 12, 17):
            with self.subTest(number=number):
                chosen, _ = self.ask([str(number)])
                self.assertEqual(chosen, self.CODES[number - 1])

    def test_the_numbers_below_ten_still_pick_the_same_screens(self):
        for number in (1, 5, 9):
            with self.subTest(number=number):
                chosen, _ = self.ask([str(number)])
                self.assertEqual(chosen, self.CODES[number - 1])

    def test_a_short_list_is_unchanged(self):
        chosen, printed = self.ask(["3"], count=4)
        self.assertEqual(chosen, self.CODES[2])
        self.assertIn("Screens already recorded (4):", printed)

    def test_numbers_line_up_when_the_list_passes_nine(self):
        # Right-aligned, so " 1" and "17" share a column instead of the
        # screen codes shifting one place at row 10.
        _, printed = self.ask(["1"])
        rows = [l for l in printed.splitlines()
                if "Report number" in l and "UM00" in l]
        self.assertEqual(len(rows), 17)
        starts = {l.index("Q2") for l in rows}
        self.assertEqual(len(starts), 1, "screen codes are not in one column")

    def test_no_hard_coded_cap_is_left_in_the_code(self):
        # Comment lines are skipped: the explanation of why the cap was
        # removed names it, and must be allowed to.
        import inspect
        import re
        code_lines = [l for l in inspect.getsource(workflow.question_screen).splitlines()
                      if not l.lstrip().startswith("#")]
        for line in code_lines:
            with self.subTest(line=line.strip()):
                self.assertIsNone(re.search(r"saved\[:\d+\]", line))


class QuestionFiltersRoundTrip(unittest.TestCase):
    """Accepting the shown default unchanged has to return exactly what was
    remembered, not re-parse the "A=1; B=2" display string this question
    builds to SHOW two or more remembered filters - splitting that on the
    first "=" merged the second filter into the first one's value, and the
    second filter silently vanished."""

    def ask_with(self, raw):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("builtins.input", return_value=raw):
            return workflow.question_filters(workflow.Questions(),
                                             {"Production Order": "011074232146",
                                              "Model Code": "SM-A137F"})

    def test_accepting_two_remembered_filters_unchanged_keeps_both(self):
        # Blank input makes ask() fall back to the pre-filled default,
        # which IS the "A=1; B=2"-joined string - this is the "just press
        # Enter" path, the one actually reachable through blank input.
        result = self.ask_with("")
        self.assertEqual(result, {"Production Order": "011074232146",
                                  "Model Code": "SM-A137F"})

    def test_a_genuinely_new_single_filter_still_works(self):
        result = self.ask_with("Plant=P703")
        self.assertEqual(result, {"Plant": "P703"})


class ReconcileMode(unittest.TestCase):
    """RECORD over an already-learned screen must NOT discard it on disk
    the moment it is chosen - a live review caught that the earlier version
    of this function did exactly that (gmes_profile.forget(), called here,
    before the screen was even opened or the run confirmed), so cancelling
    or a later failure left the old, working profile gone with nothing to
    replace it. The fix is `relearning`: the caller runs with
    `trust_profile=False` instead, so core.run_screen() does not load or
    trust the old profile but still atomically replaces it via its own
    save() - only on actual success (HISTORY.md Phase 66)."""

    PROFILE = {"learned": "2026-09-01", "values": {"division": "VD"}}

    def call(self, mode, code, profile):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(workflow.gmes_profile, "forget") as forget:
            result = workflow.reconcile_mode(mode, code, profile)
        forget.assert_not_called()   # never touches disk, in any case
        return result

    def test_record_over_a_learned_screen_marks_relearning_without_forgetting(self):
        mode, profile, old_profile, relearning = self.call(
            "record", "P1112UM00", dict(self.PROFILE))
        self.assertEqual(mode, "record")
        self.assertIsNone(profile)
        self.assertEqual(old_profile, self.PROFILE)
        self.assertTrue(relearning)

    def test_replay_on_an_unlearned_screen_falls_back_to_record_not_relearning(self):
        mode, profile, old_profile, relearning = self.call(
            "replay", "P1112UM00", None)
        self.assertEqual(mode, "record")
        self.assertIsNone(profile)
        self.assertIsNone(old_profile)
        self.assertFalse(relearning)   # nothing existed to discard

    def test_the_matching_cases_are_left_alone(self):
        result = self.call("replay", "P1112UM00", dict(self.PROFILE))
        self.assertEqual(result, ("replay", self.PROFILE, None, False))

        result = self.call("record", "P1112UM00", None)
        self.assertEqual(result, ("record", None, None, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)

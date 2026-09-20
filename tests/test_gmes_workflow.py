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
        self.assertIn("looks like a screen code, not R, P or B", out)

    def test_exact_letter_answers_still_work(self):
        self.assertEqual(self.run_with_answers(["r"])[0], "record")
        self.assertEqual(self.run_with_answers(["p"])[0], "replay")
        self.assertEqual(self.run_with_answers(["replay"])[0], "replay")

    def test_batch_is_a_third_answer(self):
        self.assertEqual(self.run_with_answers(["b"])[0], "batch")
        self.assertEqual(self.run_with_answers(["Batch"])[0], "batch")

    def test_a_screen_code_starting_with_b_is_not_read_as_batch(self):
        """The same trap one letter over: a code typed here must be refused,
        not matched on its first letter."""
        mode, out = self.run_with_answers(["B1234WM00", "b"])
        self.assertEqual(mode, "batch")
        self.assertIn("looks like a screen code", out)

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

        self.assertEqual(labels, ["1. Record, Replay or Batch?",
                                  "1. Record, Replay or Batch?"])


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


class BatchAnswers(unittest.TestCase):
    """The small parsers behind the Batch questions. Each one refuses what it
    does not understand - the question is then asked again, never guessed."""

    def test_dates_default_to_yesterday_and_are_validated_now_not_at_run_time(self):
        self.assertEqual(workflow.parse_batch_dates(""), "yesterday")
        self.assertEqual(workflow.parse_batch_dates(" Today "), "today")
        self.assertEqual(workflow.parse_batch_dates("-2"), "-2")
        self.assertEqual(workflow.parse_batch_dates("keep"), "keep")
        for bad in ("someday", "20261399", "tomorrow"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workflow.parse_batch_dates(bad)

    def test_actions(self):
        for word, want in (("n", "now"), ("Run", "now"), ("s", "schedule"),
                           ("schedule", "schedule"), ("V", "save"), ("save", "save")):
            self.assertEqual(workflow.parse_batch_action(word), want)
        for bad in ("", "x", "yes", "nn"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workflow.parse_batch_action(bad)

    def test_names(self):
        self.assertEqual(workflow.parse_batch_name(" morning "), "morning")
        for bad in ("", "a b", "..\\x", "x" * 41):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workflow.parse_batch_name(bad)

    def test_when(self):
        w = workflow.parse_batch_when("06:30 daily")
        self.assertEqual((w.at, w.kind), ("06:30", "daily"))
        self.assertEqual(workflow.parse_batch_when("6:30").kind, "daily")     # daily is the default
        self.assertEqual(workflow.parse_batch_when("07:00 weekdays").days,
                         ["mon", "tue", "wed", "thu", "fri"])
        self.assertEqual(workflow.parse_batch_when("07:00 mon,wed,fri").days,
                         ["mon", "wed", "fri"])
        o = workflow.parse_batch_when("23:00 once 2026-09-25")
        self.assertEqual((o.kind, o.on), ("once", "2026-09-25"))
        for bad in ("", "daily", "25:00 daily", "06:30 fortnightly", "06:30 once soon"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workflow.parse_batch_when(bad)


class BatchFlow(unittest.TestCase):
    """The interactive Batch dialogue: choose, decide dates, SEE THE PLAN, then
    run now / schedule / save. Nothing may be queried before the plan is shown,
    and a plan with nothing runnable must not ask any further question."""

    PROFILES = [
        {"screen": "A1", "title": "Alpha", "learned": True,
         "values": {"division": "VD", "from": "20260901", "to": "20260901", "verify": "ymd"}},
        {"screen": "B2", "title": "Beta", "learned": True, "values": {"division": "VD"}},
        {"screen": "C3", "title": "Gamma", "learned": False, "values": {}},
    ]

    def flow(self, answers, profiles=None, saved=None, **patches):
        import gmes_batch
        import gmes_schedule
        out = io.StringIO()
        results = [gmes_batch._result(c, "ok", rows=1) for c in ("A1", "B2")]
        run_batch = patches.pop("run_batch", mock.Mock(return_value=results))
        save_batch = mock.Mock()
        create = patches.pop("create", mock.Mock())
        with contextlib.redirect_stdout(out), \
                mock.patch("builtins.input", side_effect=answers), \
                mock.patch.object(workflow.gmes_profile, "known",
                                  return_value=self.PROFILES if profiles is None else profiles), \
                mock.patch.object(gmes_batch, "list_batches", return_value=saved or {}), \
                mock.patch.object(gmes_batch, "run_batch", run_batch), \
                mock.patch.object(gmes_batch, "save_batch", save_batch), \
                mock.patch.object(gmes_batch, "write_report", return_value=("j.json", "r.txt")), \
                mock.patch.object(gmes_schedule, "create", create):
            done = workflow.batch_flow(workflow.Questions(), object())
        return done, out.getvalue(), run_batch, save_batch, create

    def test_run_now_shows_the_plan_first_then_runs_only_what_is_runnable(self):
        done, out, run_batch, save_batch, create = self.flow(["all", "", "n"])
        self.assertTrue(done)
        self.assertLess(out.index("PLAN"), out.index("BATCH SUMMARY"))
        plan = run_batch.call_args[0][1]
        self.assertEqual([(i.code, i.ready) for i in plan],
                         [("A1", True), ("B2", True), ("C3", False)])
        save_batch.assert_not_called()
        create.assert_not_called()

    def test_yesterday_is_the_default_date_and_reaches_the_plan(self):
        import gmes_batch
        _done, out, run_batch, *_ = self.flow(["1", "", "n"])
        expected = gmes_batch.resolve_dates("yesterday")[0]
        self.assertEqual(run_batch.call_args[0][1][0].spec["date_from"], expected)

    def test_a_chosen_subset_runs_only_those_screens(self):
        _d, _o, run_batch, *_ = self.flow(["2", "", "n"])
        self.assertEqual([i.code for i in run_batch.call_args[0][1]], ["B2"])

    def test_a_bad_selection_is_asked_again_with_the_same_question_number(self):
        labels = []
        answers = iter(["99", "nonsense", "1", "", "n"])

        def fake_ask(label, hint="", default=""):
            labels.append(label)
            return next(answers).strip() or default

        import gmes_batch
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch("run_gmes_workflow.ask", side_effect=fake_ask), \
                mock.patch.object(workflow.gmes_profile, "known", return_value=self.PROFILES), \
                mock.patch.object(gmes_batch, "list_batches", return_value={}), \
                mock.patch.object(gmes_batch, "run_batch", return_value=[]), \
                mock.patch.object(gmes_batch, "write_report", return_value=("j", "t")):
            workflow.batch_flow(workflow.Questions(), object())
        self.assertEqual(labels[:3], ["1. Which screens?"] * 3)
        self.assertEqual(labels[3], "2. Which dates?")

    def test_a_plan_with_nothing_runnable_asks_nothing_further_and_runs_nothing(self):
        # Exactly two answers are supplied: a third input() would raise StopIteration.
        done, out, run_batch, save_batch, create = self.flow(["1", ""], profiles=[self.PROFILES[2]])
        self.assertFalse(done)
        self.assertIn("None of these can run", out)
        run_batch.assert_not_called()
        save_batch.assert_not_called()

    def test_nothing_recorded_says_so_and_asks_nothing(self):
        done, out, run_batch, *_ = self.flow([], profiles=[])
        self.assertFalse(done)
        self.assertIn("Nothing is recorded", out)
        run_batch.assert_not_called()

    def test_save_only_saves_the_list_and_schedules_nothing(self):
        done, _o, run_batch, save_batch, create = self.flow(["1,2", "-1", "v", "am"])
        self.assertTrue(done)
        save_batch.assert_called_once_with("am", ["A1", "B2"], "-1", "both")
        run_batch.assert_not_called()
        create.assert_not_called()

    def test_schedule_saves_the_list_then_registers_the_task_for_that_name(self):
        done, out, run_batch, save_batch, create = self.flow(
            ["all", "", "s", "morning", "07:15 weekdays"])
        self.assertTrue(done)
        save_batch.assert_called_once_with("morning", ["A1", "B2", "C3"], "yesterday", "both")
        name, when = create.call_args[0]
        self.assertEqual((name, when.at, when.kind), ("morning", "07:15", "weekly"))
        run_batch.assert_not_called()                 # scheduling is not running
        self.assertIn("only while you are signed in", out)

    def test_a_bad_time_is_asked_again_before_anything_is_registered(self):
        _d, _o, _r, _s, create = self.flow(
            ["all", "", "s", "am", "25:99 daily", "yesterday", "06:30 daily"])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args[0][1].at, "06:30")

    def test_task_scheduler_refusing_is_reported_not_swallowed(self):
        import gmes_schedule
        done, out, *_ = self.flow(
            ["all", "", "s", "am", "06:30 daily"],
            create=mock.Mock(side_effect=gmes_schedule.ScheduleError("Access is denied")))
        self.assertFalse(done)
        self.assertIn("Access is denied", out)

    def test_a_saved_list_can_be_chosen_by_name(self):
        _d, _o, run_batch, *_ = self.flow(
            ["@am", "", "n"], saved={"am": {"screens": ["B2"], "date": "yesterday"}})
        self.assertEqual([i.code for i in run_batch.call_args[0][1]], ["B2"])

    def test_the_run_reports_failure_when_any_screen_did_not_succeed(self):
        import gmes_batch
        bad = [gmes_batch._result("A1", "ok"), gmes_batch._result("B2", "failed")]
        done, *_ = self.flow(["1,2", "", "n"], run_batch=mock.Mock(return_value=bad))
        self.assertFalse(done)

    def test_the_mode_menu_hands_over_to_the_batch_dialogue(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(workflow, "question_mode", return_value="batch"), \
                mock.patch.object(workflow, "batch_flow", return_value=True) as flow:
            result = workflow.one_run(object())
        self.assertTrue(result)
        flow.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

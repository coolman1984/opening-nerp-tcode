"""The guided workflow shows the screen's own choices before asking for any."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import workflow_uc
from gmes.cli import app
from gmes.contracts import (DataExecution, FilterRef, GridRef, LoginAttempt, LoginOutcome,
                            OptionRef, QuickViewRef, RunResult, ScreenInfo, ScreenPreview,
                            TreeRef)


ORDER = FilterRef("dsFilter", "paramProdOrderNo", "edtOrder", label="Production Order")
PLANT = FilterRef("dsFilter", "paramPlant", "cboPlant", label="Plant", value="VD")
TYPED = FilterRef("", "", "edtModel", label="Model", bound=False, id="win.form.edtModel")
PREVIEW = ScreenPreview(
    code="P1112UM00", title="Master Plan",
    filters=(ORDER, PLANT), unbound=(TYPED,),
    options=(OptionRef("Plan Date", state="selected"),
             OptionRef("Create Date", state="not selected"),
             OptionRef("Including Past Org.", state="unchecked")),
    trees=(TreeRef("Org.xfdl.js", "dsTree", names=("VD", "MOBILE"), settable=True),
           TreeRef("Prod.xfdl.js", "dsProd", names=("VD",), settable=True),
           TreeRef("Read.xfdl.js", "dsRead", names=("HIDDEN",), settable=False)),
    quick_views=(QuickViewRef("P1112UM00", "Master", active=True),
                 QuickViewRef("P1112WM00", "Detail")),
    date_columns=("planYmd",))


class PreviewShapeTests(unittest.TestCase):
    def test_settable_covers_both_bound_and_typed_controls(self):
        self.assertEqual(PREVIEW.settable, (ORDER, PLANT, TYPED))

    def test_divisions_are_deduplicated_and_exclude_trees_that_cannot_be_ticked(self):
        self.assertEqual(PREVIEW.divisions, ("MOBILE", "VD"))


class BuildPreviewTests(unittest.TestCase):
    def screen(self, **overrides):
        screen = Mock(code="P1112UM00", title="Master Plan", filters=(ORDER,), unbound=(),
                      warnings=["a Quick View panel is present"],
                      info=ScreenInfo("P1112UM00", quick_views=(QuickViewRef("P1112WM00"),),
                                      grids=(GridRef("grd", "dsResult"),)))
        screen.options.return_value = (OptionRef("Plan Date", state="selected"),)
        screen.trees.return_value = ()
        screen.date_like_columns.return_value = ["planYmd"]
        screen.grid.return_value = GridRef("grd", "dsResult")
        for name, value in overrides.items():
            getattr(screen, name).side_effect = value
        return screen

    def test_a_preview_carries_every_filter_and_option_the_screen_reports(self):
        preview = workflow_uc.build_preview(self.screen())
        self.assertEqual(preview.filters, (ORDER,))
        self.assertEqual(preview.options[0].label, "Plan Date")
        self.assertEqual(preview.date_columns, ("planYmd",))
        self.assertIn("a Quick View panel is present", preview.warnings)

    def test_an_ambiguous_result_grid_is_shown_as_a_warning_not_raised(self):
        screen = self.screen(grid=RuntimeError("more than one plausible result grid"))
        preview = workflow_uc.build_preview(screen)
        self.assertEqual(preview.date_columns, ())
        self.assertIn("more than one plausible result grid", " ".join(preview.warnings))


class GuideOrderTests(unittest.TestCase):
    """Open and read the screen BEFORE the operator is asked anything."""

    def setUp(self):
        self.events = []
        self.enterContext(patch.object(
            workflow_uc, "preview_screen",
            side_effect=lambda ws, code, log=print: self.events.append(f"read {code}") or PREVIEW))
        self.run = self.enterContext(patch.object(
            workflow_uc, "run_many",
            side_effect=lambda ws, specs, log=print: self.events.append("run")
            or [RunResult(screen=specs[0].screen_code, ok=True, rows=5)]))

    def interview(self, request, screens=(("P1112UM00", None),)):
        asked = []
        interview = Mock()
        interview.choose_screen.side_effect = list(screens)
        interview.choose_values.side_effect = \
            lambda preview, profile: asked.append(preview) or request
        interview.again.return_value = False
        return interview, asked

    def test_the_screen_is_read_before_the_questions_and_run_after_them(self):
        interview, asked = self.interview({"division": "VD", "sets": [], "options": []})
        self.assertTrue(workflow_uc.guide(object(), interview, log=lambda _: None))
        self.assertEqual(self.events, ["read P1112UM00", "run"])
        self.assertEqual(asked[0].code, "P1112UM00")
        self.assertEqual(self.run.call_args.args[1][0].division, "VD")

    def test_a_screen_that_will_not_open_is_reported_and_nothing_is_run(self):
        interview, _asked = self.interview({})
        with patch.object(workflow_uc, "preview_screen",
                          side_effect=RuntimeError("never finished building")):
            self.assertFalse(workflow_uc.guide(object(), interview, log=lambda _: None))
        interview.report_open_failure.assert_called_once()
        interview.choose_values.assert_not_called()
        self.run.assert_not_called()

    def test_a_failed_run_is_reported_and_does_not_end_the_sitting_successfully(self):
        interview, _asked = self.interview({"sets": [], "options": []})
        self.run.side_effect = lambda ws, specs, log=print: [
            RunResult(screen="P1112UM00", ok=False, error="no rows")]
        self.assertFalse(workflow_uc.guide(object(), interview, log=lambda _: None))
        interview.report.assert_called_once()

    def test_no_screen_code_stops_without_opening_anything(self):
        interview, _asked = self.interview({}, screens=(("", None),))
        self.assertFalse(workflow_uc.guide(object(), interview, log=lambda _: None))
        interview.choose_values.assert_not_called()


class InterviewPresentationTests(unittest.TestCase):
    """Every choice is listed; nothing the screen offers is hidden."""

    def show(self, function, *args):
        captured = io.StringIO()
        with redirect_stdout(captured):
            value = function(*args)
        return value, captured.getvalue()

    def test_every_filter_is_listed_with_its_name_and_current_value(self):
        listed, printed = self.show(app._show_filters, PREVIEW)
        self.assertEqual(listed, PREVIEW.settable)
        self.assertIn("Production Order", printed)
        self.assertIn("paramProdOrderNo", printed)
        self.assertIn("'VD'", printed)
        self.assertIn("typed", printed)

    def test_every_option_is_listed_with_the_state_the_screen_reports(self):
        _listed, printed = self.show(app._show_options, PREVIEW)
        self.assertIn("Plan Date", printed)
        self.assertIn("[selected]", printed)
        self.assertIn("Create Date", printed)
        self.assertIn("[not selected]", printed)

    def test_divisions_and_other_screens_are_named_rather_than_left_to_memory(self):
        _value, printed = self.show(app._show_context, PREVIEW)
        self.assertIn("MOBILE, VD", printed)
        self.assertIn("P1112WM00", printed)
        self.assertIn("not an option here", printed)
        self.assertIn("planYmd", printed)


class InterviewAnswerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def answers(self, *replies):
        return patch.object(app, "_ask", side_effect=list(replies))

    def test_a_filter_chosen_by_number_is_sent_under_the_name_the_engine_resolves(self):
        with self.answers("1", "4501234567", ""):
            chosen = app._ask_filters(PREVIEW.settable, {})
        self.assertEqual(chosen, ["paramProdOrderNo=4501234567"])

    def test_a_typed_control_is_sent_under_its_control_name(self):
        with self.answers("3", "SM-A356", ""):
            self.assertEqual(app._ask_filters(PREVIEW.settable, {}), ["edtModel=SM-A356"])

    def test_a_blank_value_removes_a_remembered_filter(self):
        with self.answers("2", "", ""):
            self.assertEqual(app._ask_filters(PREVIEW.settable, {"paramPlant": "VD"}), [])

    def test_a_name_typed_instead_of_a_number_is_passed_through_untouched(self):
        with self.answers("paramWorkCenter", "L01", ""):
            self.assertEqual(app._ask_filters(PREVIEW.settable, {}), ["paramWorkCenter=L01"])

    def test_options_are_chosen_by_their_listed_number_or_by_label(self):
        with self.answers("o2"):
            self.assertEqual(app._ask_options(PREVIEW.options, []), ["Create Date"])
        with self.answers("3, Plan Date"):
            self.assertEqual(app._ask_options(PREVIEW.options, []),
                             ["Including Past Org.", "Plan Date"])

    def test_a_dated_run_keeps_asking_until_a_verification_column_is_named(self):
        with self.answers("", "planYmd"):
            self.assertEqual(app._ask_verify(PREVIEW, ""), "planYmd")


class WorkflowCommandTests(unittest.TestCase):
    def test_the_workflow_command_hands_its_interview_to_one_application_operation(self):
        execution = DataExecution(LoginAttempt(LoginOutcome.OK), value=True)
        with patch.object(app.application, "execute_guided_workflow",
                          return_value=execution) as guided, redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["workflow"]), 0)
        self.assertTrue(hasattr(guided.call_args.args[0], "choose_values"))

    def test_a_sign_in_that_did_not_complete_is_reported_and_fails_the_command(self):
        execution = DataExecution(LoginAttempt(LoginOutcome.REJECTED, "no saved credentials"))
        captured = io.StringIO()
        with patch.object(app.application, "execute_guided_workflow", return_value=execution), \
             redirect_stdout(captured):
            self.assertEqual(app.main(["workflow"]), 1)
        self.assertIn("no saved credentials", captured.getvalue())

    def test_closed_input_ends_the_workflow_without_a_traceback(self):
        with patch.object(app.application, "execute_guided_workflow",
                          side_effect=app._WorkflowInputClosed()), redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["workflow"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

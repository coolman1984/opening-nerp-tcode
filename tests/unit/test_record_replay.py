"""Recording a screen, and being able to replay what was recorded.

The bug these were written for: a screen recorded WITH a left-panel option
could never be replayed. Options rebuild the panel, so the shape recorded at
the end of a run was the post-option screen, while the drift check on the
next run compared it against the screen as freshly opened. The shapes
differed, the profile was refused as "the screen's controls have changed",
and the operator saw a tool that would not remember anything it had just
learned - on exactly the screens they had been told to use options on.
"""
import importlib
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import FilterRef, GridRef, RunSpec, ScreenInfo
from gmes.discovery.fingerprint import fingerprint

ORDER = FilterRef("dsFilter", "poNo", "edtOrder", label="Order")
PLAN_DATE = FilterRef("dsFilter", "planYmd", "mskPlan", label="Plan Date")
CREATE_DATE = FilterRef("dsFilter", "createYmd", "mskCreate", label="Create Date")
GRID = GridRef("grdResult", "dsResult", "P1112WM00.xfdl.js")

# The same screen before and after clicking a left-panel option. The option
# rebuilds the panel, so a different date field is bound afterwards - which is
# the whole reason the option exists.
AS_OPENED = ScreenInfo("P1112UM00", filters=(ORDER, PLAN_DATE), grids=(GRID,))
AFTER_OPTION = ScreenInfo("P1112UM00", filters=(ORDER, CREATE_DATE), grids=(GRID,))


class PanelRebuildTests(unittest.TestCase):
    def test_an_option_that_rebuilds_the_panel_really_does_change_the_shape(self):
        """The premise: without this the bug below could not happen."""
        self.assertNotEqual(fingerprint(AS_OPENED), fingerprint(AFTER_OPTION))


class RecordThenReplayTests(unittest.TestCase):
    """Record a screen with an option, then replay it - the round trip."""

    def setUp(self):
        self.uc = importlib.import_module("gmes.application.run_screen_uc")
        self.enterContext(patch.object(self.uc.popups, "close_notices",
                                       return_value=([], [])))
        self.saved = {}
        self.enterContext(patch.object(self.uc.store, "save",
                                       side_effect=self.remember))
        self.enterContext(patch.object(self.uc, "org_selection",
                                       return_value={"found": True, "org": "VD"}))
        self.screen = self.fresh_screen()
        self.enterContext(patch.object(self.uc, "open_screen",
                                       side_effect=lambda *a, **k: self.screen))

    def remember(self, code, title, menu_id, info, **kwargs):
        """Stand in for profiles/store.save, keeping what it would write."""
        self.saved = {"screen": code, "fingerprint": fingerprint(info),
                      "grid": {"dataset": kwargs["grid"].dataset},
                      "options": [str(option) for option in kwargs.get("options", ())],
                      "values": {}}
        return "fake.json"

    def fresh_screen(self):
        """A screen whose panel is rebuilt by set_option, as the real one is."""
        screen = Mock(title="Plan", menu_id="PPM0219", win_id="winFake",
                      info=AS_OPENED, filters=AS_OPENED.filters, unbound=(),
                      warnings=[], last_tree=None)
        screen.grid.return_value = GRID
        screen.clear_stale.return_value = []
        screen.inquiry.return_value = 12
        screen.to_csv.return_value = Mock(checked=True, path=__file__, row_count=12)

        def set_option(label):
            screen.info = AFTER_OPTION
            screen.filters = AFTER_OPTION.filters
            return f"{label} -> selected"

        screen.set_option.side_effect = set_option
        return screen

    def run_spec(self, **kwargs):
        kwargs.setdefault("export", "csv")
        return self.uc.run_screen(object(), RunSpec("P1112UM00", **kwargs),
                                  log=lambda _: None)

    def test_a_screen_recorded_with_an_option_can_be_replayed(self):
        with patch.object(self.uc.store, "load", return_value=None):
            self.assertTrue(self.run_spec(options=("Create Date",)).ok)
        recorded = dict(self.saved)
        self.assertEqual(recorded["options"], ["Create Date"])

        # A second run, on a screen that opens exactly as the first one did.
        self.screen = self.fresh_screen()
        with patch.object(self.uc.store, "load", return_value=recorded):
            result = self.run_spec()
        self.assertTrue(result.ok)
        self.assertTrue(result.used_profile)
        # The saved option was replayed, not silently dropped.
        self.screen.set_option.assert_called_once_with("Create Date")

    def test_a_screen_recorded_without_options_still_replays(self):
        with patch.object(self.uc.store, "load", return_value=None):
            self.assertTrue(self.run_spec().ok)
        recorded = dict(self.saved)

        self.screen = self.fresh_screen()
        with patch.object(self.uc.store, "load", return_value=recorded):
            self.assertTrue(self.run_spec().ok)

    def test_a_screen_that_really_changed_is_still_refused(self):
        """The check must keep working - this is not a licence to replay
        a profile whose screen has genuinely moved."""
        with patch.object(self.uc.store, "load", return_value=None):
            self.run_spec(options=("Create Date",))
        recorded = dict(self.saved)
        recorded["fingerprint"] = "something-else-entirely"

        self.screen = self.fresh_screen()
        with patch.object(self.uc.store, "load", return_value=recorded):
            with self.assertRaisesRegex(RuntimeError, "remembered screen shape changed"):
                self.run_spec()

    def test_the_refusal_says_how_to_get_out_of_it(self):
        recorded = {"screen": "P1112UM00", "fingerprint": "gone", "grid": {}, "values": {}}
        with patch.object(self.uc.store, "load", return_value=recorded):
            with self.assertRaises(RuntimeError) as refused:
                self.run_spec()
        self.assertIn("--relearn", str(refused.exception))

    def test_relearn_records_the_screen_again_instead_of_dead_ending(self):
        recorded = {"screen": "P1112UM00", "fingerprint": "gone", "grid": {}, "values": {}}
        with patch.object(self.uc.store, "load", return_value=recorded):
            result = self.run_spec(relearn=True)
        self.assertTrue(result.ok)
        self.assertFalse(result.used_profile)
        self.assertEqual(self.saved["fingerprint"], fingerprint(AS_OPENED))


class GuidedRelearnTests(unittest.TestCase):
    """The way out of a refused profile, for someone not on the command line."""

    def setUp(self):
        import io
        from contextlib import redirect_stdout
        self.enterContext(redirect_stdout(io.StringIO()))
        from gmes.cli import app
        from gmes.contracts import OptionRef, ScreenPreview
        self.app = app
        self.preview = ScreenPreview(code="P1112UM00", title="Plan",
                                     filters=(ORDER,),
                                     options=(OptionRef("Create Date", state="not selected"),))
        self.profile = {"screen": "P1112UM00", "options": ["Plan Date"],
                        "values": {"division": "VD", "sets": {"poNo": "123"}}}

    def answers(self, *replies):
        return patch.object(self.app, "_ask", side_effect=list(replies))

    def test_plain_enter_still_replays_everything_that_was_proved(self):
        with self.answers(""):
            request = self.app._Interview().choose_values(self.preview, self.profile)
        self.assertEqual(request["division"], "VD")
        self.assertEqual(request["options"], ["Plan Date"])
        self.assertNotIn("relearn", request)

    def test_answering_r_records_the_screen_again_and_drops_what_was_saved(self):
        # division, from, to, filter-number(blank), options(blank)
        with self.answers("r", "", "", "", "", ""):
            request = self.app._Interview().choose_values(self.preview, self.profile)
        self.assertTrue(request["relearn"])
        self.assertEqual(request["options"], [])
        self.assertEqual(request["sets"], [])

    def test_run_is_not_mistaken_for_relearn(self):
        """'run' is the printed default and also begins with r."""
        with self.answers("run"):
            request = self.app._Interview().choose_values(self.preview, self.profile)
        self.assertNotIn("relearn", request)
        self.assertEqual(request["division"], "VD")

    def test_a_refused_profile_tells_the_operator_where_the_way_out_is(self):
        from gmes.contracts import RunResult
        import io
        from contextlib import redirect_stdout
        captured = io.StringIO()
        with redirect_stdout(captured):
            self.app._Interview().report(RunResult(
                screen="P1112UM00", ok=False,
                error="the remembered screen shape changed; ... with --relearn (...)"))
        self.assertIn("answer r at the Run choice", captured.getvalue())

    def test_answering_f_replays_the_saved_settings_with_force_set(self):
        with self.answers("f"):
            request = self.app._Interview().choose_values(self.preview, self.profile)
        self.assertTrue(request["force"])
        self.assertEqual(request["division"], "VD")   # still the saved settings

    def test_relearning_also_bypasses_the_breaker(self):
        """Recording a screen again is itself an explicit 'try anyway'."""
        with self.answers("r", "", "", "", "", ""):
            request = self.app._Interview().choose_values(self.preview, self.profile)
        self.assertTrue(request["force"])

    def test_a_skipped_screen_tells_the_operator_to_answer_f(self):
        from gmes.contracts import RunResult
        import io
        from contextlib import redirect_stdout
        captured = io.StringIO()
        with redirect_stdout(captured):
            self.app._Interview().report(RunResult(
                screen="P1112UM00", ok=False,
                error="P1112UM00 has failed 3 runs in a row ... 'gmes run P1112UM00 --force' ..."))
        self.assertIn("answer f at the Run choice", captured.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)

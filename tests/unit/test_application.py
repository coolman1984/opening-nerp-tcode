"""Offline orchestration tests; all browser and persistent-state edges are stubbed."""
import csv
import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import (DatasetPage, ExportResult, FilterRef, GridRef,
                            LoginAttempt, LoginOutcome, RunResult, RunSpec, ScreenInfo)


def require_module(test, name):
    full = "gmes.application." + name
    test.assertIsNotNone(importlib.util.find_spec(full), f"missing use case: {name}")
    return importlib.import_module(full)


class SignInTests(unittest.TestCase):
    def setUp(self):
        self.uc = require_module(self, "sign_in_uc")

    def test_transient_failure_retries_and_reports_attempt_count(self):
        attempt = Mock(side_effect=[LoginAttempt(LoginOutcome.FAILED),
                                    LoginAttempt(LoginOutcome.OK)])
        with patch.object(self.uc, "sign_in_once", attempt):
            result = self.uc.sign_in(log=lambda _: None)
        self.assertEqual(result, LoginAttempt(LoginOutcome.OK, attempts_used=2))
        self.assertEqual(attempt.call_count, 2)

    def test_rejection_and_success_never_retry(self):
        for outcome in (LoginOutcome.REJECTED, LoginOutcome.OK):
            with self.subTest(outcome=outcome), patch.object(
                    self.uc, "sign_in_once", return_value=LoginAttempt(outcome)) as attempt:
                self.assertEqual(self.uc.sign_in(log=lambda _: None).outcome, outcome)
                attempt.assert_called_once()

    def test_retry_cap_and_unknown_outcome_stop(self):
        with patch.object(self.uc, "sign_in_once", return_value=LoginAttempt(
                LoginOutcome.FAILED, "timeout")) as attempt:
            self.assertEqual(self.uc.sign_in(attempts=3, log=lambda _: None),
                             LoginAttempt(LoginOutcome.FAILED, "timeout", 3))
            self.assertEqual(attempt.call_count, 3)
        with patch.object(self.uc, "sign_in_once", return_value=True):
            with self.assertRaises(TypeError):
                self.uc.sign_in()

    def test_date_normalisation_invalid_calendar_and_days_back_precedence(self):
        self.assertEqual(self.uc.date_from_args("2026-09-07"), "20260907")
        self.assertIsNone(self.uc.date_from_args())
        with self.assertRaises(ValueError):
            self.uc.date_from_args("2026-02-30")
        with patch.object(self.uc, "datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1)
            self.assertEqual(self.uc.date_from_args("ignored", 1), "20251231")
            self.assertEqual(self.uc.date_from_args(days_back=0), "20260101")

    def test_existing_session_sweeps_popups_without_credentials_or_new_login(self):
        ws = Mock()
        with patch.object(self.uc.session, "ensure_browser"), \
             patch.object(self.uc.session, "open_gmes"), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc.session, "wait_for_login_or_session", return_value=("session", ws)), \
             patch.object(self.uc.session, "is_logged_in", return_value=(True, "fake user")), \
             patch.object(self.uc.credentials, "load") as creds, \
             patch.object(self.uc.popups, "close_child_popups") as sweep, \
             patch.object(self.uc.popups, "close_popups_when_they_appear") as watch, \
             patch.object(self.uc.popups, "find_child_popups", return_value={"count": 0}), \
             patch.object(self.uc.screenshots, "capture_screenshot"):
            self.assertEqual(self.uc.sign_in_once(log=lambda _: None).outcome, LoginOutcome.OK)
        creds.assert_not_called()
        sweep.assert_called_once_with(ws)
        watch.assert_not_called()
        ws.close.assert_called_once()

    def test_missing_credentials_are_terminal_and_socket_is_closed(self):
        ws = Mock()
        with patch.object(self.uc.session, "ensure_browser"), \
             patch.object(self.uc.session, "open_gmes"), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc.session, "wait_for_login_or_session", return_value=("login", ws)), \
             patch.object(self.uc.session, "is_logged_in", return_value=(False, "")), \
             patch.object(self.uc.credentials, "load", return_value=(None, None)), \
             patch.object(self.uc.login_flow, "click_by_id") as click:
            self.assertEqual(self.uc.sign_in_once(log=lambda _: None).outcome,
                             LoginOutcome.REJECTED)
        click.assert_not_called()
        ws.close.assert_called_once()

    def test_sso_failure_falls_back_to_direct_login_and_observed_session_wins(self):
        with patch.object(self.uc.credentials, "load", return_value=("fake", "fake-test-password")), \
             patch.object(self.uc.login_flow, "click_by_id", return_value=True), \
             patch.object(self.uc.login_flow, "wait_for_sso_window", return_value=("rejected", "stale message")), \
             patch.object(self.uc, "_wait_signed_in", side_effect=[(False, "stale message"), (True, "stale message")]), \
             patch.object(self.uc.login_flow, "direct_login", return_value=(True, "submitted")) as direct, \
             patch.object(self.uc.screenshots, "screenshot_on_failure") as shot:
            result = self.uc._authenticate(object(), lambda _: None)
        self.assertEqual(result.outcome, LoginOutcome.OK)
        direct.assert_called_once()
        shot.assert_not_called()

    def test_exhausted_auth_wait_classifies_terminal_message_vs_transient_timeout(self):
        for message, outcome in (("refused", LoginOutcome.REJECTED), ("", LoginOutcome.FAILED)):
            with patch.object(self.uc.credentials, "load", return_value=("fake", "fake-test-password")), \
                 patch.object(self.uc.login_flow, "click_by_id", return_value=True), \
                 patch.object(self.uc.login_flow, "wait_for_sso_window", return_value=None), \
                 patch.object(self.uc, "_wait_signed_in", return_value=(False, message)), \
                 patch.object(self.uc.login_flow, "direct_login", return_value=(True, "submitted")), \
                 patch.object(self.uc.screenshots, "screenshot_on_failure"):
                self.assertEqual(self.uc._authenticate(object(), lambda _: None).outcome, outcome)

    def test_unknown_readiness_state_stops_before_credentials_or_clicks(self):
        ws = Mock()
        with patch.object(self.uc.session, "ensure_browser"), \
             patch.object(self.uc.session, "open_gmes"), \
             patch.object(self.uc, "connect_gmes", return_value=ws), \
             patch.object(self.uc.session, "wait_for_login_or_session", return_value=("unknown", ws)), \
             patch.object(self.uc.session, "is_logged_in", return_value=(False, "")), \
             patch.object(self.uc, "_authenticate", return_value=LoginAttempt(LoginOutcome.OK)) as auth, \
             patch.object(self.uc.popups, "close_popups_when_they_appear"), \
             patch.object(self.uc.popups, "find_child_popups", return_value={"count": 0}), \
             patch.object(self.uc.screenshots, "capture_screenshot"):
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                self.uc.sign_in_once(log=lambda _: None)
        auth.assert_not_called()


class RunScreenTests(unittest.TestCase):
    def setUp(self):
        self.uc = require_module(self, "run_screen_uc")
        self.flt = FilterRef("dsFilter", "poNo", "edtOrder", label="Order")
        self.grid = GridRef("grdResult", "dsResult", "P1112WM00.xfdl.js")
        self.screen = Mock(title="Plan", menu_id="PPM0219", win_id="winFake",
                           info=ScreenInfo("P1112UM00", filters=(self.flt,)),
                           filters=(self.flt,), unbound=(), warnings=[], last_tree=None)
        self.screen.grid.return_value = self.grid
        self.screen.clear_stale.return_value = ["Old=stale"]
        self.screen.set_date_range.return_value = []
        self.screen.set_filter.return_value = (self.flt, "0123")
        self.screen.inquiry.return_value = 2
        self.screen.date_like_columns.return_value = []
        self.screen.close.return_value = (True, "closed")
        self.enterContext(patch.object(self.uc, "open_screen", return_value=self.screen))
        self.load = self.enterContext(patch.object(self.uc.store, "load", return_value=None))
        self.save = self.enterContext(patch.object(self.uc.store, "save", return_value="fake.json"))
        self.enterContext(patch.object(self.uc, "org_selection", return_value={"found": True, "org": "VD"}))

    def run_spec(self, **kwargs):
        return self.uc.run_screen(object(), RunSpec(" p1112um00 ", **kwargs), log=lambda _: None)

    def test_explicit_values_dry_run_and_stale_clear_do_not_query_or_save(self):
        sets = {"Order": "0123"}
        result = self.run_spec(sets=sets, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.screen, "P1112UM00")
        self.assertEqual(result.applied, {"Order": "0123"})
        self.assertEqual(result.cleared, ("Old=stale",))
        self.screen.clear_stale.assert_called_once_with({"poNo"})
        self.screen.inquiry.assert_not_called()
        self.save.assert_not_called()
        self.assertEqual(sets, {"Order": "0123"})

    def test_zero_rows_or_failed_verification_prevent_export_and_save(self):
        for count, failure in ((0, None), (2, RuntimeError("wrong day"))):
            with self.subTest(count=count):
                self.screen.inquiry.return_value = count
                self.screen.verify_column.side_effect = failure
                with self.assertRaises(RuntimeError):
                    self.run_spec(verify=("planYmd", "20260907"))
        self.screen.export_excel.assert_not_called()
        self.screen.to_csv.assert_not_called()
        self.save.assert_not_called()

    def test_drift_refuses_saved_options_grid_and_date_references(self):
        self.load.return_value = {"fingerprint": "old", "grid": {"dataset": "stale"},
                                  "options": ["Create Date"], "from": {"column": "gone"}}
        with patch.object(self.uc, "describe_change", return_value=["date field gone"]):
            result = self.run_spec(dry_run=True, date_from="20260907", date_to="20260907")
        self.assertFalse(result.used_profile)
        self.screen.grid.assert_called_once_with(None)
        self.screen.set_option.assert_not_called()
        self.screen.set_date_range.assert_called_once_with("20260907", "20260907", None)

    def test_valid_profile_options_precede_org_and_dates_and_explicit_options_override(self):
        self.load.return_value = {"grid": {"dataset": "dsResult"}, "division": None,
                                  "options": ["Plan Date"]}
        self.screen.select_org.return_value = {"ticked": [{"name": "VD"}], "cleared": []}
        events = []
        self.screen.set_option.side_effect = lambda label: events.append(label) or label
        self.screen.select_org.side_effect = lambda *a, **k: events.append("org") or {"ticked": [{"name": "VD"}]}
        self.screen.set_date_range.side_effect = lambda *a: events.append("dates") or []
        with patch.object(self.uc, "describe_change", return_value=[]):
            result = self.run_spec(division="vd", date_from="20260907", date_to="20260907", dry_run=True)
            self.assertTrue(result.used_profile)
            self.assertEqual(events, ["Plan Date", "org", "dates"])
            events.clear()
            self.run_spec(options=("Create Date",), dry_run=True)
            self.assertEqual(events, ["Create Date"])

    def test_small_valid_csv_is_checked_and_saved_after_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tiny.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("poNo\n0123\n")
            self.screen.to_csv.return_value = ExportResult(path, "csv", 1, True)
            result = self.run_spec(export="csv", out_dir=directory, close_after=True)
        self.assertEqual(result.files, (path,))
        self.assertEqual(result.csv_rows, 1)
        self.assertTrue(result.closed)
        self.assertEqual(self.save.call_args.kwargs["values"]["division"], "VD")

    def test_missing_csv_delivery_and_tiny_excel_prevent_profile_save(self):
        with tempfile.TemporaryDirectory() as directory:
            self.screen.to_csv.return_value = ExportResult("missing.csv", "csv", 2, False)
            with self.assertRaisesRegex(RuntimeError, "CSV"):
                self.run_spec(export="csv", out_dir=directory)
            tiny = os.path.join(directory, "download.xlsx")
            with open(tiny, "wb") as handle:
                handle.write(b"bad")
            self.screen.export_excel.return_value = tiny
            with self.assertRaisesRegex(RuntimeError, "not a real export"):
                self.run_spec(export="xlsx", out_dir=directory)
        self.save.assert_not_called()

    def test_verification_tuple_keeps_explicit_value_and_falls_back_to_from_date(self):
        for expected, actual in (("0", "0"), (None, "20260907")):
            self.run_spec(export="none", use_profile=False, verify=(" planYmd ", expected),
                          date_from="20260907")
            self.screen.verify_column.assert_called_with(self.grid, "planYmd", actual, strict=True)

    def test_default_output_keeps_exports_under_ignored_data_hub(self):
        with patch.object(self.uc, "_export", return_value=((), 0, 0)) as export:
            self.run_spec(export="none", use_profile=False)
        self.assertEqual(export.call_args.args[3], os.path.join(os.getcwd(), "Data Hub Folder", "GMES"))


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.uc = require_module(self, "run_many_uc")

    def test_batch_order_continues_after_failure_and_summary_reports_it(self):
        events = []
        def run(ws, spec, log):
            events.append(spec.screen_code)
            if spec.screen_code == "B":
                raise RuntimeError("unknown dialog")
            return RunResult(spec.screen_code, True, rows=2)
        with patch.object(self.uc, "run_screen", side_effect=run), \
             patch.object(self.uc, "screenshot_on_failure") as shot:
            result = self.uc.run_many(object(), [RunSpec(c) for c in "ABC"], log=lambda _: None)
        self.assertEqual(events, list("ABC"))
        self.assertEqual([r.ok for r in result], [True, False, True])
        self.assertEqual(result[1].error, "unknown dialog")
        shot.assert_called_once_with("gmes_B")
        summary = require_module(self, "run_screen_uc")
        lines = []
        self.assertEqual(summary.print_summary(result, log=lines.append), 2)
        self.assertIn("unknown dialog", "\n".join(lines))

    def test_failed_diagnostic_does_not_hide_failure_or_abort_remaining_specs(self):
        with patch.object(self.uc, "run_screen", side_effect=[RuntimeError("unknown dialog"), RunResult("B", True)]), \
             patch.object(self.uc, "screenshot_on_failure", side_effect=RuntimeError("no browser")):
            results = self.uc.run_many(object(), [RunSpec("A"), RunSpec("B")], log=lambda _: None)
        self.assertEqual([r.ok for r in results], [False, True])
        self.assertEqual(results[0].error, "unknown dialog")


if __name__ == "__main__":
    unittest.main(verbosity=2)

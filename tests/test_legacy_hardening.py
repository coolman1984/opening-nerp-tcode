"""Offline regression tests for the safety gates ported to the legacy path."""
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmes_common  # noqa: E402
import gmes_core as core  # noqa: E402
import gmes_daily_prodplan  # noqa: E402
import gmes_data  # noqa: E402
import gmes_inspect  # noqa: E402
import gmes_log  # noqa: E402
import gmes_login  # noqa: E402
import gmes_open_screen  # noqa: E402
import gmes_preflight  # noqa: E402
import gmes_report  # noqa: E402


def _screen(info):
    return core.Screen(None, "P1112UM00", {"title": "Test"}, info)


class _FakeClock:
    """A clock that only moves when the code sleeps.

    `gmes_login.main()` polls against wall-clock deadlines. With `sleep`
    merely stubbed out, those loops busy-spin for their full real duration -
    five seconds per test, for a suite that is otherwise measured in
    hundredths. Advancing a fake clock inside `sleep` makes them terminate
    deterministically and instantly, and removes any dependence on how fast
    the machine running the tests happens to be."""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.01)

    def strftime(self, *args, **kwargs):
        import time as _real_time
        return _real_time.strftime(*args, **kwargs)


class PasswordIsNeverSubmittedAfterAFailedSso(unittest.TestCase):
    """A failed corporate sign-in is NOT a failed password.

    Live, 2026-09-15: AD SSO's window did not open when the same account was
    signed in from a second browser profile. The code fell through to typing
    the saved password into G-MES's own login form, and the server answered
    with a counting modal - "attempt 1 of 5 before this account is locked".
    The password was almost certainly correct; the window had simply never
    appeared (HISTORY.md Phase 74).

    These tests pin the rule that came out of it: no automatic path may reach
    `direct_login()`, whatever the reason AD SSO failed. The password costs
    one of five attempts, and an SSO failure is not evidence worth spending
    one on.
    """

    def _run_login(self, sso_outcome, allow_password_login=False,
                   lockout=None, logged_in_after=False):
        """Drive gmes_login.main() to the point where the old code would have
        fallen through to the password form, and report whether it did."""
        ws = Mock()
        lockout = lockout or {"found": False}
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes"), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in",
                          return_value=(logged_in_after, "")), \
             patch.object(gmes_login.gmes_credentials, "load",
                          return_value=("someone", "a-password")), \
             patch.object(gmes_login, "click_by_id", return_value={"found": True}), \
             patch.object(gmes_login, "list_windows", return_value=[]), \
             patch.object(gmes_login, "wait_for_sso_window", return_value=sso_outcome), \
             patch.object(gmes_login, "lockout_warning", return_value=lockout), \
             patch.object(gmes_login, "login_error", return_value=""), \
             patch.object(gmes_login.gmes_common, "screenshot_on_failure"), \
             patch.object(gmes_login.gmes_common, "close_popups_when_they_appear",
                          return_value=[]), \
             patch.object(gmes_login.gmes_common, "close_child_popups", return_value=[]), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login.gmes_common, "capture_screenshot",
                          return_value="shot.png"), \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs",
                          return_value=""), \
             patch.object(gmes_login, "time", _FakeClock()), \
             patch.object(gmes_login, "direct_login",
                          return_value=(False, "not reached")) as direct:
            code = gmes_login.main(allow_password_login=allow_password_login)
        return code, direct

    def test_an_sso_window_that_never_opens_does_not_submit_the_password(self):
        code, direct = self._run_login(("no-window", ""))
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED,
                         "a failed SSO must be FAILED (transient), never REJECTED")

    def test_a_timeout_with_a_message_on_the_page_still_does_not_submit(self):
        # The login form carries "check your ID or password" even with nothing
        # submitted - it is a diagnostic string, not a verdict.
        code, direct = self._run_login(
            ("no-window", "아이디 또는 패스워드를 확인하세요."))
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED)

    def test_a_none_outcome_network_failure_does_not_submit_the_password(self):
        code, direct = self._run_login(None)
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED)

    def test_the_sso_page_failing_to_be_filled_does_not_submit_the_password(self):
        # A real SSO window opened but could not be completed - still not a
        # reason to spend an attempt on the password form.
        tab = {"id": "sso", "url": "https://stseu.secsso.net/adfs/ls/"}
        with patch.object(gmes_login, "complete_sso",
                          return_value=(False, "the SSO page could not be filled", False)):
            code, direct = self._run_login(tab)
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED)

    def test_the_password_path_runs_only_when_explicitly_allowed(self):
        code, direct = self._run_login(("no-window", ""), allow_password_login=True)
        direct.assert_called_once()

    def test_a_counting_refusal_stops_immediately_and_is_rejected(self):
        # The one signal that really does mean the credentials were refused.
        warning = {"found": True, "used": 1, "limit": 5,
                   "text": "아이디 또는 비밀번호가 일치하지 않습니다. (시도횟수1/5)"}
        code, direct = self._run_login(("no-window", ""), lockout=warning)
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.REJECTED,
                         "a counted refusal must be REJECTED so nothing retries it")

    def test_an_unclear_outcome_after_real_submission_is_never_retried(self):
        # HISTORY.md - external review of 1957ba9, finding #9: complete_sso()
        # actually dispatched the Login click this run, sign-in never
        # confirmed, and lockout_warning() found nothing recognisable either
        # - genuinely unknown, not "nothing was ever sent".
        with patch.object(gmes_login, "complete_sso",
                          return_value=(True, "submitted", True)):
            code, direct = self._run_login({"id": "sso", "url": "https://stseu.secsso.net/adfs/ls/"})
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.UNKNOWN_AFTER_SUBMIT)

        with patch.object(core.gmes_login, "main", return_value=gmes_login.UNKNOWN_AFTER_SUBMIT) as m:
            self.assertFalse(core.sign_in(attempts=3))
        m.assert_called_once()   # never retried, exactly like REJECTED

    def test_an_unsubmitted_outcome_is_still_ordinary_failed(self):
        # The new UNKNOWN_AFTER_SUBMIT branch must not swallow the ordinary
        # "nothing was ever sent" case into itself.
        with patch.object(gmes_login, "complete_sso",
                          return_value=(False, "the SSO page could not be filled", False)):
            code, direct = self._run_login({"id": "sso", "url": "https://stseu.secsso.net/adfs/ls/"})
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED)


class SsoWindowOwnership(unittest.TestCase):
    """HISTORY.md - external review of 1957ba9, finding #8: a stale Samsung
    SSO popup left open by an earlier, abandoned attempt must never be
    mistaken for the window THIS run's own click just opened - the exact
    leftover-popup shape `prune_duplicate_gmes_tabs()` already exists to
    clean up on the G-MES side (Phase 76.4), now closed on the SSO side."""

    STALE = {"id": "stale", "url": "https://stseu.secsso.net/adfs/ls/?old=1"}
    FRESH = {"id": "fresh", "url": "https://stseu.secsso.net/adfs/ls/?new=1"}

    def test_a_stale_window_open_before_the_click_is_never_picked(self):
        with patch.object(gmes_login, "list_windows", return_value=[self.STALE]):
            tab, ambiguous = gmes_login.find_new_sso_window({self.STALE["id"]})
        self.assertIsNone(tab)
        self.assertEqual(ambiguous, 0)

    def test_the_window_that_appeared_after_the_click_is_picked(self):
        with patch.object(gmes_login, "list_windows",
                          return_value=[self.STALE, self.FRESH]):
            tab, ambiguous = gmes_login.find_new_sso_window({self.STALE["id"]})
        self.assertEqual(tab, self.FRESH)
        self.assertEqual(ambiguous, 0)

    def test_two_new_windows_at_once_refuse_to_guess(self):
        other_fresh = {"id": "fresh2", "url": "https://stseu.secsso.net/adfs/ls/?new=2"}
        with patch.object(gmes_login, "list_windows",
                          return_value=[self.FRESH, other_fresh]):
            tab, ambiguous = gmes_login.find_new_sso_window(set())
        self.assertIsNone(tab)
        self.assertEqual(ambiguous, 2)

    def test_wait_for_sso_window_reports_ambiguous_rather_than_a_tab(self):
        other_fresh = {"id": "fresh2", "url": "https://stseu.secsso.net/adfs/ls/?new=2"}
        with patch.object(gmes_login, "list_windows",
                          return_value=[self.FRESH, other_fresh]):
            result = gmes_login.wait_for_sso_window(set(), ws=None, max_wait=0.01)
        self.assertEqual(result, ("ambiguous", 2))

    def test_main_treats_ambiguous_sso_as_a_safe_transient_failure(self):
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes"), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(False, "")), \
             patch.object(gmes_login.gmes_credentials, "load",
                          return_value=("someone", "a-password")), \
             patch.object(gmes_login, "click_by_id", return_value={"found": True}), \
             patch.object(gmes_login, "list_windows", return_value=[]), \
             patch.object(gmes_login, "wait_for_sso_window",
                          return_value=("ambiguous", 2)), \
             patch.object(gmes_login.gmes_common, "screenshot_on_failure"), \
             patch.object(gmes_login.gmes_common, "close_popups_when_they_appear",
                          return_value=[]), \
             patch.object(gmes_login.gmes_common, "close_child_popups", return_value=[]), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs",
                          return_value=""), \
             patch.object(gmes_login, "time", _FakeClock()), \
             patch.object(gmes_login, "direct_login") as direct:
            code = gmes_login.main()
        direct.assert_not_called()
        self.assertEqual(code, gmes_login.FAILED,
                         "nothing was typed on either window - safe to retry")

    def test_complete_sso_reconnects_by_id_not_by_a_broad_sso_search(self):
        # Two SSO tabs open at once - the owned one and an unrelated
        # leftover. A reconnect after a dropped socket must still find the
        # owned one, never fall back to "whichever SSO tab exists".
        ws1, ws2 = Mock(), Mock()
        connects = iter([ws1, ws2])
        owned = {"id": "owned", "webSocketDebuggerUrl": "ws://owned"}
        leftover = {"id": "leftover", "webSocketDebuggerUrl": "ws://leftover"}
        with patch.object(gmes_login, "connect",
                          side_effect=lambda *a, **k: next(connects)) as connect, \
             patch.object(gmes_login, "evaluate",
                          side_effect=[RuntimeError("dropped"),
                                       {"user": True, "pw": True},
                                       {"found": True, "x": 1, "y": 1},
                                       {"text": ""}]), \
             patch.object(gmes_login, "set_value_by_id"), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect"), \
             patch.object(gmes_login, "list_windows",
                          return_value=[owned, leftover]), \
             patch.object(gmes_login.time, "sleep"):
            ok, detail, submitted = gmes_login.complete_sso(owned, "user", "pw")
        self.assertTrue(ok)
        self.assertTrue(submitted)
        # Both connect attempts were addressed at the OWNED websocket url,
        # never the leftover tab's - reconnect-by-id survived the dropped
        # socket without retargeting.
        urls = [call.args[0] for call in connect.call_args_list]
        self.assertEqual(urls, ["ws://owned", "ws://owned"])


class LockoutWarningDetection(unittest.TestCase):
    """Reading the counting modal that means an attempt was actually spent."""

    def _detect(self, payload):
        with patch.object(gmes_login, "evaluate", return_value=payload):
            return gmes_login.lockout_warning(Mock())

    def test_it_reads_the_counter_out_of_the_live_modal(self):
        found = self._detect({"found": True, "used": 1, "limit": 5,
                              "text": "(시도횟수1/5)"})
        self.assertTrue(found["found"])
        self.assertEqual((found["used"], found["limit"]), (1, 5))

    def test_a_clean_page_is_not_a_refusal(self):
        self.assertFalse(self._detect({"found": False})["found"])

    def test_a_read_failure_is_not_treated_as_a_refusal(self):
        # Failing to read the page must not invent a credential rejection -
        # that would stop a run for the wrong reason.
        with patch.object(gmes_login, "evaluate", side_effect=RuntimeError("socket gone")):
            self.assertFalse(gmes_login.lockout_warning(Mock())["found"])

    def test_the_snippet_names_the_markers_it_matches(self):
        for marker in ("시도횟수", "attempt", "restricted", "locked"):
            with self.subTest(marker=marker):
                self.assertIn(marker, gmes_login.JS_LOCKOUT_WARNING)


class ResultVerification(unittest.TestCase):
    def test_checks_every_result_row_not_a_small_sample(self):
        result = {
            "found": True,
            "columns": ["planYmd"],
            "rows": [{"planYmd": "20260909"}] * 8 + [{"planYmd": "20260908"}],
        }
        with patch.object(core, "read_rows", return_value=result) as read:
            seen, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "20260909")
        read.assert_called_once_with(None, "P1112WM00", "dsResult", limit=-1, path=None)
        self.assertEqual(seen, ["20260908", "20260909"])
        self.assertIn("not exactly", problem)

    def test_requires_an_expected_value(self):
        result = {"found": True, "columns": ["planYmd"], "rows": [{"planYmd": "20260909"}]}
        with patch.object(core, "read_rows", return_value=result):
            _, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "")
        self.assertIn("expected value", problem)


class VerifyDateRangeCheck(unittest.TestCase):
    """verify_rows() only ever compares every row to ONE expected value,
    which made it reject every genuinely correct MULTI-DAY query -
    confirmed live: a real 10-day range on P1112UM00 (6529 rows, all
    legitimately spanning the requested window) failed verification
    entirely, because --verify COLUMN with no explicit =VALUE had only
    date_from to compare against. verify_date_range() is the range-aware
    sibling that checks every row falls WITHIN the window instead."""

    def test_a_genuine_multi_day_range_is_accepted(self):
        result = {
            "found": True,
            "columns": ["creYmd"],
            "rows": [{"creYmd": d} for d in
                     ("20260901", "20260903", "20260905", "20260909", "20260910")],
        }
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_date_range(
                None, "P1112WM00", "dsResult", "creYmd", "20260901", "20260910")
        self.assertIsNone(problem)
        self.assertEqual(seen, ["20260901", "20260903", "20260905", "20260909", "20260910"])

    def test_a_value_outside_the_requested_window_is_caught(self):
        # The exact live-reproduced case: real rows genuinely outside the
        # requested window (a much older date mixed into the result) must
        # still be flagged, not accepted just because SOME rows are right.
        result = {
            "found": True,
            "columns": ["creYmd"],
            "rows": [{"creYmd": "20260905"}, {"creYmd": "20260303"}],
        }
        with patch.object(core, "read_rows", return_value=result):
            seen, problem = core.verify_date_range(
                None, "P1112WM00", "dsResult", "creYmd", "20260901", "20260910")
        self.assertIsNotNone(problem)
        self.assertIn("20260303", problem)

    def test_the_boundary_dates_themselves_are_inside_the_range(self):
        result = {"found": True, "columns": ["creYmd"],
                 "rows": [{"creYmd": "20260901"}, {"creYmd": "20260910"}]}
        with patch.object(core, "read_rows", return_value=result):
            _, problem = core.verify_date_range(
                None, "P1112WM00", "dsResult", "creYmd", "20260901", "20260910")
        self.assertIsNone(problem)


class AmbiguityAndDates(unittest.TestCase):
    def test_comparable_grids_require_an_explicit_choice(self):
        screen = _screen({"grids": [
            {"name": "grdMaster", "dataset": "dsMaster", "area": 400000, "visible": True},
            {"name": "grdDetail", "dataset": "dsDetail", "area": 300000, "visible": True},
        ]})
        with self.assertRaisesRegex(RuntimeError, "more than one plausible"):
            screen.grid()

    def test_one_date_field_is_written_once_for_one_day_request(self):
        field = {"column": "planYmd", "control": "mskPlanDate", "value": "",
                 "bound": True, "dataset": "dsFilter", "form": "P1112WF00.xfdl.js"}
        screen = _screen({"filters": [field]})
        screen.apply = Mock(return_value="20260909")
        written = screen.set_date_range("20260909", "20260909")
        self.assertEqual(written, [(field, "20260909")])
        screen.apply.assert_called_once_with(field, "20260909")

    def test_one_date_field_rejects_a_range(self):
        field = {"column": "planYmd", "control": "mskPlanDate", "value": "",
                 "bound": True, "dataset": "dsFilter", "form": "P1112WF00.xfdl.js"}
        with self.assertRaisesRegex(RuntimeError, "no from/to pair"):
            _screen({"filters": [field]}).set_date_range("20260908", "20260909")


class ExportAndBatchSafety(unittest.TestCase):
    def test_rejects_a_large_file_that_is_not_an_excel_or_drm_workbook(self):
        path = "report.xlsx"
        with patch.object(core.os.path, "isfile", return_value=True), \
             patch.object(core.os.path, "getsize", return_value=1400), \
             patch("builtins.open", mock_open(read_data=b"not a workbook")):
            with self.assertRaisesRegex(RuntimeError, "not an XLSX"):
                core.check_download(path)

    def test_accepts_a_zip_workbook_signature(self):
        path = "report.xlsx"
        with patch.object(core.os.path, "isfile", return_value=True), \
             patch.object(core.os.path, "getsize", return_value=604), \
             patch("builtins.open", mock_open(read_data=b"PK\x03\x04" + b"x" * 60)):
            self.assertGreater(core.check_download(path), 512)

    def test_batch_stops_after_a_failure_and_marks_later_work_not_run(self):
        specs = [{"screen_code": "A1000"}, {"screen_code": "B1000"}, {"screen_code": "C1000"}]
        with patch.object(core, "run_screen", side_effect=[{"screen": "A1000", "ok": True}, RuntimeError("bad")]), \
             patch.object(core.cdp_common, "screenshot_on_failure"), \
             patch.object(core.gmes_common, "screenshot_on_failure"):
            results = core.run_many(None, specs, log=lambda _message: None)
        self.assertEqual([item["screen"] for item in results], ["A1000", "B1000", "C1000"])
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[2]["error"], "not run because the previous screen left an unknown state")


class PopupAfterDownloadIsClosed(unittest.TestCase):
    """HISTORY.md Phase 82.10, live-caught mid-session while recording
    together with the project owner: G-MES follows a finished Excel
    download with its own "Notification: completed." popup on at least
    some screens (confirmed live on M3912UM00) - a SEPARATE dialog from
    the "Save to Excel" confirmation already handled, appearing only once
    the file has actually landed. Nothing closed it, and G-MES is fully
    modal while it is open: the very next screen this tool tried to open
    failed with "its tab could not be brought to the front" because the
    popup was still blocking the whole application. Confirmed as the root
    cause live: activate_screen() failed on the exact same target while
    the popup was open, and succeeded immediately once it was closed by
    hand - then again automatically once this fix was in place."""

    def test_the_trailing_notification_is_closed_once_the_file_lands(self):
        import shutil, tempfile
        target_dir = tempfile.mkdtemp(prefix="gmes-test-target-")
        staging_dir = tempfile.mkdtemp(prefix="gmes-test-staging-")
        try:
            def fake_sleep(_seconds):
                # First call: the file "arrives". Every call after: nothing
                # changes, letting the stability check (2 unchanged reads)
                # pass on real, on-disk file sizes.
                target = os.path.join(staging_dir, "Assign Range Status.xlsx")
                if not os.path.exists(target):
                    with open(target, "wb") as fh:
                        fh.write(b"PK\x03\x04" + b"x" * 100)

            with patch.object(core, "send"), \
                 patch.object(core, "evaluate", return_value={"found": True, "x": 1, "y": 1}), \
                 patch.object(core, "click_element_by_rect"), \
                 patch.object(core.gmes_common, "click_control", return_value=True), \
                 patch.object(core.gmes_common, "close_child_popups", return_value=[]) as close, \
                 patch.object(core.tempfile, "mkdtemp", return_value=staging_dir), \
                 patch.object(core.time, "sleep", side_effect=fake_sleep):
                result = core.download_excel(Mock(), target_dir, timeout=5)

            self.assertTrue(os.path.isfile(result))
            close.assert_called_once()
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)
            # download_excel() already removes its own staging dir; guard
            # against a failed run leaving it behind in a real temp folder.
            shutil.rmtree(staging_dir, ignore_errors=True)

    def test_the_popup_close_happens_after_the_file_is_confirmed_not_before(self):
        # Ordering matters: closing anything DURING the "Save to Excel"
        # step would cancel the export outright (this function's own
        # docstring already warns about exactly that). The close call must
        # only ever follow a successfully retrieved file.
        source = core.download_excel.__wrapped__ if hasattr(
            core.download_excel, "__wrapped__") else core.download_excel
        import inspect
        body = inspect.getsource(source)
        ok_click_at = body.index('text="OK"')
        close_popups_at = body.index("gmes_common.close_child_popups(ws)")
        self.assertLess(ok_click_at, close_popups_at)


class ExcelDialogPatience(unittest.TestCase):
    def test_the_ok_button_wait_is_generous_not_a_15_second_guess(self):
        # HISTORY.md Phase 82.13, live-caught recording Q2111UM00: two
        # consecutive real runs raised "the 'Save to Excel' dialog did not
        # offer an OK button" against a heavy 175-row/143-column export,
        # with Inquiry itself measurably slowing across the same attempts
        # (14.9s -> 22.7s -> 25.4s) - consistent with G-MES needing longer
        # under load to render the dialog too, not a missing button. A
        # third attempt, seconds later with no code change, found the
        # button within 1s. `click_control` already polls and returns the
        # instant the button appears (CLAUDE.md 3.1), so a generous cap
        # costs nothing in the fast case - checked as "wide enough", not
        # pinned to the exact number, so a future further increase does
        # not fail this test for the wrong reason.
        import inspect
        body = inspect.getsource(core.download_excel)
        m = re.search(r'click_control\(ws, text="OK", attempts=(\d+), delay=([\d.]+)\)', body)
        self.assertIsNotNone(m, "the OK-button click_control call must still exist")
        attempts, delay = int(m.group(1)), float(m.group(2))
        self.assertGreaterEqual(attempts * delay, 30,
                                "at least 30s of patience for the dialog to appear")


class LoggingSafety(unittest.TestCase):
    def test_secret_shaped_assignments_are_redacted_before_logging(self):
        line = 'password=do-not-store token: "also-do-not-store" ordinary=value'
        redacted = gmes_log._SECRET.sub(
            lambda match: f"{match.group(1)}{match.group(2)}***", line)
        self.assertNotIn("do-not-store", redacted)
        self.assertNotIn("also-do-not-store", redacted)
        self.assertIn("ordinary=value", redacted)


class GmesScreenshotTargeting(unittest.TestCase):
    """gmes_common.capture_screenshot must name the G-MES tab specifically,
    not fall back to cdp_common's "whichever page target is listed first" -
    that fallback silently photographed a leftover AD SSO popup instead of
    G-MES's own rejected login form (HISTORY.md Phase 56.4). No browser is
    launched in any of these; get_tabs is mocked to return canned tab lists."""

    GMES_TAB = {"type": "page", "id": "gmes1",
                "url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html",
                "webSocketDebuggerUrl": "ws://x/gmes1"}
    # Carries "seegmes4.sec.samsung.net" inside its own RelayState query
    # parameter - the exact collision gmes_tab()'s own docstring warns
    # about ("matching the whole URL for 'gmes' picked the ADFS sign-in tab
    # instead"). A naive substring match on the full URL would still be
    # fooled by this; host-only matching, which gmes_tab() already does,
    # is not.
    SSO_TAB = {"type": "page", "id": "sso1",
               "url": ("https://stseu.secsso.net/adfs/ls/?SAMLRequest=X&"
                       "RelayState=http%3A%2F%2Fseegmes4.sec.samsung.net%2Fmes4%2Fadsso%2Fadsso"),
               "webSocketDebuggerUrl": "ws://x/sso1"}

    def test_selects_the_gmes_tab_over_a_leftover_sso_popup(self):
        # The SSO popup listed BEFORE the real G-MES tab, exactly the
        # ordering that made cdp_common.capture_screenshot's pages[0]
        # fallback pick the wrong one live.
        with patch.object(gmes_common, "get_tabs", return_value=[self.SSO_TAB, self.GMES_TAB]), \
             patch.object(gmes_common.cdp_common, "capture_screenshot", return_value="saved.png") as inner:
            result = gmes_common.capture_screenshot("out.png")

        self.assertEqual(result, "saved.png")
        inner.assert_called_once()
        self.assertEqual(inner.call_args.kwargs["tab"], self.GMES_TAB)

    def test_sso_only_never_calls_generic_screenshot_fallback(self):
        with patch.object(gmes_common, "get_tabs", return_value=[self.SSO_TAB]), \
             patch.object(gmes_common.cdp_common, "capture_screenshot") as inner:
            self.assertIsNone(gmes_common.capture_screenshot("out.png"))
        inner.assert_not_called()

    def test_nerp_and_sso_without_gmes_never_capture(self):
        nerp = {"type": "page", "url": "https://nerps.sec.samsung.net/", "id": "n"}
        with patch.object(gmes_common, "get_tabs", return_value=[self.SSO_TAB, nerp]), \
             patch.object(gmes_common.cdp_common, "capture_screenshot") as inner:
            self.assertIsNone(gmes_common.capture_screenshot("out.png"))
        inner.assert_not_called()

    def test_a_closed_browser_returns_none_without_raising(self):
        # Strict resolution treats an unavailable CDP endpoint as no
        # verified G-MES tab. It must not ask the generic helper to guess.
        with patch.object(gmes_common, "strict_gmes_tab", return_value=None), \
             patch.object(gmes_common.cdp_common, "capture_screenshot") as inner:
            result = gmes_common.capture_screenshot("out.png")
        self.assertIsNone(result)
        inner.assert_not_called()

    def test_no_page_tabs_at_all_is_handled_like_the_existing_contract(self):
        with patch.object(gmes_common, "get_tabs", return_value=[]), \
             patch.object(gmes_common.cdp_common, "capture_screenshot") as inner:
            result = gmes_common.capture_screenshot("out.png")
        self.assertIsNone(result)
        inner.assert_not_called()

    def test_explicit_gmes_tab_is_passed_exactly(self):
        with patch.object(gmes_common.cdp_common, "capture_screenshot", return_value="saved.png") as inner:
            self.assertEqual(gmes_common.capture_screenshot("out.png", tab=self.GMES_TAB), "saved.png")
        self.assertEqual(inner.call_args.kwargs["tab"], self.GMES_TAB)

    def test_remaining_probe_tools_route_through_the_strict_wrapper(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("gmes_probe_suggest.py", "gmes_probe_search.py"):
            text = (root / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("gmes_common.capture_screenshot", text)
                self.assertNotIn("cdp_common.capture_screenshot", text)


class StrictGmesTabConnection(unittest.TestCase):
    """`gmes_common.gmes_tab()` - the tab `connect_gmes()` actually drives,
    not just the one screenshots target.

    Found by external review (HISTORY.md Phase 79): after its wait deadline,
    `gmes_tab()` used to fall back to "whichever non-SSO tab happens to
    exist" - about:blank, a leftover page from a previous run, anything -
    rather than failing. That handed the real driving connection a live
    websocket to a page that was not G-MES at all, so every downstream
    operation (filters, Inquiry, export) ran against the wrong page. Every
    caller already treats `None` as the correctly actionable failure; the
    fallback tab was never actually safer than raising."""

    GMES_TAB = {"type": "page", "id": "gmes1",
                "url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html",
                "webSocketDebuggerUrl": "ws://x/gmes1"}
    SSO_TAB = {"type": "page", "id": "sso1",
               "url": ("https://stseu.secsso.net/adfs/ls/?SAMLRequest=X&"
                       "RelayState=http%3A%2F%2Fseegmes4.sec.samsung.net%2Fmes4%2Fadsso%2Fadsso"),
               "webSocketDebuggerUrl": "ws://x/sso1"}
    BLANK_TAB = {"type": "page", "id": "blank1", "url": "chrome://newtab/",
                "webSocketDebuggerUrl": "ws://x/blank1"}

    def test_finds_the_real_gmes_tab_immediately(self):
        with patch.object(gmes_common, "get_tabs",
                          return_value=[self.SSO_TAB, self.GMES_TAB]):
            self.assertEqual(gmes_common.gmes_tab(), self.GMES_TAB)

    def test_an_sso_tab_carrying_the_gmes_host_in_its_relaystate_is_excluded(self):
        with patch.object(gmes_common, "get_tabs", return_value=[self.SSO_TAB]), \
             patch.object(gmes_common.time, "sleep"):
            self.assertIsNone(gmes_common.gmes_tab(wait=0.01))

    def test_a_leftover_blank_or_unrelated_tab_is_never_returned(self):
        # The exact bug: only a blank/unrelated tab exists, no G-MES tab at
        # all. The old code fell back to BLANK_TAB here instead of failing.
        with patch.object(gmes_common, "get_tabs", return_value=[self.BLANK_TAB]), \
             patch.object(gmes_common.time, "sleep"):
            self.assertIsNone(gmes_common.gmes_tab(wait=0.01))

    def test_no_tabs_at_all_returns_none_not_a_crash(self):
        with patch.object(gmes_common, "get_tabs", return_value=[]), \
             patch.object(gmes_common.time, "sleep"):
            self.assertIsNone(gmes_common.gmes_tab(wait=0.01))

    def test_an_unreachable_browser_raises_an_actionable_error(self):
        with patch.object(gmes_common, "get_tabs", side_effect=OSError("refused")):
            with self.assertRaises(RuntimeError) as ctx:
                gmes_common.gmes_tab(wait=0.01)
        self.assertIn("python gmes_login.py", str(ctx.exception))

    def test_a_tab_that_appears_partway_through_the_wait_is_still_found(self):
        # A real poll, not a one-shot check: the G-MES tab is not there on
        # the first look (still on about:blank / mid-navigation) but is
        # found before the deadline.
        calls = {"n": 0}

        def get_tabs(port=None):
            calls["n"] += 1
            return [self.BLANK_TAB] if calls["n"] < 3 else [self.GMES_TAB]

        with patch.object(gmes_common, "get_tabs", side_effect=get_tabs), \
             patch.object(gmes_common.time, "sleep"):
            self.assertEqual(gmes_common.gmes_tab(wait=5), self.GMES_TAB)
        self.assertGreaterEqual(calls["n"], 3)

    def test_connect_gmes_raises_a_clear_message_instead_of_attaching_to_the_wrong_page(self):
        # The actual regression this phase closes: connect_gmes() is what
        # every driving entrance calls to attach for real work.
        with patch.object(gmes_common, "get_tabs", return_value=[self.BLANK_TAB]), \
             patch.object(gmes_common, "time") as fake_time:
            fake_time.time.side_effect = [0, 100]   # first check, then past any deadline
            with self.assertRaises(RuntimeError) as ctx:
                gmes_common.connect_gmes(port=1234, attempts=1)
        self.assertIn("No G-MES tab is open", str(ctx.exception))

    def test_the_probe_tool_already_handles_none_without_crashing(self):
        # gmes_sso_diagnose.py checks `if tab is None` / `if fresh_tab is not
        # None` at both call sites - confirms the tightened contract needs no
        # change there.
        root = Path(__file__).resolve().parents[1]
        text = (root / "gmes_sso_diagnose.py").read_text(encoding="utf-8")
        self.assertIn("if tab is None", text)
        self.assertIn("if fresh_tab is not None", text)


class NoFixedSleeps(unittest.TestCase):
    """HISTORY.md Open Item 27 / Phase 79.5: `complete_sso()` and
    `open_gmes()` each had a genuine fixed-duration `time.sleep()` with no
    poll - a direct instance of the anti-pattern CLAUDE.md 3.1 names by
    example. Replaced with real polls that exit as soon as the thing they
    are waiting for is observed, on the same or a more generous cap."""

    def test_no_bare_time_sleep_with_a_literal_remains_in_either_function(self):
        # Structural guard against the exact regression, read from source
        # rather than trusted from the diff. Checks for the two EXACT
        # literals that were removed, not "no time.sleep() call at all" -
        # complete_sso()'s form-ready wait loop has always had a legitimate
        # poll-interval time.sleep(1) inside a real loop with its own exit
        # condition (CLAUDE.md 3.1's own "acceptable only as the interval
        # inside a poll"), and the new SSO-error poll added here has its own
        # time.sleep(0.3) for exactly that reason - a blanket ban on any
        # numeric time.sleep() would incorrectly flag both.
        import inspect
        complete_sso_source = inspect.getsource(gmes_login.complete_sso)
        open_gmes_source = inspect.getsource(gmes_login.open_gmes)
        self.assertNotIn("time.sleep(3)", complete_sso_source)
        self.assertNotIn("time.sleep(2)", open_gmes_source)

    def test_complete_sso_exits_immediately_once_the_window_closes(self):
        # The fast path: a successful sign-in redirects the window away
        # almost immediately, so this must not wait out the full cap.
        #
        # evaluate() repeats {"text": ""} forever rather than a short list -
        # a short list exhausting mid-poll raises StopIteration, which the
        # loop's own `except Exception: break` catches, making the loop stop
        # for the WRONG reason and hiding whether the owned window being gone
        # is actually what ends it. Found by sabotaging the real check and
        # watching this assertion not fail with the short-list version.
        #
        # `list_windows` is what `owned_window_gone()`/`attach()` actually
        # call now (Phase 81.3: reconnect and the closed-check are scoped to
        # THIS run's own window id, not "any SSO tab anywhere") - an empty
        # list means the owned id is nowhere to be found, i.e. gone.
        import itertools
        tab = {"id": "sso", "webSocketDebuggerUrl": "ws://sso"}
        ws = Mock()
        sleeps = []
        responses = itertools.chain(
            [{"user": True, "pw": True},          # form ready
             {"found": True, "x": 1, "y": 1}],    # submit button
            itertools.repeat({"text": ""}))       # error poll, forever
        with patch.object(gmes_login, "connect", return_value=ws), \
             patch.object(gmes_login, "evaluate", side_effect=lambda *a: next(responses)), \
             patch.object(gmes_login, "set_value_by_id"), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect"), \
             patch.object(gmes_login, "list_windows", return_value=[]), \
             patch.object(gmes_login.time, "sleep", side_effect=sleeps.append):
            ok, detail, submitted = gmes_login.complete_sso(tab, "user", "pw")
        self.assertTrue(ok)
        self.assertEqual(detail, "submitted")
        self.assertTrue(submitted)
        # One sleep from the form-ready wait loop's single iteration; NONE
        # from the post-submit poll, because the owned window already
        # reported gone on the first check.
        self.assertLessEqual(len(sleeps), 1)

    def test_complete_sso_catches_a_bad_password_within_the_cap(self):
        tab = {"id": "sso", "webSocketDebuggerUrl": "ws://sso"}
        ws = Mock()
        with patch.object(gmes_login, "connect", return_value=ws), \
             patch.object(gmes_login, "evaluate",
                          side_effect=[{"user": True, "pw": True},
                                       {"found": True, "x": 1, "y": 1},
                                       {"text": "check your ID or password"}]), \
             patch.object(gmes_login, "set_value_by_id"), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect"), \
             patch.object(gmes_login, "list_windows", return_value=[tab]), \
             patch.object(gmes_login.time, "sleep"):
            ok, detail, submitted = gmes_login.complete_sso(tab, "user", "pw")
        self.assertFalse(ok)
        self.assertIn("check your ID or password", detail)
        self.assertTrue(submitted)   # the click was dispatched before the rejection

    def test_complete_sso_does_not_busy_spin_past_its_cap(self):
        # If neither condition is ever observed, the loop must still exit -
        # a real cap, not an infinite poll.
        tab = {"id": "sso", "webSocketDebuggerUrl": "ws://sso"}
        ws = Mock()
        clock = _FakeClock()
        with patch.object(gmes_login, "connect", return_value=ws), \
             patch.object(gmes_login, "evaluate",
                          side_effect=[{"user": True, "pw": True},
                                       {"found": True, "x": 1, "y": 1}]
                          + [{"text": ""}] * 100), \
             patch.object(gmes_login, "set_value_by_id"), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect"), \
             patch.object(gmes_login, "list_windows", return_value=[tab]), \
             patch.object(gmes_login, "time", clock):
            ok, detail, submitted = gmes_login.complete_sso(tab, "user", "pw")
        self.assertTrue(ok)
        self.assertEqual(detail, "submitted")
        self.assertTrue(submitted)

    def test_open_gmes_needs_no_sleep_when_the_tab_is_already_there(self):
        with patch.object(gmes_login.gmes_common, "gmes_tab",
                          return_value={"id": "t"}) as tab, \
             patch.object(gmes_login.cdp_common, "navigate_page") as nav:
            result = gmes_login.open_gmes()
        self.assertEqual(result, {"id": "t"})
        nav.assert_not_called()
        tab.assert_called_once()

    def test_open_gmes_navigates_then_finds_the_tab_with_no_sleep_in_between(self):
        calls = iter([None, {"id": "gmes"}])
        with patch.object(gmes_login.gmes_common, "gmes_tab",
                          side_effect=lambda: next(calls)), \
             patch.object(gmes_login.cdp_common, "navigate_page") as nav, \
             patch.object(gmes_login.time, "sleep") as sleep:
            result = gmes_login.open_gmes()
        self.assertEqual(result, {"id": "gmes"})
        nav.assert_called_once()
        sleep.assert_not_called()

    def test_open_gmes_retries_once_after_a_transient_post_navigation_failure(self):
        # navigate_page() can tear the CDP target down mid-navigation;
        # gmes_tab() raises immediately on the first get_tabs() failure
        # rather than retrying itself, so a single blip right after
        # navigating must be absorbed by retrying, not guessed around with
        # a delay.
        calls = iter([None, RuntimeError("Cannot reach the automation browser"),
                      {"id": "gmes"}])

        def gmes_tab():
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(gmes_login.gmes_common, "gmes_tab", side_effect=gmes_tab), \
             patch.object(gmes_login.cdp_common, "navigate_page"):
            result = gmes_login.open_gmes()
        self.assertEqual(result, {"id": "gmes"})

    def test_open_gmes_still_raises_a_clear_error_if_truly_unreachable(self):
        with patch.object(gmes_login.gmes_common, "gmes_tab",
                          side_effect=[None, RuntimeError("gone"), RuntimeError("gone")]), \
             patch.object(gmes_login.cdp_common, "navigate_page"):
            with self.assertRaises(RuntimeError):
                gmes_login.open_gmes()


class PreflightCheck(unittest.TestCase):
    """`gmes_preflight.py` - found by external review (HISTORY.md Phase 79):
    `GMES_Workflow.bat`'s only check was `where python`, so a machine
    missing websocket-client, missing both browsers, or unable to write its
    own runtime directory discovered that only after the first real sign-in
    attempt - the expensive failure this whole project exists to avoid
    spending unnecessarily. Every check here is read-only and none launches
    a browser (that IS the expensive step this exists to fail before)."""

    def test_a_fully_ready_machine_passes_every_check(self):
        with patch.object(gmes_preflight.sys, "version_info",
                          gmes_preflight.MIN_PYTHON + (0,)), \
             patch.object(gmes_preflight.importlib.util, "find_spec",
                          return_value=object()), \
             patch.object(gmes_preflight, "check_browser",
                          return_value=(True, "Chrome (C:\\fake\\chrome.exe)")), \
             patch.object(gmes_preflight, "check_runtime_directory",
                          return_value=(True, "C:\\fake\\GMES_Automation")):
            self.assertTrue(gmes_preflight.run(verbose=False))

    def test_an_old_python_fails_the_version_check(self):
        with patch.object(gmes_preflight.sys, "version_info", (3, 6, 0)):
            ok, detail = gmes_preflight.check_python_version()
        self.assertFalse(ok)
        self.assertIn("3.6.0", detail)

    def test_websocket_client_missing_is_reported_with_the_install_command(self):
        with patch.object(gmes_preflight.importlib.util, "find_spec", return_value=None):
            ok, detail = gmes_preflight.check_websocket_client()
        self.assertFalse(ok)
        self.assertIn("pip install", detail)

    def test_neither_browser_installed_fails_with_an_actionable_message(self):
        import gmes_browsers as real_gb
        with patch.object(real_gb, "find_executable", return_value=None):
            ok, detail = gmes_preflight.check_browser()
        self.assertFalse(ok)
        self.assertIn("CHROME_PATH", detail)
        self.assertIn("EDGE_PATH", detail)

    def test_an_unwritable_runtime_directory_fails_clearly(self):
        import gmes_browsers as real_gb
        with patch.object(real_gb, "AUTOMATION_ROOT", "Z:\\definitely\\not\\writable"), \
             patch.object(gmes_preflight.os, "makedirs",
                          side_effect=OSError("access denied")):
            ok, detail = gmes_preflight.check_runtime_directory()
        self.assertFalse(ok)
        self.assertIn("access denied", detail)

    def test_one_failing_check_does_not_hide_the_others(self):
        # Every check still runs and reports even after an earlier one
        # fails - fixing one problem must not require running this five
        # times to discover the next.
        calls = []

        def tracked(name):
            def check():
                calls.append(name)
                return False, "failed"
            return check

        with patch.object(gmes_preflight, "CHECKS",
                          tuple((n, tracked(n)) for n in ("a", "b", "c"))):
            ok = gmes_preflight.run(verbose=False)
        self.assertFalse(ok)
        self.assertEqual(calls, ["a", "b", "c"])

    def test_a_check_that_raises_is_caught_not_left_to_crash_the_launcher(self):
        def exploding():
            raise RuntimeError("unexpected")

        with patch.object(gmes_preflight, "CHECKS", (("exploding", exploding),)):
            self.assertFalse(gmes_preflight.run(verbose=False))

    def test_main_returns_zero_only_when_every_check_passed(self):
        with patch.object(gmes_preflight, "run", return_value=True):
            self.assertEqual(gmes_preflight.main(), 0)
        with patch.object(gmes_preflight, "run", return_value=False):
            self.assertEqual(gmes_preflight.main(), 1)

    def test_it_never_launches_a_browser_or_imports_cdp_common(self):
        # The expensive step this tool exists to fail BEFORE, not repeat.
        root = Path(__file__).resolve().parents[1]
        source = (root / "gmes_preflight.py").read_text(encoding="utf-8")
        for forbidden in ("cdp_common", "launch_automation_chrome", "connect_gmes"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_launcher_runs_it_and_stops_on_failure(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "GMES_Workflow.bat").read_text(encoding="utf-8")
        self.assertIn("python gmes_preflight.py", text)
        # The preflight call must appear before either real entrance runs.
        # Matched on the actual invocation line, not a bare filename -
        # "gmes_report.py" also appears in the header comment describing
        # what the argument-bearing branch does, which sits BEFORE the
        # preflight call and would give a false pass/fail either way.
        preflight_pos = text.index("python gmes_preflight.py")
        workflow_pos = text.index("python run_gmes_workflow.py")
        report_pos = text.index("python gmes_report.py run")
        self.assertLess(preflight_pos, workflow_pos)
        self.assertLess(preflight_pos, report_pos)


class LoginPageDefaultsToEnglish(unittest.TestCase):
    """Requested directly by the project owner, with a screenshot of the
    Korean login form: the tool should switch it to English every time.

    Live-verified before this was written (HISTORY.md Phase 77): clicking the
    real toggle via the project's own real-mouse dispatch immediately
    re-renders every visible label ('아이디' -> 'Remember ID', '로그인' ->
    'Login', 'AD SSO 로그인' -> 'AD SSO Login'), fires ZERO network requests
    (captured via CDP's Network domain over 3s), and does not survive a
    reload. So this must run on every fresh login form, must never be treated
    as one-time state, and must never be mistaken for the separate, unrelated,
    account-side `gvLanguage` setting that the signed-in application actually
    uses (Phase 76.5) - that one is still not touched anywhere."""

    def test_already_english_is_left_alone(self):
        with patch.object(gmes_login, "evaluate",
                          return_value={"found": True, "ambiguous": False, "english": True}), \
             patch.object(gmes_login, "click_by_id") as click:
            result = gmes_login.ensure_login_language_english(ws=None)
        self.assertEqual(result, "already English")
        click.assert_not_called()

    def test_korean_is_switched_with_exactly_one_click(self):
        checks = iter([
            {"found": True, "ambiguous": False, "english": False},   # before
            {"found": True, "ambiguous": False, "english": True},    # after - confirmed
        ])
        with patch.object(gmes_login, "evaluate",
                          side_effect=lambda _ws, _js: next(checks)), \
             patch.object(gmes_login, "click_by_id", return_value={"found": True}) as click, \
             patch.object(gmes_login, "time", _FakeClock()):
            result = gmes_login.ensure_login_language_english(ws=None)
        self.assertEqual(result, "switched to English")
        # attempts=6, delay=0.5: a shorter budget than click_by_id's own
        # default, because by the time this runs the login form is already
        # confirmed rendered (Phase 77.3 review finding).
        click.assert_called_once_with(None, gmes_login.STA_ENG, attempts=6, delay=0.5)

    def test_no_toggle_on_the_page_is_not_an_error(self):
        # An already-signed-in session shows no login form at all.
        with patch.object(gmes_login, "evaluate", return_value={"found": False}), \
             patch.object(gmes_login, "click_by_id") as click:
            self.assertIsNone(gmes_login.ensure_login_language_english(ws=None))
        click.assert_not_called()

    def test_an_ambiguous_state_is_left_alone_not_guessed(self):
        # Neither toggle unambiguously selected (or both) - an unrecognized
        # state this project refuses to act on rather than guess through
        # (CLAUDE.md 3.9). A bare "does staEng lack the V2 suffix" check
        # cannot tell this apart from "English is selected"; requiring the
        # two controls to disagree is what makes the difference visible.
        with patch.object(gmes_login, "evaluate",
                          return_value={"found": True, "ambiguous": True}), \
             patch.object(gmes_login, "click_by_id") as click:
            self.assertIsNone(gmes_login.ensure_login_language_english(ws=None))
        click.assert_not_called()

    def test_a_click_that_never_confirms_is_reported_not_raised(self):
        # Cosmetic and non-fatal: every real control is addressed by id, never
        # by text (CLAUDE.md 3.3), so a stuck toggle must not abort sign-in.
        with patch.object(gmes_login, "evaluate",
                          return_value={"found": True, "ambiguous": False, "english": False}), \
             patch.object(gmes_login, "click_by_id", return_value={"found": True}), \
             patch.object(gmes_login, "time", _FakeClock()):
            result = gmes_login.ensure_login_language_english(ws=None, verify_wait=1)
        self.assertIn("could not confirm", result)

    def test_a_toggle_that_cannot_be_clicked_is_reported_not_raised(self):
        with patch.object(gmes_login, "evaluate",
                          return_value={"found": True, "ambiguous": False, "english": False}), \
             patch.object(gmes_login, "click_by_id", return_value=None):
            result = gmes_login.ensure_login_language_english(ws=None)
        self.assertIn("not found to click", result)

    def test_it_runs_on_every_call_to_main_not_just_the_first(self):
        # It does not persist across a reload, so main() must call it on
        # every 'login' state reached - a module-level "already handled this
        # process" flag would defeat the whole point and must not creep in.
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes", return_value={"id": "t"}), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(False, None)), \
             patch.object(gmes_login, "ensure_login_language_english",
                          return_value="switched to English") as switch, \
             patch.object(gmes_login.gmes_credentials, "load", return_value=(None, None)), \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs"):
            gmes_login.main()
            gmes_login.main()
        self.assertEqual(switch.call_count, 2)
        switch.assert_called_with(ws)

    def test_it_is_skipped_when_the_session_was_already_restored(self):
        # The common real case: state == "session" from the start, so there
        # is no login form to switch at all.
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes", return_value={"id": "t"}), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("session", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(True, "someone")), \
             patch.object(gmes_login, "ensure_login_language_english") as switch, \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs"), \
             patch.object(gmes_login.gmes_common, "close_child_popups", return_value={}), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login.gmes_common, "capture_screenshot",
                          return_value="shot.png"):
            gmes_login.main()
        switch.assert_not_called()

    def test_it_is_skipped_when_signed_in_arrives_during_the_login_state(self):
        # Isolates the OTHER half of `state == "login" and not signed_in`: a
        # login form was seen, but a fresh is_logged_in() check right
        # afterward says the session has since come up (a race, not the
        # common path - `wait_for_login_or_session()` and `is_logged_in()` are
        # two separate calls). There is no login form left to switch either
        # way, and the two conditions must be tested apart, not only together.
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes", return_value={"id": "t"}), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(True, "someone")), \
             patch.object(gmes_login, "ensure_login_language_english") as switch, \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs"), \
             patch.object(gmes_login.gmes_common, "close_child_popups", return_value={}), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login.gmes_common, "capture_screenshot",
                          return_value="shot.png"):
            gmes_login.main()
        switch.assert_not_called()

    def test_it_is_skipped_for_status_only(self):
        # --status only looks; it must never click anything (module docstring).
        ws = Mock()
        with patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(False, None)), \
             patch.object(gmes_login, "login_error", return_value=""), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login, "ensure_login_language_english") as switch:
            gmes_login.main(status_only=True)
        switch.assert_not_called()

    def _extract_lockout_markers(self):
        """Compile the REAL regex literals out of `gmes_login.JS_LOCKOUT_WARNING`,
        rather than re-declaring them - a copy would still pass after the
        source markers were deleted, which is exactly what made the first
        version of this test worthless (Phase 77.3 review finding)."""
        js = gmes_login.JS_LOCKOUT_WARNING
        body = re.search(r"MARKERS\s*=\s*\[(.*?)\];", js, re.S).group(1)
        compiled = []
        for token in body.split(","):
            token = token.strip()
            m = re.match(r"^/(.*)/([a-z]*)$", token, re.S)
            self.assertIsNotNone(m, f"could not parse marker literal: {token!r}")
            pattern, flags = m.group(1), m.group(2)
            compiled.append(re.compile(pattern, re.IGNORECASE if "i" in flags else 0))
        return compiled

    def test_a_real_english_refusal_is_still_caught(self):
        # Guessed English wording, never observed live (a real one would cost
        # a lockout attempt to see - HISTORY.md Phase 74). Tests the ACTUAL
        # compiled source, so deleting a marker fails this test.
        markers = self._extract_lockout_markers()
        english_text = ("ID or password does not match. Login is restricted "
                        "after 5 failed attempts. (attempt count 2/5)")
        self.assertTrue(any(m.search(english_text) for m in markers),
                        "no marker in JS_LOCKOUT_WARNING matched a plausible "
                        "English refusal")

    def test_an_unguessed_english_wording_is_still_caught_by_the_counter_shape(self):
        # The whole point of Phase 77.3's fix: even wording NONE of the
        # guessed English markers anticipate is still caught, because the
        # "(N/M)" counter shape does not depend on the surrounding language at
        # all.
        markers = self._extract_lockout_markers()
        unguessed_text = "Sign-in was refused. Your account status: (2/5)."
        self.assertTrue(any(m.search(unguessed_text) for m in markers),
                        "the structural counter marker did not match")

    def test_the_korean_wording_is_still_caught(self):
        markers = self._extract_lockout_markers()
        korean_text = "아이디 또는 비밀번호가 일치하지 않습니다. (시도횟수1/5)"
        self.assertTrue(any(m.search(korean_text) for m in markers))

    def test_an_unrelated_fraction_on_the_page_does_not_false_positive(self):
        # The structural marker is deliberately narrow - PARENTHESIZED - so an
        # unrelated "1 / 5" elsewhere (a step count, a page indicator) without
        # parentheses must not match it.
        markers = self._extract_lockout_markers()
        unrelated_text = "Step 1 / 5"
        self.assertFalse(any(m.search(unrelated_text) for m in markers))


class LoginPageSessionConflictPopup(unittest.TestCase):
    """HISTORY.md Phase 82.14, live-caught mid-session with the project
    owner: G-MES's own server-side session guard showed a "Currently being
    used by another PC or terminated abnormally" popup on the LOGIN page -
    before any credential is submitted, so a different popup family entirely
    from the post-signin Notice windows `close_child_popups()` already
    handles (those live under `mdiFrame`; this one lives under `loginFrame`).
    G-MES is fully modal while it is open, so the automated AD SSO click
    landed on nothing and `wait_for_sso_window()` reported "the Samsung SSO
    window never opened" - a confusing SYMPTOM of a popup neither the
    automation nor the person watching it immediately recognised as the real
    cause. Confirming it (its own "OK") is the same recovery step a person
    would take by hand to reclaim their own stale session - it carries no
    password and burns no attempt against the five-try lockout counter."""

    def test_the_popup_is_confirmed_when_present(self):
        with patch.object(gmes_login, "evaluate",
                          return_value={"found": True, "x": 10, "y": 20}), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect") as click:
            result = gmes_login.close_login_ip_check(ws=None)
        self.assertTrue(result)
        click.assert_called_once_with(None, 10, 20)

    def test_nothing_happens_when_the_popup_is_not_there(self):
        # The overwhelmingly common case - must be cheap and silent.
        with patch.object(gmes_login, "evaluate", return_value={"found": False}), \
             patch.object(gmes_login.cdp_common, "click_element_by_rect") as click:
            result = gmes_login.close_login_ip_check(ws=None)
        self.assertFalse(result)
        click.assert_not_called()

    def test_a_probe_failure_is_reported_not_raised(self):
        # Matches ensure_login_language_english()'s own discipline right
        # above it: a diagnostic probe failing must never abort sign-in.
        with patch.object(gmes_login, "evaluate", side_effect=RuntimeError("boom")):
            self.assertFalse(gmes_login.close_login_ip_check(ws=None))

    def test_main_checks_for_it_on_every_login_state_before_anything_else(self):
        # Everything downstream - the language toggle, the SSO click - is
        # behind this modal if it is open, so it must run FIRST, not after,
        # and on every fresh login form (Phase 77's "does not persist across
        # a reload" applies here too - it is a fresh popup instance each time).
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes", return_value={"id": "t"}), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("login", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(False, None)), \
             patch.object(gmes_login, "close_login_ip_check", return_value=True) as closer, \
             patch.object(gmes_login, "ensure_login_language_english",
                          return_value=None) as switch, \
             patch.object(gmes_login.gmes_credentials, "load", return_value=(None, None)), \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs"):
            gmes_login.main()
            gmes_login.main()
        self.assertEqual(closer.call_count, 2)
        closer.assert_called_with(ws)
        # Source-order check, not just "both got called": the popup check
        # must run before the language switch in the real function body.
        import inspect
        source = inspect.getsource(gmes_login.main)
        ip_check_at = source.index("close_login_ip_check(ws)")
        language_at = source.index("ensure_login_language_english(ws)")
        self.assertLess(ip_check_at, language_at)

    def test_it_is_skipped_when_already_signed_in(self):
        ws = Mock()
        with patch.object(gmes_login, "ensure_browser", return_value="started"), \
             patch.object(gmes_login, "open_gmes", return_value={"id": "t"}), \
             patch.object(gmes_login, "connect_gmes", return_value=ws), \
             patch.object(gmes_login, "wait_for_login_or_session",
                          return_value=("session", ws)), \
             patch.object(gmes_login, "is_logged_in", return_value=(True, "someone")), \
             patch.object(gmes_login, "close_login_ip_check") as closer, \
             patch.object(gmes_login.gmes_common, "prune_duplicate_gmes_tabs"), \
             patch.object(gmes_login.gmes_common, "close_child_popups", return_value={}), \
             patch.object(gmes_login.gmes_common, "find_child_popups",
                          return_value={"count": 0, "popups": []}), \
             patch.object(gmes_login.gmes_common, "capture_screenshot",
                          return_value="shot.png"):
            gmes_login.main()
        closer.assert_not_called()


class DailyProdPlanSafety(unittest.TestCase):
    """Found by external review (HISTORY.md Phase 78): the nightly job was a
    generic caller of gmes_core in most ways, but had quietly grown its own
    copies of two things that must never be reimplemented - the run lock and
    the credential-shaped column filter - and both copies were weaker than
    the shared one."""

    def test_the_run_lock_is_acquired_before_sign_in_is_ever_attempted(self):
        # The interactive front end and gmes_report.py both refuse to share
        # one Chrome/CDP session between two processes; this job had NO such
        # guard at all, so a scheduled run overlapping a manual one could
        # silently collide mid-query on the same screen.
        order = []
        with patch.object(gmes_daily_prodplan.core, "acquire_run_lock",
                          side_effect=lambda: order.append("lock")) as acquire, \
             patch.object(gmes_daily_prodplan.core, "sign_in",
                          side_effect=lambda: order.append("sign_in") or False), \
             patch.object(gmes_daily_prodplan.core, "release_run_lock") as release, \
             patch.object(sys, "argv", ["gmes_daily_prodplan.py"]):
            code = gmes_daily_prodplan.main()
        acquire.assert_called_once()
        release.assert_called_once()
        self.assertEqual(order, ["lock", "sign_in"])
        self.assertEqual(code, 1)   # sign-in was made to fail; nothing else ran

    def test_a_held_lock_refuses_the_run_and_touches_no_browser(self):
        with patch.object(gmes_daily_prodplan.core, "acquire_run_lock",
                          side_effect=core.RunLocked("lock held by pid 524")), \
             patch.object(gmes_daily_prodplan.core, "sign_in") as sign_in, \
             patch.object(gmes_daily_prodplan.core, "release_run_lock") as release, \
             patch.object(sys, "argv", ["gmes_daily_prodplan.py"]):
            code = gmes_daily_prodplan.main()
        sign_in.assert_not_called()
        # Never acquired, so there is nothing for this run to release - only
        # the run that actually holds it may release it.
        release.assert_not_called()
        self.assertEqual(code, 1)

    def test_the_lock_is_released_even_when_the_job_fails_after_sign_in(self):
        with patch.object(gmes_daily_prodplan.core, "acquire_run_lock"), \
             patch.object(gmes_daily_prodplan.core, "release_run_lock") as release, \
             patch.object(gmes_daily_prodplan.core, "sign_in", return_value=True), \
             patch.object(gmes_daily_prodplan, "connect_gmes",
                          side_effect=RuntimeError("no browser")), \
             patch.object(sys, "argv", ["gmes_daily_prodplan.py"]):
            with self.assertRaises(RuntimeError):
                gmes_daily_prodplan.main()
        release.assert_called_once()

    def test_the_csv_export_reuses_the_shared_sensitive_column_filter(self):
        # The daily job used to filter columns itself - `not c.startswith
        # ("_")` only - missing gmes_data.SENSITIVE_COLUMN entirely. A column
        # merely NAMED like a credential (refreshTokenId, CLAUDE.md 2.3's own
        # example) does not start with "_" and would have shipped in the CSV.
        ws = Mock()
        rows = [{"poNo": "PO1", "planQty": "10", "refreshTokenId": "eyJ.fake.jwt"}]
        with patch.object(gmes_daily_prodplan.gmes_data, "read_dataset",
                          return_value={"found": True, "rows": rows,
                                       "columns": ["poNo", "planQty", "refreshTokenId"]}), \
             patch.object(gmes_daily_prodplan.tempfile, "mkstemp") as mkstemp, \
             patch("builtins.open", mock_open()), \
             patch.object(gmes_daily_prodplan.os, "fdopen") as fdopen, \
             patch.object(gmes_daily_prodplan.os, "replace"), \
             patch.object(gmes_daily_prodplan.os, "makedirs"):
            mkstemp.return_value = (99, "/tmp/x.partial")
            written = {}

            class FakeWriter:
                def __init__(self, fh, fieldnames, extrasaction):
                    written["fieldnames"] = fieldnames
                def writeheader(self):
                    pass
                def writerows(self, rows):
                    written["rows"] = rows

            fdopen.return_value.__enter__ = lambda self: self
            fdopen.return_value.__exit__ = lambda *a: False
            with patch.object(gmes_daily_prodplan.csv, "DictWriter", FakeWriter):
                gmes_daily_prodplan.export_clean_data(ws, "/out", "stamp", "20260101")

        self.assertNotIn("refreshTokenId", written["fieldnames"])
        self.assertIn("poNo", written["fieldnames"])

    def test_the_shared_filter_is_actually_called_not_a_local_copy(self):
        # Proves this is THE shared function, not a look-alike reimplemented
        # locally - patching gmes_data's real one must change the outcome.
        ws = Mock()
        with patch.object(gmes_daily_prodplan.gmes_data, "read_dataset",
                          return_value={"found": True,
                                       "rows": [{"poNo": "PO1"}],
                                       "columns": ["poNo"]}), \
             patch.object(gmes_daily_prodplan.gmes_data, "redact_sensitive_columns",
                          return_value=(["poNo"], [])) as redact, \
             patch.object(gmes_daily_prodplan.tempfile, "mkstemp",
                          return_value=(99, "/tmp/x.partial")), \
             patch("builtins.open", mock_open()), \
             patch.object(gmes_daily_prodplan.os, "fdopen") as fdopen, \
             patch.object(gmes_daily_prodplan.os, "replace"), \
             patch.object(gmes_daily_prodplan.os, "makedirs"), \
             patch.object(gmes_daily_prodplan.csv, "DictWriter") as writer_cls:
            fdopen.return_value.__enter__ = lambda self: self
            fdopen.return_value.__exit__ = lambda *a: False
            writer_cls.return_value = Mock()
            gmes_daily_prodplan.export_clean_data(ws, "/out", "stamp", "20260101")
        redact.assert_called_once_with(["poNo"])


class DuplicateGmesTabPruning(unittest.TestCase):
    """One G-MES page per browser.

    Observed live: FOUR G-MES tabs open, three of them with no work screens at
    all. "AD SSO Login" opens ADFS with window.open(); on success that popup
    follows its own RelayState back to the G-MES host, so it stops being an SSO
    window and becomes a second full Nexacro application. Nothing closed it -
    the sign-in code only ever noticed a popup closing ITSELF - so every AD SSO
    sign-in left one behind (HISTORY.md Phase 76.4).

    They are not cosmetic: `gmes_tab()` takes whichever the browser lists
    first, so a run can attach to an empty duplicate while the screens it
    opened sit in another tab."""

    GMES = "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html"
    SSO = ("https://stseu.secsso.net/adfs/ls/?SAMLRequest=abc"
           "&RelayState=http%3A%2F%2Fseegmes4.sec.samsung.net%2Fmes4%2Fadsso")

    def tab(self, tab_id, url=None):
        return {"id": tab_id, "type": "page", "url": url or self.GMES,
                "webSocketDebuggerUrl": f"ws://{tab_id}"}

    def run_prune(self, tabs, screens=None, keep=None, closes_ok=True):
        """`screens` maps tab id -> how many work screens it has open."""
        screens = screens or {}
        remaining = list(tabs)
        closed = []

        def close_tab(target_id, port=None, timeout=5):
            closed.append(target_id)
            if closes_ok:
                remaining[:] = [t for t in remaining if t["id"] != target_id]
            return True

        listings = [list(tabs), remaining]

        def get_tabs(port=None, timeout=5):
            return listings[0] if len(listings) > 1 and listings.pop(0) else remaining

        with patch.object(gmes_common, "get_tabs", side_effect=lambda **_k: list(remaining)
                          if closed else list(tabs)), \
             patch.object(gmes_common.cdp_common, "close_tab", side_effect=close_tab), \
             patch.object(gmes_common, "_open_screen_count",
                          side_effect=lambda t: screens.get(t["id"], 0)):
            detail = gmes_common.prune_duplicate_gmes_tabs(keep=keep, log=None)
        return detail, closed, remaining

    def test_the_tab_with_work_screens_open_is_the_one_kept(self):
        # The run's own state lives there; closing it would be the bug.
        tabs = [self.tab("empty1"), self.tab("real"), self.tab("empty2")]
        _detail, closed, remaining = self.run_prune(tabs, screens={"real": 1})
        self.assertNotIn("real", closed)
        self.assertEqual(sorted(closed), ["empty1", "empty2"])
        self.assertEqual([t["id"] for t in remaining], ["real"])

    def test_a_single_tab_is_left_completely_alone(self):
        detail, closed, _r = self.run_prune([self.tab("only")])
        self.assertEqual(closed, [])
        self.assertEqual(detail, "")

    def test_a_failed_reverification_is_not_reported_as_a_clean_success(self):
        # Real bug, found by external review (HISTORY.md Phase 78): the
        # re-list that PROVES a close happened used to default to an empty
        # set on any exception, which made every closed id look "not still
        # there" and reported a full, verified-sounding success with zero
        # actual evidence - in precisely the one situation (a transient CDP
        # hiccup during re-verification) where the caller most needs to be
        # told the tool does not actually know what happened.
        tabs = [self.tab("keep"), self.tab("dup1"), self.tab("dup2")]
        calls = {"n": 0}

        def get_tabs(port=None, timeout=5):
            calls["n"] += 1
            if calls["n"] == 1:
                return list(tabs)          # the initial discovery
            raise ConnectionError("browser hung up")   # the re-verification

        with patch.object(gmes_common, "get_tabs", side_effect=get_tabs), \
             patch.object(gmes_common.cdp_common, "close_tab", return_value=True), \
             patch.object(gmes_common, "_open_screen_count",
                          side_effect=lambda t: 1 if t["id"] == "keep" else 0):
            detail = gmes_common.prune_duplicate_gmes_tabs(log=None)

        self.assertNotIn("closed 2 duplicate", detail,
                         "reported success without any evidence a close worked")
        self.assertIn("could not verify", detail)
        self.assertIn("requested closing", detail)

    def test_no_tabs_at_all_is_not_an_error(self):
        detail, closed, _r = self.run_prune([])
        self.assertEqual(closed, [])
        self.assertEqual(detail, "")

    def test_an_sso_tab_mid_flight_is_never_touched(self):
        # Closing the ADFS window while sign-in is using it would break the
        # very flow this cleanup exists because of.
        tabs = [self.tab("gmes"), self.tab("sso", url=self.SSO)]
        _detail, closed, _r = self.run_prune(tabs)
        self.assertEqual(closed, [], "an SSO tab was closed")

    def test_a_named_keeper_wins_over_the_screen_count(self):
        tabs = [self.tab("mine"), self.tab("other")]
        _detail, closed, _r = self.run_prune(tabs, screens={"other": 5},
                                             keep="mine")
        self.assertEqual(closed, ["other"])

    def test_all_empty_still_leaves_exactly_one(self):
        tabs = [self.tab("a"), self.tab("b"), self.tab("c")]
        _detail, closed, remaining = self.run_prune(tabs)
        self.assertEqual(len(closed), 2)
        self.assertEqual(len(remaining), 1)

    def test_a_tab_that_refuses_to_close_is_reported_not_claimed(self):
        # "DevTools accepted it" is not "the tab has gone" - the same
        # distinction the popup closer needed (GMES_SKILL.md #48).
        tabs = [self.tab("keep"), self.tab("stuck")]
        detail, closed, _r = self.run_prune(tabs, screens={"keep": 1},
                                            closes_ok=False)
        self.assertEqual(closed, ["stuck"])
        self.assertIn("would not close", detail)
        self.assertNotIn("closed 1", detail)

    def test_an_unreachable_browser_is_silent_rather_than_fatal(self):
        with patch.object(gmes_common, "get_tabs", side_effect=OSError("gone")):
            self.assertEqual(
                gmes_common.prune_duplicate_gmes_tabs(log=None), "")

    def test_it_never_closes_the_browser_itself(self):
        # CLAUDE.md 2.6: tabs are closed, sessions are not ended, and nothing
        # anywhere in this path may reach for taskkill.
        source = Path(gmes_common.__file__).read_text(encoding="utf-8")
        self.assertNotIn("taskkill", source)
        block = source.split("def prune_duplicate_gmes_tabs")[1].split("\ndef ")[0]
        self.assertNotIn("close_browser", block)


class GmesInspectionScreenshots(unittest.TestCase):
    def test_each_inspected_tab_is_the_exact_screenshot_target(self):
        first = {"type": "page", "id": "sso", "title": "SSO",
                 "url": "https://login.secsso.net/", "webSocketDebuggerUrl": "ws://first"}
        second = {"type": "page", "id": "nerp", "title": "N-ERP",
                  "url": "https://nerps.sec.samsung.net/", "webSocketDebuggerUrl": "ws://second"}
        sockets = [Mock(), Mock()]
        with patch.object(gmes_inspect, "get_tabs", return_value=[first, second]), \
             patch.object(gmes_inspect, "connect", side_effect=sockets), \
             patch.object(gmes_inspect.gmes_common, "screen_report", return_value={}), \
             patch.object(gmes_inspect.gmes_common, "print_report"), \
             patch.object(gmes_inspect.cdp_common, "capture_screenshot", side_effect=["one.png", "two.png"]) as capture:
            self.assertEqual(gmes_inspect.main(shots=True), 0)

        self.assertEqual(capture.call_args_list[0].args, ("gmes_window_1.png",))
        self.assertIs(capture.call_args_list[0].kwargs["tab"], first)
        self.assertEqual(capture.call_args_list[1].args, ("gmes_window_2.png",))
        self.assertIs(capture.call_args_list[1].kwargs["tab"], second)
        self.assertTrue(all(socket.close.called for socket in sockets))


class PopupFallbackClose(unittest.TestCase):
    """A live sign-in on 2026-09-13 hit a Notice popup (`S9502UP01`) whose
    close button reported a real on-screen position but did not respond to
    clicks there - `close_child_popups` reported it "closed" and moved on
    while the popup was still covering the screen. `fallback_close_popup`
    (which calls the popup's own `_on_closebutton_click()` instead of
    clicking screen coordinates) was proven live to close it. These tests
    cover the orchestration around that call: it must only be tried after
    clicking is confirmed not to be working, and a popup that survives even
    the fallback must be reported as still present, not silently dropped."""

    STUCK = {"count": 1, "popups": [
        {"name": "S9502UP01", "id": "btn1", "bar_id": "mainframe...공지사항.titlebar",
         "x": 10, "y": 10},
    ]}
    GONE = {"count": 0, "popups": []}

    def test_falls_back_to_the_close_handler_once_clicking_stalls(self):
        # Clicking never reduces the count for two rounds running; the
        # fallback then succeeds and the popup is confirmed gone.
        with patch.object(gmes_common, "find_child_popups",
                           side_effect=[self.STUCK, self.STUCK, self.STUCK,
                                        self.STUCK, self.GONE, self.GONE]), \
             patch.object(gmes_common, "click_element_by_rect"), \
             patch.object(gmes_common, "fallback_close_popup", return_value=True) as fallback, \
             patch("time.sleep"):
            closed = gmes_common.close_child_popups(None)

        fallback.assert_called_once_with(None, "mainframe...공지사항.titlebar")
        self.assertIn("S9502UP01", closed)

    def test_a_popup_the_fallback_also_cannot_close_is_not_reported_closed(self):
        with patch.object(gmes_common, "find_child_popups",
                           return_value=self.STUCK), \
             patch.object(gmes_common, "click_element_by_rect"), \
             patch.object(gmes_common, "fallback_close_popup", return_value=False), \
             patch("time.sleep"):
            gmes_common.close_child_popups(None)
            left = gmes_common.find_child_popups(None)

        self.assertEqual(left["count"], 1)

    def test_close_popups_when_they_appear_also_uses_the_fallback(self):
        with patch.object(gmes_common, "find_child_popups",
                           side_effect=[self.STUCK, self.STUCK, self.STUCK,
                                        self.STUCK, self.GONE, self.GONE]), \
             patch.object(gmes_common, "click_element_by_rect"), \
             patch.object(gmes_common, "fallback_close_popup", return_value=True) as fallback, \
             patch("time.sleep"):
            closed = gmes_common.close_popups_when_they_appear(
                None, appear_wait=5, quiet_rounds=1)

        fallback.assert_called_once_with(None, "mainframe...공지사항.titlebar")
        self.assertIn("S9502UP01", closed)


class WorkFrameCloseFallback(unittest.TestCase):
    """A real open "Production Plan by Order(Line)" tab, tested live
    (2026-09-13), had no separate DOM close control at all - its tab bar
    element's only child was a text label. `Screen.close()` reported "the
    tab has no close control" and left the tab open on every single run,
    which is very likely what Phase 58.2 actually saw (screens quietly
    accumulating behind later commands). `gfnCloseWorkFarme` - G-MES's own
    close-tab handler, found by dumping the tab bar's method list live -
    reduces to one call needing only the win_id, already in hand:
    `nexacro.getApplication().gvMdiFrame.form.fnRemoveForm(winId)`, wired up
    here as `close_work_frame()`. Confirmed live: it closed the real tab
    the DOM search could not even find a button for."""

    STILL_OPEN = {"rows": [{"winId": "winX"}]}
    GONE = {"rows": []}

    def _screen(self):
        return core.Screen(None, "P1112UM00", {"winId": "winX", "menuId": "PPM0219"}, {})

    def test_falls_back_when_there_is_no_close_control_at_all(self):
        # This is the exact shape confirmed live: JS_TAB_CLOSE_TARGET finds
        # nothing to click at all.
        def fake_evaluate(ws, js, *a, **kw):
            if "fnRemoveForm" in js:
                return {"ok": True}
            return {"found": False, "reason": "the tab has no close control"}

        with patch.object(core, "evaluate", side_effect=fake_evaluate), \
             patch.object(core, "click_element_by_rect") as click, \
             patch.object(core.gmes_open_screen, "open_screens", return_value=self.GONE):
            ok, detail = self._screen().close(timeout=5)

        click.assert_not_called()
        self.assertTrue(ok)
        self.assertIn("direct", detail)

    def test_falls_back_when_a_found_close_button_does_not_actually_close_it(self):
        # A close control IS found and clicked - exactly like the popup's
        # close button (gotcha #48) - but it does not do anything within
        # the window this call is given, so the fallback still has to run.
        def fake_evaluate(ws, js, *a, **kw):
            if "fnRemoveForm" in js:
                return {"ok": True}
            return {"found": True, "target": {"x": 5, "y": 5}}

        with patch.object(core, "evaluate", side_effect=fake_evaluate), \
             patch.object(core, "click_element_by_rect"), \
             patch.object(core.gmes_open_screen, "open_screens",
                           side_effect=[self.STILL_OPEN, self.GONE]), \
             patch.object(core.time, "sleep"), \
             patch.object(core.time, "time", side_effect=[0, 5, 20, 20, 25]):
            ok, detail = self._screen().close(timeout=10)

        self.assertTrue(ok)
        self.assertIn("direct", detail)

    def test_reports_clearly_when_neither_way_closes_it(self):
        def fake_evaluate(ws, js, *a, **kw):
            if "fnRemoveForm" in js:
                return {"ok": False, "reason": "threw: fnRemoveForm is not a function"}
            return {"found": False, "reason": "the tab has no close control"}

        with patch.object(core, "evaluate", side_effect=fake_evaluate), \
             patch.object(core, "click_element_by_rect") as click, \
             patch.object(core.gmes_open_screen, "open_screens", return_value=self.STILL_OPEN):
            ok, detail = self._screen().close(timeout=5)

        click.assert_not_called()
        self.assertFalse(ok)
        self.assertIn("fnRemoveForm did not close it either", detail)


class OpenScreenNeverGuessesANewTab(unittest.TestCase):
    """HISTORY.md - external review of 1957ba9/cff282b, finding #10:
    `open_screen()` used to return `new[0]` - the first tab with a winId
    not seen before the search - the moment ANY new tab appeared, even
    when none of them actually matched the menu id just searched for. Its
    own comment said "rather than guessing"; the code then guessed. A
    notice popup, a leftover AD SSO window, or another run/session sharing
    this browser (the same class of collision `acquire_run_lock()` exists
    for) opening something at the same moment could all be mistaken for
    the screen this call asked for."""

    CHOSEN = {"index": 0, "screenId": "P1112UM00", "menuId": "PPM0219",
             "name": "Production Plan"}

    def _run(self, poll_rows, timeout=3):
        # `poll_rows` is chained with an infinite repeat of its own last
        # element - a finite list exhausting mid-poll raises StopIteration,
        # which would be caught as an unrelated crash rather than proving
        # the loop actually kept polling for the right reason.
        import itertools
        responses = itertools.chain([{"rows": []}], poll_rows,
                                    itertools.repeat(poll_rows[-1]))
        with patch.object(gmes_open_screen, "close_child_popups", return_value=[]), \
             patch.object(gmes_open_screen, "open_screens",
                          side_effect=lambda *a, **k: next(responses)), \
             patch.object(gmes_open_screen, "type_into_search"), \
             patch.object(gmes_open_screen, "wait_for_results",
                          return_value=[self.CHOSEN]), \
             patch.object(gmes_open_screen, "evaluate",
                          return_value={"found": True, "x": 1, "y": 1}), \
             patch.object(gmes_open_screen, "click_element_by_rect"), \
             patch.object(gmes_open_screen.time, "sleep"):
            return gmes_open_screen.open_screen(None, "P1112UM00", timeout=timeout)

    def test_an_unrelated_new_tab_is_never_mistaken_for_the_target(self):
        # A popup or another session's screen opens (a new winId), but its
        # menuId never matches what was actually searched for - must keep
        # polling, not grab it, and eventually time out clearly rather than
        # return the wrong screen.
        unrelated = [{"rows": [{"winId": "winPOPUP", "menuId": "OTHER0001"}]}]
        with self.assertRaisesRegex(RuntimeError, "did not open within"):
            self._run(unrelated, timeout=0.05)

    def test_the_real_match_is_returned_even_if_it_takes_a_few_polls(self):
        # The legitimate case the old new[0] shortcut was trying to serve -
        # a genuine propagation delay - must still work, just via the exact
        # match on a later poll instead of a guess on an earlier one.
        delayed = [
            {"rows": [{"winId": "winPOPUP", "menuId": "OTHER0001"}]},
            {"rows": [{"winId": "winPOPUP", "menuId": "OTHER0001"},
                     {"winId": "winREAL", "menuId": "PPM0219"}]},
        ]
        result = self._run(delayed, timeout=5)
        self.assertEqual(result["winId"], "winREAL")


class CatalogueTruncationIsReported(unittest.TestCase):
    """HISTORY.md - external review of 1957ba9/cff282b, finding #12:
    `JS_CATALOGUE` used to report `matched: rows.length` - and `rows` was
    itself capped at 60 - so a 143-match search silently reported "60
    matches" with no sign any were missing. Source-level (JS_CATALOGUE
    cannot run offline, CLAUDE.md 4.3): `matched` is now counted
    independently of the 60-row display cap."""

    def test_matched_is_counted_before_the_display_cap_is_applied(self):
        self.assertIn("matched++;", gmes_open_screen.JS_CATALOGUE)
        self.assertIn("if (rows.length < 60)", gmes_open_screen.JS_CATALOGUE)
        # matched++ must appear BEFORE the cap check in source order, or it
        # would only count what was actually kept, defeating the point.
        matched_at = gmes_open_screen.JS_CATALOGUE.index("matched++;")
        cap_at = gmes_open_screen.JS_CATALOGUE.index("if (rows.length < 60)")
        self.assertLess(matched_at, cap_at)

    def test_the_result_carries_an_explicit_truncated_flag(self):
        self.assertIn('truncated: matched > rows.length', gmes_open_screen.JS_CATALOGUE)

    def test_find_cli_prints_the_true_matched_count_when_truncated(self):
        with patch.object(sys, "argv", ["gmes_open_screen.py", "--find", "plan"]), \
             patch.object(gmes_open_screen, "connect_gmes", return_value=Mock(close=lambda: None)), \
             patch.object(gmes_open_screen, "catalogue",
                          return_value={"found": True, "total": 810, "matched": 143,
                                       "returned": 60, "truncated": True, "rows": []}), \
             patch("builtins.print") as mock_print:
            code = gmes_open_screen.main()
        self.assertEqual(code, 0)
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("143", printed)

    def test_the_pre_open_preview_uses_the_true_count_not_the_capped_one(self):
        many_rows = [{"screenId": f"P{i}", "menuTitle": "x", "path": "",
                     "menuId": f"M{i}", "sysCode": "", "pageUrl": f"P{i}"}
                    for i in range(2)]
        with patch.object(sys, "argv", ["gmes_open_screen.py", "P1112"]), \
             patch.object(gmes_open_screen, "connect_gmes", return_value=Mock(close=lambda: None)), \
             patch.object(gmes_open_screen, "catalogue",
                          return_value={"found": True, "total": 810, "matched": 143,
                                       "returned": 60, "truncated": True, "rows": many_rows}), \
             patch.object(gmes_open_screen, "open_screen",
                          return_value={"title": "x", "menuId": "M0", "winId": "w", "pageUrl": "p"}), \
             patch("builtins.print") as mock_print:
            code = gmes_open_screen.main()
        self.assertEqual(code, 0)
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("143 matches", printed)


class WorkflowBatRunTypo(unittest.TestCase):
    """GMES_Workflow.bat's argument branch already runs
    `python gmes_report.py run %*`. Typing `GMES_Workflow.bat run
    P1112UM00 ...` makes gmes_report.py see "run" a second time, where
    argparse's `screens` (nargs="+") happily swallows it as a screen code -
    the resulting cascade ("RUN not found", then every real screen skipped
    as "previous screen left an unknown state") was confusing enough to
    look like a deeper failure the first time it was hit live."""

    def test_a_repeated_run_argument_is_caught_before_any_browser_work(self):
        with patch.object(sys, "argv", ["gmes_report.py", "run", "run", "P1112UM00"]), \
             patch.object(gmes_report.core, "sign_in") as sign_in, \
             patch("builtins.print") as mock_print:
            result = gmes_report.main()

        self.assertEqual(result, 2)
        sign_in.assert_not_called()
        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("GMES_Workflow.bat P1112UM00", printed)
        self.assertIn("python gmes_report.py run P1112UM00", printed)

    def test_a_screen_that_is_only_coincidentally_named_run_is_unaffected(self):
        # "run" is the guard's trigger only as args.screens[0] under the
        # "run" command with a repeated "run" - a single, ordinary
        # "run <SCREEN>" invocation must never be caught by it.
        with patch.object(sys, "argv", ["gmes_report.py", "run", "P1112UM00"]), \
             patch.object(gmes_report.core, "sign_in", return_value=False), \
             patch("builtins.print"):
            result = gmes_report.main()

        # Falls through to the real "sign-in failed" path (1), not the
        # guard's usage error (2) - proving the guard did not fire here.
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

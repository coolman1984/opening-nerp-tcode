"""Offline regression tests for the safety gates ported to the legacy path."""
import os
import sys
import unittest
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmes_common  # noqa: E402
import gmes_core as core  # noqa: E402
import gmes_log  # noqa: E402


def _screen(info):
    return core.Screen(None, "P1112UM00", {"title": "Test"}, info)


class ResultVerification(unittest.TestCase):
    def test_checks_every_result_row_not_a_small_sample(self):
        result = {
            "found": True,
            "columns": ["planYmd"],
            "rows": [{"planYmd": "20260909"}] * 8 + [{"planYmd": "20260908"}],
        }
        with patch.object(core, "read_rows", return_value=result) as read:
            seen, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "20260909")
        read.assert_called_once_with(None, "P1112WM00", "dsResult", limit=-1)
        self.assertEqual(seen, ["20260908", "20260909"])
        self.assertIn("not exactly", problem)

    def test_requires_an_expected_value(self):
        result = {"found": True, "columns": ["planYmd"], "rows": [{"planYmd": "20260909"}]}
        with patch.object(core, "read_rows", return_value=result):
            _, problem = core.verify_rows(None, "P1112WM00", "dsResult", "planYmd", "")
        self.assertIn("expected value", problem)


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

    def test_a_closed_browser_returns_none_without_raising(self):
        # gmes_tab() raises RuntimeError when the automation browser is
        # unreachable (HISTORY.md: "closed by a previous job"). A
        # best-effort diagnostic screenshot must absorb that, not crash the
        # failure path that was trying to call it. gmes_tab's own polling
        # is not under test here, so it is mocked directly rather than
        # exercised through get_tabs/time.sleep.
        with patch.object(gmes_common, "gmes_tab", side_effect=RuntimeError(
                "Cannot reach the automation browser.")):
            result = gmes_common.capture_screenshot("out.png")
        self.assertIsNone(result)

    def test_no_page_tabs_at_all_is_handled_like_the_existing_contract(self):
        # cdp_common.capture_screenshot's existing contract: no tab -> None,
        # no exception. gmes_tab() with nothing open returns None (not a
        # raise) via its own "pages[0] if pages else None" fallback.
        with patch.object(gmes_common, "gmes_tab", return_value=None), \
             patch.object(gmes_common.cdp_common, "capture_screenshot", return_value=None) as inner:
            result = gmes_common.capture_screenshot("out.png")
        self.assertIsNone(result)
        self.assertIsNone(inner.call_args.kwargs["tab"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

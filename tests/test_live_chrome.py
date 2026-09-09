"""
End-to-end tests against a REAL Chrome over a REAL CDP connection, driving
the mock portal in mock_nerp_server.py.

This is the part that unit tests cannot reach: whether the cross-origin
iframe really shows up as its own CDP target, whether a synthetic click
really is ignored, whether dispatchKeyEvent really reaches an out-of-process
frame, and whether the export flows really complete. Every assertion here
corresponds to a failure that has actually happened against the live portal.

    python tests/test_live_chrome.py            # all scenarios
    python tests/test_live_chrome.py --headed   # watch it happen

It uses its own CDP port and profile and does NOT kill the user's Chrome.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
import execute_filters  # noqa: E402
import export_to_excel  # noqa: E402
import search_tcode  # noqa: E402
import mock_nerp_server  # noqa: E402


TEST_PORT = int(os.environ.get("NERP_TEST_CDP_PORT", "9555"))
HEADED = "--headed" in sys.argv

# The shell and the iframes must be different SITES for Chrome to give the
# iframe its own CDP target, which is the condition the real portal creates
# by serving the WebGUI from a different origin. Both names are mapped to
# loopback, so no hosts-file edit or admin rights are needed.
SHELL_HOST = "nerps.mock"
IFRAME_HOST = "webgui.mock"

FAST = {"go_delay": 1200, "fields_delay": 500, "busy_ms": 900,
        "dialog_ms": 600, "slow_ms": 1800, "offscreen_ms": 350,
        "confirm_ms": 1200}


def _read_webgui(js):
    tab = cdp_common.get_webgui_tab()
    if not tab:
        return None
    ws = cdp_common.connect(tab["webSocketDebuggerUrl"], timeout=10)
    try:
        return cdp_common.evaluate(ws, js)
    finally:
        ws.close()


def wait_for(predicate, timeout=30, interval=0.4, what="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as e:
            last = e
        time.sleep(interval)
    raise AssertionError(f"Timed out after {timeout}s waiting for {what} (last: {last!r})")


_SERVER = None
_CHROME = None
_ORIG_PORT = None


def setUpModule():
    """One mock server and one Chrome for the whole run - launching per class
    would fight over the same profile directory."""
    global _SERVER, _CHROME, _ORIG_PORT
    _SERVER, _ = mock_nerp_server.start(port=0, timings=FAST)

    flags = [
        # Force every cross-site iframe out of process, reproducing the real
        # portal's separate-target behaviour on loopback.
        "--site-per-process",
        f"--host-resolver-rules=MAP {SHELL_HOST} 127.0.0.1,MAP {IFRAME_HOST} 127.0.0.1",
        "--window-size=1400,900",
        # The corporate proxy intercepts Chrome's own requests too, so the
        # mock hosts must bypass it. NO_PROXY only fixes Python -> CDP.
        "--no-proxy-server",
    ]
    if not HEADED:
        flags.append("--headless=new")

    # kill_existing=False on purpose: the test must not close the user's own
    # browser. It also settles the open question behind gotcha #2 - whether
    # a dedicated --user-data-dir alone is enough to get a new instance.
    cdp_common.launch_chrome(
        port=TEST_PORT, profile=cdp_common.profile_dir("chrome_cdp_test_profile"),
        kill_existing=False, extra_flags=flags)
    _CHROME = cdp_common.LAST_CHROME_PROCESS

    _ORIG_PORT = cdp_common.CDP_PORT
    cdp_common.CDP_PORT = TEST_PORT
    print(f"\nMock portal on port {_SERVER.server_port}, test Chrome on CDP {TEST_PORT} "
          f"({'headed' if HEADED else 'headless'}).\n")


def tearDownModule():
    cdp_common.CDP_PORT = _ORIG_PORT
    if _SERVER:
        _SERVER.shutdown()
    # Terminate only the instance this suite started - never a blanket
    # taskkill, which would close the user's own browser.
    if _CHROME and _CHROME.poll() is None:
        _CHROME.terminate()
        try:
            _CHROME.wait(timeout=10)
        except Exception:
            _CHROME.kill()


class LiveChromeTestCase(unittest.TestCase):

    @property
    def port(self):
        return _SERVER.server_port

    def shell_url(self, flow, tcode):
        return (f"http://{SHELL_HOST}:{self.port}/?flow={flow}"
                f"&fh={IFRAME_HOST}&tc={tcode}")

    def open_tcode(self, flow, tcode="MB52", verify=True):
        with mock.patch.object(search_tcode, "NERP_URL", self.shell_url(flow, tcode)):
            search_tcode.main(tcode, verify=verify)


class TestPortalOpening(LiveChromeTestCase):

    def test_go_button_is_only_reachable_with_a_real_mouse_event(self):
        """Gotcha #5, verified rather than asserted in a comment: the SAP-style
        button ignores element.click() and only responds to a genuine
        mousedown/mouseup pair."""
        cdp_common.navigate_page(self.shell_url("a", "MB52"))
        page_tab, info = search_tcode.wait_for_search_ui(max_wait=60)
        ws = cdp_common.connect(page_tab["webSocketDebuggerUrl"], timeout=15)
        try:
            synthetic = cdp_common.evaluate(ws, """
                (function() {
                    document.getElementById('goBtn').click();
                    return JSON.stringify({clicked: true});
                })()""")
            self.assertTrue(synthetic["clicked"])
            time.sleep(1.0)

            after_synthetic = cdp_common.evaluate(ws, """
                (function() { return JSON.stringify({
                    frames: document.querySelectorAll('iframe').length,
                    clickEvents: window.__clickEventsSeen }); })()""")
            self.assertEqual(after_synthetic["frames"], 0,
                             "element.click() opened the screen - the mock is not "
                             "reproducing the real button behaviour")
            self.assertEqual(after_synthetic["clickEvents"], 1,
                             "the synthetic click was not even delivered")

            cdp_common.click_element_by_rect(ws, info["x"], info["y"])
            frames = wait_for(
                lambda: cdp_common.evaluate(ws, """
                    (function(){ return JSON.stringify({n: document.querySelectorAll('iframe').length}); })()
                """)["n"], what="iframes after a real mouse event")
            self.assertEqual(frames, 3)
        finally:
            ws.close()

    def test_webgui_target_is_separate_and_the_right_one_is_chosen(self):
        """Gotchas #6 and #12 against real CDP targets: the decoy and the
        stale placeholder are both present, and neither may win."""
        self.open_tcode("a", "MB52", verify=False)

        tabs = wait_for(
            lambda: [t for t in cdp_common.get_tabs(port=TEST_PORT)
                     if t.get("type") == "iframe"] or None,
            what="iframe CDP targets to appear")
        urls = [t["url"] for t in tabs]
        self.assertTrue(any("adrum" in u for u in urls),
                        f"the decoy iframe never became its own target: {urls}")

        candidates = [t for t in tabs if cdp_common.is_webgui_candidate(t)]
        self.assertEqual(len(candidates), 2,
                         f"expected the stale + live webgui targets, got {urls}")

        picked = cdp_common.get_webgui_tab(port=TEST_PORT)
        self.assertNotIn("adrum", picked["url"])
        self.assertNotIn("stale", picked["url"],
                         "the stale placeholder was chosen over the live screen")

    def test_selection_screen_readiness_is_awaited_not_assumed(self):
        """Gotcha #16: the target exists before its fields do."""
        self.open_tcode("a", "MB52", verify=False)
        tab = cdp_common.wait_for_selection_screen_ready(max_wait=60)
        state = cdp_common.read_selection_screen_state(tab)
        self.assertTrue(state["executeFound"])
        self.assertIn("Material Number", state["visibleInputTitles"])
        self.assertIn("Plant", state["visibleInputTitles"])

    def test_screen_verification_detects_the_wrong_tcode(self):
        """Gotcha #22, which the original code documented but never enforced."""
        self.open_tcode("a", "MB52", verify=False)
        cdp_common.wait_for_selection_screen_ready(max_wait=60)

        ok, detail = search_tcode.verify_screen_matches("MB52", max_wait=20)
        self.assertTrue(ok, f"the correct screen was reported as wrong: {detail}")

        ok, detail = search_tcode.verify_screen_matches("ZRPPD410200", max_wait=20)
        self.assertFalse(ok, "a completely different t-code was accepted as a match")


class TestFilterAndExecute(LiveChromeTestCase):

    def test_fields_are_matched_by_label_not_id(self):
        """Gotcha #7: dynpro ids are noise; the title attribute is the label."""
        self.open_tcode("a", "MB52", verify=False)
        execute_filters.main({"Material Number": "SM-A137FLBHMEB", "Plant": "P703"})

        result = wait_for(lambda: _read_webgui(
            """(function(){ return JSON.stringify({
                   list: !!document.getElementById('alv'),
                   text: document.body.textContent }); })()"""),
            what="the result list to render")
        self.assertTrue(result["list"], "Execute did not produce the result list")

    def test_execute_lookup_finds_the_button_not_its_container(self):
        """Gotcha #9 applied to Execute. The original lookup matched on
        textContent with no length or visibility filter, so the screen
        container - which contains the button, and comes first in document
        order - won. The click then landed on empty space and the run waited
        forever for results that were never coming."""
        self.open_tcode("a", "MB52", verify=False)
        tab = cdp_common.wait_for_selection_screen_ready(max_wait=60)
        ws = cdp_common.connect(tab["webSocketDebuggerUrl"], timeout=15)
        try:
            info = cdp_common.evaluate(ws, execute_filters.JS_LOCATE_EXECUTE)
        finally:
            ws.close()
        self.assertTrue(info["found"])
        self.assertEqual(info["id"], "execBtn",
                         f"matched {info.get('id')!r} instead of the Execute button")
        self.assertIn("F8", info["title"])

    def test_execute_waits_for_the_busy_indicator(self):
        """Gotcha #25: control must not return while SAP is still working."""
        self.open_tcode("a", "MB52", verify=False)
        execute_filters.main({})
        # No sleep here on purpose - if execute_filters returned too early
        # this assertion is what fails.
        state = _read_webgui(
            """(function(){ return JSON.stringify({
                   list: !!document.getElementById('alv'),
                   busy: document.getElementById('hiddenLoadingToolbarButton').style.display }); })()""")
        self.assertTrue(state["list"],
                        "execute_filters returned before the results had rendered")
        self.assertEqual(state["busy"], "none")

    def test_live_target_is_still_chosen_after_execute_clears_the_fields(self):
        """The post-Execute inversion: once the selection fields are replaced
        by a result list, the live target has zero inputs while the stale
        placeholder still has one. Scoring on field count picked the stale
        frame here, and every export step then drove the wrong screen."""
        self.open_tcode("a", "MB52", verify=False)
        before = cdp_common.get_webgui_tab(port=TEST_PORT)
        self.assertIn("live=1", before["url"])

        execute_filters.main({})

        after = cdp_common.get_webgui_tab(port=TEST_PORT)
        self.assertNotIn("stale", after["url"],
                         "the stale placeholder won once the list replaced the fields")
        self.assertIn("live=1", after["url"])

    def test_unknown_field_label_is_reported_with_the_real_labels(self):
        self.open_tcode("a", "MB52", verify=False)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            execute_filters.main({"Widget Colour": "blue"})
        out = buf.getvalue()
        self.assertIn("could not find fields for", out)
        self.assertIn("Material Number", out,
                      "the error did not list the labels that are actually present")


class TestExportFlows(LiveChromeTestCase):

    def _run_export(self, flow, tcode):
        self.open_tcode(flow, tcode, verify=False)
        execute_filters.main({})
        return export_to_excel.main(tcode, base_filename=f"{tcode}_TEST")

    def _status(self):
        return _read_webgui(
            """(function(){ return JSON.stringify({
                   text: document.getElementById('statusbar').textContent }); })()""")["text"]

    def test_flow_a_ctrl_shift_f7(self):
        self.assertTrue(self._run_export("a", "MB52"))
        self.assertIn("MB52_TEST.xlsx", self._status())

    def test_flow_a_via_shift_f4(self):
        """Gotcha #17: the same shortcut means different things per t-code, so
        the first mechanism must be a real attempt, not a token no-op."""
        self.assertTrue(self._run_export("shiftf4", "MB51"))
        self.assertIn("MB51_TEST.xlsx", self._status())

    def test_flow_b_shift_f7(self):
        self.assertTrue(self._run_export("b", "ZRPPM400300"))
        self.assertIn(".xlsx", self._status().lower())

    def test_flow_c_must_switch_the_save_as_dropdown_to_xlsx(self):
        """Flow C's whole point: 'Text with Tabs' yields a .txt unless the
        Save-as combo is switched to Spreadsheet Files (*.xlsx) first. The
        mock enforces that, so a regression here fails loudly."""
        self.assertTrue(self._run_export("c", "ZRMMK121040"))
        status = self._status()
        self.assertIn("ZRMMK121040_TEST.xlsx", status)
        self.assertNotIn(".txt", status,
                         "the export silently produced a text file, not a workbook")

    def test_export_icon_fallback_survives_the_offscreen_dropdown(self):
        """Gotcha #20: the menu item pre-renders at y = -99984. A visibility
        check that only tests width/height clicks empty space and the whole
        flow fails with no error at all."""
        self.assertTrue(self._run_export("icon", "ZRPPD410200"))
        self.assertIn("ZRPPD410200_TEST.xlsx", self._status())

    def test_offscreen_menu_item_is_not_clickable_until_repositioned(self):
        """Direct proof of the viewport check, independent of the flow."""
        self.open_tcode("icon", "ZRPPD410200", verify=False)
        execute_filters.main({})
        tab = cdp_common.get_webgui_tab(port=TEST_PORT)
        ws = cdp_common.connect(tab["webSocketDebuggerUrl"], timeout=15)
        try:
            icons = cdp_common.find_visible_by_title(ws, "Export", exact=True, max_size=80)
            self.assertTrue(icons, "the toolbar Export icon was not found")
            cdp_common.click_element_by_rect(ws, icons[0]["x"], icons[0]["y"])

            # Immediately after opening, the item exists with a real size but
            # sits far off-screen; the finder must refuse it.
            immediate = cdp_common.find_visible_leaf_by_text(ws, "Spreadsheet")
            offscreen = cdp_common.evaluate(ws, """
                (function() {
                    const el = Array.from(document.querySelectorAll('.menu div'))
                        .find(d => d.textContent.trim() === 'Spreadsheet');
                    if (!el) return JSON.stringify({present: false});
                    const r = el.getBoundingClientRect();
                    return JSON.stringify({present: true, top: r.top,
                                           sized: r.width > 0 && r.height > 0});
                })()""")
            self.assertTrue(offscreen["present"] and offscreen["sized"],
                            "the mock did not pre-render the item off-screen")
            if offscreen["top"] < 0:
                self.assertEqual(immediate, [],
                                 "an off-screen menu item was reported as clickable")

            found = wait_for(lambda: cdp_common.find_visible_leaf_by_text(ws, "Spreadsheet") or None,
                             timeout=10, what="the menu item to move into view")
            self.assertGreater(found[0]["y"], 0)
        finally:
            ws.close()


class TestExportFailureHandling(LiveChromeTestCase):

    def setUp(self):
        # Do not litter the project with diagnostic PNGs for the deliberate
        # failures below.
        patcher = mock.patch.object(cdp_common, "screenshot_on_failure", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_export_mechanism_reports_clearly(self):
        self.open_tcode("none", "CO03", verify=False)
        execute_filters.main({})
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            export_to_excel.main("CO03")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("not a list at all", buf.getvalue())

    def test_unrecognised_dialog_stops_instead_of_firing_more_shortcuts(self):
        """The original code kept sending shortcuts into an open modal, so the
        final error named the last shortcut rather than the actual blocker."""
        self.open_tcode("unknown", "MB52", verify=False)
        execute_filters.main({})
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            export_to_excel.main("MB52")
        out = buf.getvalue()
        self.assertIn("unrecognised dialog", out)
        self.assertIn("No data was selected", out,
                      "the dialog's own text was not reported back")
        self.assertNotIn("Trying Ctrl+Shift+F7", out,
                         "further shortcuts were fired into the open dialog")


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--headed"], verbosity=2)

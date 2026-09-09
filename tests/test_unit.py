"""
Offline tests for the decision logic - no Chrome, no network.

These cover the choices that silently produce a WRONG-but-valid result when
they go wrong (picking the adrum decoy, picking a stale iframe, mis-parsing
filters), which is the failure mode this skill has actually suffered from.

    python tests/test_unit.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cdp_common  # noqa: E402
import execute_filters  # noqa: E402
import export_to_excel  # noqa: E402
import run_nerp_workflow  # noqa: E402


LIVE = {"type": "iframe", "title": "SAP",
        "url": "https://nerps.sec.samsung.net/sap/bc/gui/sap/its/webgui?sap-client=100",
        "webSocketDebuggerUrl": "ws://live"}
STALE = {"type": "iframe", "title": "SAP",
         "url": "https://nerps.sec.samsung.net/sap/bc/gui/sap/its/webgui?stale",
         "webSocketDebuggerUrl": "ws://stale"}
ADRUM = {"type": "iframe", "title": "adrum",
         "url": ("https://cdn.appdynamics.com/adrum/adrum-xd.html"
                 "#https%3A%2F%2Fnerps.sec.samsung.net%2Fsap%2Fbc%2Fgui%2Fsap%2Fits%2Fwebgui%3Bfoo"),
         "webSocketDebuggerUrl": "ws://adrum"}
PAGE = {"type": "page", "title": "N-ERP Home",
        "url": "https://nerps.sec.samsung.net/ui", "webSocketDebuggerUrl": "ws://page"}
OTHER_PAGE = {"type": "page", "title": "New Tab", "url": "chrome://newtab/",
              "webSocketDebuggerUrl": "ws://newtab"}


class TestWebGuiTargetSelection(unittest.TestCase):
    """Gotchas #6 and #12 - the two ways of ending up on a valid wrong page."""

    def test_adrum_decoy_is_rejected(self):
        self.assertFalse(cdp_common.is_webgui_candidate(ADRUM))
        self.assertTrue(cdp_common.is_webgui_candidate(LIVE))

    @staticmethod
    def _scores(mapping):
        return mock.patch.object(
            cdp_common, "score_webgui_tab",
            side_effect=lambda t, **k: (mapping[t["webSocketDebuggerUrl"]], {}))

    def test_adrum_rejected_even_when_it_scores_highest(self):
        # The decoy is excluded by URL, so its content is never consulted.
        with self._scores({"ws://adrum": 2500, "ws://live": 300, "ws://stale": 12}):
            picked = cdp_common.get_webgui_tab(tabs=[ADRUM, STALE, LIVE])
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://live")

    def test_live_wins_over_stale_regardless_of_order(self):
        with self._scores({"ws://live": 300, "ws://stale": 12}):
            for order in ([STALE, LIVE], [LIVE, STALE]):
                picked = cdp_common.get_webgui_tab(tabs=list(order))
                self.assertEqual(picked["webSocketDebuggerUrl"], "ws://live",
                                 f"stale won for order {[t['url'][-8:] for t in order]}")

    def test_live_result_list_still_beats_stale_when_it_has_no_inputs(self):
        """The regression that scoring on field count caused: after Execute
        the live screen is a list with zero inputs, so a one-input stale
        placeholder used to win and every export step drove the wrong
        target."""
        def score(tab, **kwargs):
            if "stale" in tab["url"]:
                return 10 + 0 + 1, {}      # tiny placeholder document, 1 input
            return 450 + 0, {}             # a full result list, 0 inputs
        with mock.patch.object(cdp_common, "score_webgui_tab", side_effect=score):
            picked = cdp_common.get_webgui_tab(tabs=[STALE, LIVE])
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://live")

    def test_no_candidates_returns_none(self):
        self.assertIsNone(cdp_common.get_webgui_tab(tabs=[PAGE, ADRUM]))

    def test_single_candidate_is_not_probed(self):
        with mock.patch.object(cdp_common, "score_webgui_tab") as probe:
            picked = cdp_common.get_webgui_tab(tabs=[PAGE, LIVE])
        probe.assert_not_called()
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://live")

    def test_all_probes_failing_still_returns_a_candidate(self):
        with mock.patch.object(cdp_common, "score_webgui_tab", return_value=(-1, {})):
            picked = cdp_common.get_webgui_tab(tabs=[STALE, LIVE])
        self.assertIsNotNone(picked)


class TestPageTabSelection(unittest.TestCase):
    """Gotcha #18 - duplicate tabs make 'the first page target' the wrong one."""

    def test_prefers_the_portal_tab_over_a_blank_one(self):
        with mock.patch.object(cdp_common, "get_tabs", return_value=[OTHER_PAGE, PAGE]):
            self.assertEqual(cdp_common.get_page_tab()["webSocketDebuggerUrl"], "ws://page")

    def test_falls_back_to_any_page_when_none_match(self):
        with mock.patch.object(cdp_common, "get_tabs", return_value=[OTHER_PAGE]):
            self.assertEqual(cdp_common.get_page_tab()["webSocketDebuggerUrl"], "ws://newtab")

    def test_never_returns_an_iframe_as_the_page_target(self):
        with mock.patch.object(cdp_common, "get_tabs", return_value=[LIVE, OTHER_PAGE]):
            self.assertEqual(cdp_common.get_page_tab()["type"], "page")


class TestProxyBypass(unittest.TestCase):
    """Gotcha #1 - without this every localhost CDP call is 403 URLBlocked."""

    def test_sets_both_casings(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cdp_common.apply_proxy_bypass()
            for name in ("NO_PROXY", "no_proxy"):
                self.assertIn("localhost", os.environ[name])
                self.assertIn("127.0.0.1", os.environ[name])

    def test_preserves_an_existing_value(self):
        with mock.patch.dict(os.environ, {"NO_PROXY": "corp.internal"}, clear=True):
            cdp_common.apply_proxy_bypass()
            self.assertIn("corp.internal", os.environ["NO_PROXY"])
            self.assertIn("localhost", os.environ["NO_PROXY"])

    def test_is_idempotent(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cdp_common.apply_proxy_bypass()
            first = os.environ["NO_PROXY"]
            cdp_common.apply_proxy_bypass()
            self.assertEqual(first, os.environ["NO_PROXY"])


class TestMessageIds(unittest.TestCase):
    """The hand-picked ids in the original code could collide across helpers."""

    def test_ids_are_unique_and_increasing(self):
        ids = [cdp_common.next_id() for _ in range(200)]
        self.assertEqual(len(set(ids)), 200)
        self.assertEqual(ids, sorted(ids))


class TestFilterArgParsing(unittest.TestCase):
    def test_equals_style(self):
        parsed = execute_filters.parse_filter_args(["Material Number=SM-A137", "Plant=P703"])
        self.assertEqual(parsed, {"Material Number": "SM-A137", "Plant": "P703"})

    def test_value_may_contain_equals(self):
        parsed = execute_filters.parse_filter_args(["Note=a=b"])
        self.assertEqual(parsed, {"Note": "a=b"})

    def test_flags_are_ignored(self):
        self.assertEqual(execute_filters.parse_filter_args(["--strict"]), {})


class TestWorkflowArgParsing(unittest.TestCase):
    """The old SKILL.md told callers to pipe stdin because argv was not
    supported; both argv styles must now work."""

    def test_pair_style(self):
        tcode, filters = run_nerp_workflow.parse_cli_args(
            ["MB52", "Material Number", "SM-A137", "Plant", "P703"])
        self.assertEqual(tcode, "MB52")
        self.assertEqual(filters, {"Material Number": "SM-A137", "Plant": "P703"})

    def test_equals_style(self):
        tcode, filters = run_nerp_workflow.parse_cli_args(["MB52", "Plant=P703"])
        self.assertEqual((tcode, filters), ("MB52", {"Plant": "P703"}))

    def test_no_filters(self):
        self.assertEqual(run_nerp_workflow.parse_cli_args(["MB52"]), ("MB52", {}))

    def test_flags_do_not_count_as_filters(self):
        tcode, filters = run_nerp_workflow.parse_cli_args(["MB52", "--no-export"])
        self.assertEqual((tcode, filters), ("MB52", {}))

    def test_odd_pair_count_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_nerp_workflow.parse_cli_args(["MB52", "Plant"])

    def test_mixed_styles_are_rejected(self):
        with self.assertRaises(SystemExit):
            run_nerp_workflow.parse_cli_args(["MB52", "Plant=P703", "Material"])

    def test_empty_argv_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_nerp_workflow.parse_cli_args([])


class TestExportFilenamePatterns(unittest.TestCase):
    """Flow detection keys off the dialog's pre-filled default value, since
    the element id is dynpro-generated and unusable (gotcha #10)."""

    def test_flow_a_pattern(self):
        import re
        rx = re.compile(export_to_excel.FLOW_A_DEFAULT_PATTERN, re.I)
        self.assertTrue(rx.match("EXPORT_20260101_101010"))
        self.assertFalse(rx.match("MB52_20260101_101010"))
        self.assertFalse(rx.match("EXPORT_2026_10"))

    def test_flow_b_pattern(self):
        import re
        rx = re.compile(export_to_excel.FLOW_B_DEFAULT_PATTERN, re.I)
        self.assertTrue(rx.search("MRP_List_20260101.XLSX"))
        self.assertTrue(rx.search("anything.xlsx"))
        self.assertFalse(rx.search("report.txt"))

    def test_generated_names_do_not_look_like_flow_a_defaults(self):
        # A generated name must not be mistaken for an untouched default on
        # a later poll, or the flow could be re-detected after being filled.
        import re
        name = "MB52_20260101_101010"
        self.assertFalse(re.match(export_to_excel.FLOW_A_DEFAULT_PATTERN, name, re.I))


class TestJsSnippets(unittest.TestCase):
    """The JS is built by string interpolation; a broken template shows up
    as a runtime error inside Chrome, so check the shape here instead."""

    def test_filter_js_escapes_quotes_and_backslashes(self):
        js = execute_filters.js_fill_filters({"Note": 'He said "hi"\\'})
        self.assertIn('\\"hi\\"', js)
        self.assertNotIn('"He said "hi""', js)

    def test_every_generated_snippet_is_balanced(self):
        snippets = [
            execute_filters.js_fill_filters({"Plant": "P703"}),
            execute_filters.JS_LOCATE_EXECUTE,
            export_to_excel.js_find_filename_field(export_to_excel.FLOW_A_DEFAULT_PATTERN),
            export_to_excel.js_set_filename_field(export_to_excel.FLOW_B_DEFAULT_PATTERN, "x.xlsx"),
            export_to_excel.JS_FLOW_C_VISIBLE,
            cdp_common.JS_SELECTION_SCREEN_STATE,
        ]
        for js in snippets:
            self.assertEqual(js.count("("), js.count(")"), f"unbalanced parens in: {js[:80]}")
            self.assertEqual(js.count("{"), js.count("}"), f"unbalanced braces in: {js[:80]}")
            self.assertNotIn("%s", js, "an unfilled placeholder survived interpolation")


class TestChromeDiscovery(unittest.TestCase):
    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"CHROME_PATH": __file__}):
            self.assertEqual(cdp_common.find_chrome(), __file__)

    def test_missing_chrome_raises_an_actionable_error(self):
        with mock.patch.dict(os.environ, {"CHROME_PATH": ""}), \
             mock.patch("os.path.isfile", return_value=False), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch.dict(sys.modules, {"winreg": None}):
            with self.assertRaises(RuntimeError) as ctx:
                cdp_common.find_chrome()
        self.assertIn("CHROME_PATH", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline tests for gmes.discovery - the JS templates format and balance
correctly, and the screen-code shape check used to decide whether an
already-open screen can be reached by clicking its tab instead of
re-typing into the search box.

Ported in spirit from tests/test_gmes_core.py's GeneratedJavaScript class
(same reasoning: the JS is built by % substitution, so a stray literal %
or a miscounted placeholder is a runtime crash inside the browser call
rather than an import error - both are cheap to catch here) onto the new
templates in discovery/screen_discovery.py and discovery/screen.py.
tests/test_gmes_core.py is left untouched.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.discovery import catalogue  # noqa: E402
from gmes.discovery import screen as screen_mod  # noqa: E402
from gmes.discovery import screen_discovery as sd  # noqa: E402
from gmes.query.form_locator import JS_HELPERS  # noqa: E402

_VIS = "function(el){return true;}"


class GeneratedJavaScript(unittest.TestCase):
    def snippets(self):
        return {
            "discover": sd._js(sd.JS_DISCOVER, JS_HELPERS, _VIS, '"P1112UM00"',
                               '["edt"]', '"btn"'),
            "left_options": sd.JS_LEFT_OPTIONS,
            "org_trees": sd._js(sd.JS_ORG_TREES, JS_HELPERS),
            "tab_close": screen_mod.JS_TAB_CLOSE_TARGET % (_VIS, '"TAB_win_0_1"'),
        }

    def test_every_template_formats(self):
        for name, js in self.snippets().items():
            self.assertNotIn("%s", js, f"{name} has an unfilled placeholder")

    def test_every_snippet_is_balanced_and_is_an_iife(self):
        for name, js in self.snippets().items():
            for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                self.assertEqual(js.count(opener), js.count(closer),
                                 f"{name} has unbalanced {opener}{closer}")
            self.assertTrue(js.strip().startswith("(function"), name)
            self.assertTrue(js.strip().endswith("})()"), name)


class ScreenCodeShape(unittest.TestCase):
    def test_real_codes_are_recognised(self):
        for code in ("P1112UM00", "P1112WM00", "M4151UM00", "PPM0219"):
            self.assertTrue(screen_mod.looks_like_a_screen_code(code), code)

    def test_a_partial_code_is_not(self):
        self.assertFalse(screen_mod.looks_like_a_screen_code("P111"))

    def test_a_screen_name_is_not(self):
        for name in ("Production Plan by Order(Line)", "Work Calendar", ""):
            self.assertFalse(screen_mod.looks_like_a_screen_code(name), name)


class TabForEmbeddedForm(unittest.TestCase):
    """P1114WM00 is loaded nested inside its P1114UM00 shell's already-open
    tab (winPPM0221_2_373); gdsOpenMenu only ever lists the shell. Live
    reproduction: P1114WM00 (PPM0693) did not open within 90s - the
    catalogue click re-hit the already-open shell, so no new tab appeared
    and no PPM0693 row was ever going to. See HISTORY.md."""

    rows = [{"winId": "winPPM0221_2_373", "menuId": "PPM0221"}]

    def test_finds_the_shells_tab_from_a_nested_work_form(self):
        forms = {"forms": [{"file": "P1114WM00.xfdl.js",
                             "path": "...workFrameSet.winPPM0221_2_373.divWorkMain..."}]}
        with patch.object(catalogue, "list_forms", return_value=forms):
            self.assertEqual(catalogue.tab_for_embedded_form(None, "P1114WM00", self.rows),
                              self.rows[0])

    def test_none_when_the_code_is_not_loaded_anywhere(self):
        with patch.object(catalogue, "list_forms", return_value={"forms": []}):
            self.assertIsNone(catalogue.tab_for_embedded_form(None, "P1114WM00", self.rows))

    def test_none_when_the_forms_own_tab_is_not_in_the_given_rows(self):
        forms = {"forms": [{"file": "P1114WM00.xfdl.js",
                             "path": "...workFrameSet.winSomethingElse_9_9.divWorkMain..."}]}
        with patch.object(catalogue, "list_forms", return_value=forms):
            self.assertIsNone(catalogue.tab_for_embedded_form(None, "P1114WM00", self.rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)

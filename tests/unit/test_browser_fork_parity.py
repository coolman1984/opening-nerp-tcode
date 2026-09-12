"""Signature-parity checks between cdp_common.py (N-ERP + shared, untouched)
and gmes.browser.* (the Phase 3 fork of the subset G-MES actually uses).

This guards against silent drift during the copy: a parameter renamed,
reordered or given a different default while porting would otherwise pass
every other test (nothing here needs a real browser) and only surface much
later as a confusing runtime TypeError.

Two functions have a DELIBERATE, documented signature change and are
checked separately rather than for exact parity - see their own test
methods below for why.
"""
import inspect
import os
import sys
import unittest

# tests/unit/ is one level deeper than the original tests/, so this needs an
# extra dirname() to still reach the repo root and its flat gmes_*.py modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import cdp_common  # noqa: E402  (the original, untouched, still used by N-ERP)

from gmes.browser import cdp as gcdp  # noqa: E402
from gmes.browser import chrome as gchrome  # noqa: E402
from gmes.browser import interaction as ginteraction  # noqa: E402
from gmes.browser import screenshots as gscreenshots  # noqa: E402


# (old cdp_common function, new gmes.browser.<module> function) pairs that
# must have IDENTICAL signatures (names, order, defaults).
IDENTICAL_PAIRS = [
    (cdp_common.next_id, gcdp.next_id),
    (cdp_common.ipv4, gcdp.ipv4),
    (cdp_common.get_tabs, gcdp.get_tabs),
    (cdp_common.send, gcdp.send),
    (cdp_common.evaluate, gcdp.evaluate),
    (cdp_common.connect, gcdp.connect),
    (cdp_common.navigate_page, gcdp.navigate_page),
    (cdp_common.cdp_is_up, gcdp.cdp_is_up),
    (cdp_common.apply_proxy_bypass, gcdp.apply_proxy_bypass),
    (cdp_common.find_chrome, gchrome.find_chrome),
    (cdp_common.default_user_profile_dir, gchrome.default_user_profile_dir),
    (cdp_common.chrome_is_running, gchrome.chrome_is_running),
    (cdp_common.working_profile_dir, gchrome.working_profile_dir),
    (cdp_common.clone_user_profile, gchrome.clone_user_profile),
    (cdp_common.launch_chrome_with_user_profile, gchrome.launch_chrome_with_user_profile),
    (cdp_common.close_browser, gchrome.close_browser),
    (cdp_common.click_element_by_rect, ginteraction.click_element_by_rect),
    (cdp_common.dispatch_key_combo, ginteraction.dispatch_key_combo),
    (cdp_common.capture_screenshot, gscreenshots.capture_screenshot),
]

# Functions confirmed by grep (`cdp_common\.\w+` and `from cdp_common
# import` across every gmes_*.py) to be N-ERP-only in practice: never
# called, directly or transitively, by any G-MES code. Deliberately not
# forked. Listed here so a future maintainer can see the exclusion was a
# checked decision, not an oversight.
DELIBERATELY_NOT_FORKED = [
    "profile_dir", "launch_chrome", "connect_with_retry",
    "find_visible_leaf_by_text", "find_visible_by_title",
    "describe_visible_dialog", "wait_for_busy_indicator_clear",
    "read_selection_screen_state", "wait_for_selection_screen_ready",
    "is_webgui_candidate", "score_webgui_tab", "get_webgui_tab",
]


class SignatureParity(unittest.TestCase):
    def test_forked_functions_match_the_original_signature(self):
        for original, forked in IDENTICAL_PAIRS:
            with self.subTest(function=original.__name__):
                self.assertEqual(
                    inspect.signature(original), inspect.signature(forked),
                    f"{original.__name__} drifted during the Phase 3 fork")

    def test_get_page_tab_was_forked_with_a_corrected_default(self):
        """get_page_tab is the one function the plan initially assumed was
        N-ERP-only (its default `prefer_url_substring="nerps"` looks
        N-ERP-specific) but grep evidence showed it is directly imported
        and used by gmes_common.py's gmes_tab() and by gmes_connect.py, and
        transitively by navigate_page()/capture_screenshot(). It IS forked,
        with the leftover N-ERP-flavoured default replaced by None - every
        real G-MES call site already passed None explicitly, so this is
        not a behavior change for G-MES, just a cleaner default."""
        old_sig = inspect.signature(cdp_common.get_page_tab)
        new_sig = inspect.signature(gcdp.get_page_tab)
        self.assertEqual(list(old_sig.parameters), list(new_sig.parameters))
        self.assertEqual(old_sig.parameters["prefer_url_substring"].default, "nerps")
        self.assertEqual(new_sig.parameters["prefer_url_substring"].default, None)

    def test_screenshot_on_failure_gained_a_directory_parameter(self):
        """screenshot_on_failure originally saved beside cdp_common.py
        itself (fine at the repo root; wrong once this code lives inside
        an installed gmes package). The fork adds an optional `directory`
        parameter (defaulting to the current working directory instead of
        __file__'s location) and changes the default prefix from
        "nerp_failure" to "gmes_failure" - every real G-MES call site
        already passed its own explicit prefix, so neither change affects
        existing behavior."""
        old_sig = inspect.signature(cdp_common.screenshot_on_failure)
        new_sig = inspect.signature(gscreenshots.screenshot_on_failure)
        self.assertEqual(list(old_sig.parameters), ["prefix"])
        self.assertEqual(list(new_sig.parameters), ["prefix", "directory"])
        self.assertEqual(old_sig.parameters["prefix"].default, "nerp_failure")
        self.assertEqual(new_sig.parameters["prefix"].default, "gmes_failure")

    def test_last_chrome_process_is_not_reexported_stale(self):
        """LAST_CHROME_PROCESS must be read as chrome.LAST_CHROME_PROCESS
        (module attribute), never imported by name, or a reassignment
        inside launch_chrome_with_user_profile() would be invisible to the
        importer - see the comment in browser/__init__.py."""
        import gmes.browser as gbrowser
        self.assertNotIn("LAST_CHROME_PROCESS", dir(gbrowser))
        self.assertTrue(hasattr(gchrome, "LAST_CHROME_PROCESS"))


class ExclusionListIsAccurate(unittest.TestCase):
    def test_excluded_names_are_real_cdp_common_functions(self):
        for name in DELIBERATELY_NOT_FORKED:
            with self.subTest(name=name):
                self.assertTrue(hasattr(cdp_common, name),
                                f"{name!r} is not even in cdp_common.py - fix the exclusion list")

    def test_excluded_names_were_not_accidentally_forked(self):
        for module in (gcdp, gchrome, ginteraction, gscreenshots):
            for name in DELIBERATELY_NOT_FORKED:
                with self.subTest(module=module.__name__, name=name):
                    self.assertFalse(hasattr(module, name),
                                     f"{name!r} was supposed to stay N-ERP-only")


class JsSnippetsWellFormed(unittest.TestCase):
    """Basic sanity check that the forked JS string constants have balanced
    braces/parens, in the same spirit as test_gmes_core.py's JS template
    balance tests - catches a broken copy-paste before it reaches Chrome."""

    def _assert_balanced(self, js):
        self.assertEqual(js.count("{"), js.count("}"))
        self.assertEqual(js.count("("), js.count(")"))

    def test_js_is_visible_balanced_in_both_copies(self):
        self._assert_balanced(cdp_common.JS_IS_VISIBLE)
        self._assert_balanced(ginteraction.JS_IS_VISIBLE)
        self.assertEqual(cdp_common.JS_IS_VISIBLE, ginteraction.JS_IS_VISIBLE)

    def test_js_set_value_balanced_and_unchanged(self):
        self._assert_balanced(cdp_common.JS_SET_VALUE)
        self._assert_balanced(ginteraction.JS_SET_VALUE)
        self.assertEqual(cdp_common.JS_SET_VALUE, ginteraction.JS_SET_VALUE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline guards for the shared CDP layer that every G-MES run depends on.

    python tests/test_cdp_common.py

These tests used to live in `tests/test_unit.py`, the N-ERP suite, because
`cdp_common.py` was shared by both systems and N-ERP happened to be the side
that grew a test file first. N-ERP was removed in HISTORY.md Phase 72, and
these particular guards had nothing to do with N-ERP: they cover
`cdp_common.py` behaviour that G-MES uses on every single run, and two of
them exist because of live G-MES incidents specifically.

Migrating them here BEFORE deleting the N-ERP suite is the whole point. The
same mistake in reverse - deleting a test file named after the thing being
removed, without checking what else it was protecting - would have silently
dropped the only automated proof that the AD SSO popup flag is still passed.

What each class protects, and why it is not optional:

  TestUserProfileChromeLaunchArguments
      `--disable-popup-blocking`. Without it this machine's Chrome GPO
      swallows the AD SSO window outright and sign-in fails with nothing to
      see (HISTORY.md Phase 56.1, ported to the legacy launcher in 57.7).
  TestScreenshotTabOverrideIsBackwardCompatible
      the optional `tab=` parameter that lets G-MES name its own tab, so a
      diagnostic screenshot cannot silently photograph a leftover SSO popup
      and be mistaken for evidence (Phase 56.4, ported in 57.8).
  TestProxyBypass
      GMES_SKILL.md gotcha #1 / the corporate gateway. Without this every
      localhost CDP call comes back 403 URLBlocked.
  TestMessageIds
      hand-picked CDP message ids could collide across overlapping helpers
      on one socket, so a caller could read another's reply.
  TestChromeDiscovery
      Chrome is not always in Program Files; a per-user install used to die
      with a bare WinError 2.
  TestPageTabSelection
      `get_page_tab()`, reached live from `gmes_connect.py` (with "gmes")
      and from `capture_screenshot`/`navigate_page` (with None).

No browser is launched anywhere in this file: `subprocess.Popen`, the
port-wait loop, `connect` and `send` are all mocked.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cdp_common  # noqa: E402


# Tab fixtures shaped like the ones these functions actually meet. A foreign
# page target is kept deliberately: the automation drives a COPY of the
# user's own Chrome profile, so an unrelated tab really can be open beside
# G-MES, and "picks the right one out of several" is the property under test.
# tests/test_legacy_hardening.py uses the same technique for the strict
# G-MES screenshot resolver.
GMES_PAGE = {"type": "page", "title": "G-MES",
             "url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html",
             "webSocketDebuggerUrl": "ws://gmes"}
SSO_PAGE = {"type": "page", "title": "Sign in",
            "url": ("https://stseu.secsso.net/adfs/ls/?SAMLRequest=abc"
                    "&RelayState=http%3A%2F%2Fseegmes4.sec.samsung.net%2Fmes4%2Fadsso"),
            "webSocketDebuggerUrl": "ws://sso"}
BLANK_PAGE = {"type": "page", "title": "New Tab", "url": "chrome://newtab/",
              "webSocketDebuggerUrl": "ws://newtab"}
AN_IFRAME = {"type": "iframe", "title": "embedded",
             "url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/frame.html",
             "webSocketDebuggerUrl": "ws://iframe"}


class TestPageTabSelection(unittest.TestCase):
    """`get_page_tab()` - which top-level page target gets driven.

    A long-lived CDP session accumulates duplicate and stale page targets, so
    `next(t for t in tabs if t['type'] == 'page')` picks whichever stale one
    happens to be listed first. Both live G-MES call sites are covered here:
    `gmes_connect.py:84` passes "gmes", while `capture_screenshot()` and
    `navigate_page()` both pass None explicitly.
    """

    def test_prefers_a_tab_matching_the_substring(self):
        # gmes_connect.py's real call: several pages open, one is G-MES.
        with mock.patch.object(cdp_common, "get_tabs",
                               return_value=[BLANK_PAGE, GMES_PAGE]):
            picked = cdp_common.get_page_tab(prefer_url_substring="gmes")
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://gmes")

    def test_the_preference_wins_regardless_of_list_order(self):
        for order in ([GMES_PAGE, BLANK_PAGE], [BLANK_PAGE, GMES_PAGE]):
            with self.subTest(order=[t["title"] for t in order]):
                with mock.patch.object(cdp_common, "get_tabs", return_value=list(order)):
                    picked = cdp_common.get_page_tab(prefer_url_substring="gmes")
                self.assertEqual(picked["webSocketDebuggerUrl"], "ws://gmes")

    def test_falls_back_to_any_page_when_none_match(self):
        with mock.patch.object(cdp_common, "get_tabs", return_value=[BLANK_PAGE]):
            picked = cdp_common.get_page_tab(prefer_url_substring="gmes")
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://newtab")

    def test_no_preference_takes_the_first_page_target(self):
        # capture_screenshot() and navigate_page() both call it this way.
        with mock.patch.object(cdp_common, "get_tabs",
                               return_value=[BLANK_PAGE, GMES_PAGE]):
            picked = cdp_common.get_page_tab(prefer_url_substring=None)
        self.assertEqual(picked["webSocketDebuggerUrl"], "ws://newtab")

    def test_never_returns_an_iframe_as_the_page_target(self):
        # Page.captureScreenshot fails outright on a non-top-level target, so
        # handing back an iframe here breaks the diagnostic, not just the pick.
        with mock.patch.object(cdp_common, "get_tabs",
                               return_value=[AN_IFRAME, BLANK_PAGE]):
            self.assertEqual(cdp_common.get_page_tab()["type"], "page")

    def test_no_page_targets_at_all_does_not_raise(self):
        with mock.patch.object(cdp_common, "get_tabs", return_value=[AN_IFRAME]):
            self.assertEqual(cdp_common.get_page_tab(), AN_IFRAME)
        with mock.patch.object(cdp_common, "get_tabs", return_value=[]):
            self.assertIsNone(cdp_common.get_page_tab())


class TestProxyBypass(unittest.TestCase):
    """GMES_SKILL.md gotcha #1 - without this every localhost CDP call is
    routed through the corporate gateway and blocked ("403 URLBlocked",
    Skyhigh Secure Web Gateway). urllib reads these variables at call time,
    so setting them in-process is enough, but it must happen before the
    first request - which is why `cdp_common` calls it at import."""

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
    """The original code hand-picked ids per call site (2, 10, 11, 30, ...)
    with ad-hoc offsets, which is a latent correlation bug: two overlapping
    helpers on the same socket can reuse an id and read each other's reply."""

    def test_ids_are_unique_and_increasing(self):
        ids = [cdp_common.next_id() for _ in range(200)]
        self.assertEqual(len(set(ids)), 200)
        self.assertEqual(ids, sorted(ids))


class TestChromeDiscovery(unittest.TestCase):
    """Chrome is not always machine-wide in Program Files; a per-user install
    lands in %LOCALAPPDATA% and the original hardcoded path died with a bare
    WinError 2."""

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


class TestUserProfileChromeLaunchArguments(unittest.TestCase):
    """AD SSO opens ADFS via window.open(); without --disable-popup-blocking
    this machine's Chrome GPO silently swallows that popup and the sign-in
    wait times out with nothing to show for it (HISTORY.md Phase 56.1,
    live-proven; ported to this launcher in Phase 57.7). No live browser is
    launched here; subprocess.Popen and the port-wait loop are both mocked.

    `launch_chrome_with_user_profile()` is the ONLY launcher left in the
    project - it drives the protected `CDP Profile` copy (CLAUDE.md 2.1a).
    """

    def test_disable_popup_blocking_is_present_exactly_once(self):
        # cdp_is_up is called once up front (must be False, or the function
        # assumes Chrome is already running and never launches anything) and
        # again inside the wait loop to detect the port coming up; True on
        # that second call ends the loop without a real 45s timeout or a
        # real browser.
        with mock.patch.object(cdp_common, "cdp_is_up", side_effect=[False, True]), \
             mock.patch.object(cdp_common, "clone_user_profile", return_value="C:\\fake\\profile"), \
             mock.patch.object(cdp_common, "find_chrome", return_value="C:\\fake\\chrome.exe"), \
             mock.patch.object(cdp_common.subprocess, "Popen") as popen, \
             mock.patch.object(cdp_common.time, "sleep"):
            popen.return_value = mock.Mock()
            cdp_common.launch_chrome_with_user_profile(port=9999, wait_seconds=1)

        args = popen.call_args.args[0]
        self.assertEqual(
            args.count("--disable-popup-blocking"), 1,
            f"expected the flag exactly once, got: {args}")

    def test_every_previously_required_argument_still_present(self):
        with mock.patch.object(cdp_common, "cdp_is_up", side_effect=[False, True]), \
             mock.patch.object(cdp_common, "clone_user_profile", return_value="C:\\fake\\profile"), \
             mock.patch.object(cdp_common, "find_chrome", return_value="C:\\fake\\chrome.exe"), \
             mock.patch.object(cdp_common.subprocess, "Popen") as popen, \
             mock.patch.object(cdp_common.time, "sleep"):
            popen.return_value = mock.Mock()
            cdp_common.launch_chrome_with_user_profile(port=9999, wait_seconds=1)

        args = popen.call_args.args[0]
        for required in ("--remote-debugging-port=9999",
                         "--user-data-dir=C:\\fake\\profile",
                         "--profile-directory=Default",
                         "--remote-allow-origins=*",
                         "--no-first-run", "--no-default-browser-check",
                         "--restore-last-session=false"):
            with self.subTest(arg=required):
                self.assertIn(required, args)


class TestScreenshotTabOverrideIsBackwardCompatible(unittest.TestCase):
    """cdp_common.capture_screenshot()/screenshot_on_failure() carry an
    optional `tab` parameter so G-MES can name its own tab correctly
    (HISTORY.md Phase 56.4, ported in 57.8). `gmes_common.capture_screenshot`
    resolves the G-MES host itself and passes it in; the unset case must stay
    exactly what it was for every caller that does not. No browser is
    launched; Page.captureScreenshot itself is mocked via `send`."""

    def test_unset_tab_resolves_through_get_page_tab_exactly_as_before(self):
        fake_tab = {"webSocketDebuggerUrl": "ws://x/1"}
        with mock.patch.object(cdp_common, "get_page_tab", return_value=fake_tab) as gpt, \
             mock.patch.object(cdp_common, "connect"), \
             mock.patch.object(cdp_common, "send",
                               return_value={"result": {"data": ""}}), \
             mock.patch("builtins.open", mock.mock_open()):
            cdp_common.capture_screenshot("out.png", port=1234)

        gpt.assert_called_once_with(prefer_url_substring=None, port=1234)

    def test_a_provided_tab_skips_get_page_tab_entirely(self):
        named_tab = {"webSocketDebuggerUrl": "ws://x/named"}
        with mock.patch.object(cdp_common, "get_page_tab") as gpt, \
             mock.patch.object(cdp_common, "connect") as connect, \
             mock.patch.object(cdp_common, "send",
                               return_value={"result": {"data": ""}}), \
             mock.patch("builtins.open", mock.mock_open()):
            cdp_common.capture_screenshot("out.png", tab=named_tab)

        gpt.assert_not_called()
        connect.assert_called_once_with(named_tab["webSocketDebuggerUrl"],
                                        timeout=20, enable_runtime=False)

    def test_no_tab_available_returns_none_same_as_before(self):
        with mock.patch.object(cdp_common, "get_page_tab", return_value=None):
            result = cdp_common.capture_screenshot("out.png")
        self.assertIsNone(result)

    def test_screenshot_on_failure_passes_tab_through_unchanged_by_default(self):
        with mock.patch.object(cdp_common, "capture_screenshot", return_value=None) as cap:
            cdp_common.screenshot_on_failure("gmes_failure")
        self.assertIsNone(cap.call_args.kwargs["tab"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Reaching a second machine: identity, browser choice, profile, first login."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import onboarding_uc
from gmes.auth import install
from gmes.browser import chrome


class TemporaryRuntime(unittest.TestCase):
    """Every test here writes only inside its own LOCALAPPDATA."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": directory.name}))
        self.root = directory.name


class InstallIdentityTests(TemporaryRuntime):
    def machine(self, computer="PC-A", user="owner"):
        return patch.dict(os.environ, {"COMPUTERNAME": computer, "USERDOMAIN": "SEC",
                                       "USERNAME": user})

    def test_a_machine_with_no_record_is_a_first_run(self):
        state = install.inspect()
        self.assertTrue(state.first_run)
        self.assertTrue(state.is_new_here)
        self.assertIn("first run", state.describe())

    def test_recording_then_reading_back_recognises_the_same_machine(self):
        with self.machine():
            install.record()
            state = install.inspect()
        self.assertFalse(state.is_new_here)
        self.assertIn("belongs to this computer", state.describe())

    def test_the_same_tree_on_another_computer_is_recognised_as_moved(self):
        with self.machine(computer="PC-A"):
            install.record()
        with self.machine(computer="PC-B"):
            state = install.inspect()
        self.assertTrue(state.moved)
        self.assertFalse(state.first_run)
        self.assertIn("another computer", state.describe())

    def test_a_different_windows_account_on_one_computer_is_also_moved(self):
        with self.machine(user="owner"):
            install.record()
        with self.machine(user="colleague"):
            self.assertTrue(install.inspect().moved)

    def test_the_record_carries_no_machine_or_account_name(self):
        with self.machine(computer="PC-SECRET", user="someone"):
            install.record()
        written = (install.install_path()).read_text(encoding="utf-8")
        self.assertNotIn("PC-SECRET", written)
        self.assertNotIn("someone", written)
        self.assertIn("fingerprint", json.loads(written))

    def test_a_corrupt_record_is_a_first_run_not_a_crash(self):
        path = install.install_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertTrue(install.inspect().first_run)

    def test_reading_the_record_never_creates_the_runtime_tree(self):
        """gmes doctor reads this, and the doctor is read-only by rule."""
        install.inspect()
        self.assertFalse(install.install_path().parent.exists())


class FirstLoginTests(TemporaryRuntime):
    """A new machine is asked for a login; an unattended one is never blocked."""

    def setUp(self):
        super().setUp()
        self.saved = self.enterContext(patch.object(onboarding_uc.credentials, "save"))

    def stored(self, user=None, password=None):
        return patch.object(onboarding_uc.credentials, "load",
                            return_value=(user, password))

    def test_an_existing_login_is_used_without_asking_anything(self):
        prompt = Mock()
        with self.stored("owner", "fake-test-password"):
            self.assertEqual(onboarding_uc.obtain_credentials(log=lambda _: None, prompt=prompt),
                             ("owner", "fake-test-password"))
        prompt.assert_not_called()
        self.saved.assert_not_called()

    def test_a_new_user_is_asked_and_their_answer_is_saved_on_their_own_machine(self):
        prompt = Mock(return_value=("colleague", "their-own-password"))
        with self.stored():
            user, password = onboarding_uc.obtain_credentials(
                log=lambda _: None, prompt=prompt, interactive=True)
        self.assertEqual((user, password), ("colleague", "their-own-password"))
        self.saved.assert_called_once_with("colleague", "their-own-password")

    def test_an_unattended_run_is_never_left_waiting_at_a_password_box(self):
        prompt = Mock()
        lines = []
        with self.stored():
            self.assertEqual(onboarding_uc.obtain_credentials(
                log=lines.append, prompt=prompt, interactive=False), (None, None))
        prompt.assert_not_called()
        self.assertIn("credentials set", " ".join(lines))

    def test_a_cancelled_box_saves_nothing_and_says_so(self):
        lines = []
        with self.stored():
            self.assertEqual(onboarding_uc.obtain_credentials(
                log=lines.append, prompt=Mock(return_value=(None, None)),
                interactive=True), (None, None))
        self.saved.assert_not_called()
        self.assertIn("nothing was saved", " ".join(lines).casefold())

    def test_the_box_is_told_to_close_itself(self):
        prompt = Mock(return_value=("a", "b"))
        with self.stored():
            onboarding_uc.obtain_credentials(log=lambda _: None, prompt=prompt,
                                             interactive=True, timeout_s=90)
        self.assertEqual(prompt.call_args.kwargs["timeout_s"], 90)

    def test_the_installation_is_claimed_only_after_a_sign_in_worked(self):
        self.assertTrue(onboarding_uc.claim_installation(log=lambda _: None))
        self.assertFalse(install.inspect().is_new_here)
        # Already claimed: nothing rewritten on every later run.
        self.assertFalse(onboarding_uc.claim_installation(log=lambda _: None))


class BrowserChoiceTests(unittest.TestCase):
    def test_chrome_is_preferred_and_edge_is_the_fallback(self):
        with patch.object(chrome, "find_chrome", return_value=r"C:\chrome.exe"), \
             patch.object(chrome, "find_edge") as edge:
            self.assertEqual(chrome.find_browser(), (r"C:\chrome.exe", "Chrome"))
        edge.assert_not_called()

        with patch.object(chrome, "find_chrome", side_effect=RuntimeError("no chrome.")), \
             patch.object(chrome, "find_edge", return_value=r"C:\msedge.exe"):
            self.assertEqual(chrome.find_browser(), (r"C:\msedge.exe", "Edge"))

    def test_neither_browser_names_both_environment_variables(self):
        with patch.object(chrome, "find_chrome", side_effect=RuntimeError("no chrome.")), \
             patch.object(chrome, "find_edge", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "EDGE_PATH"):
                chrome.find_browser()


class ProfileStrategyTests(TemporaryRuntime):
    """The developer's copy is used where it exists and never created where it is not."""

    def setUp(self):
        super().setUp()
        self.clone = self.enterContext(
            patch.object(chrome, "clone_user_profile", return_value=r"C:\CDP Profile"))
        self.enterContext(patch.dict(os.environ, {"GMES_BROWSER_PROFILE": ""}))

    def test_an_existing_copy_is_reused_and_never_re_copied(self):
        with patch.object(chrome.os.path, "isdir", return_value=True):
            profile, how = chrome.automation_profile(verbose=False)
        self.assertEqual(profile, r"C:\CDP Profile")
        self.assertIn("existing copy", how)
        self.assertNotIn("refresh", self.clone.call_args.kwargs)

    def test_a_machine_with_no_copy_gets_a_clean_profile_not_a_copy_of_its_owner(self):
        with patch.object(chrome.os.path, "isdir", return_value=False):
            profile, how = chrome.automation_profile(verbose=False)
        self.assertTrue(profile.endswith("browser-profile"))
        self.assertIn("clean profile", how)
        self.clone.assert_not_called()

    def test_the_clean_profile_can_be_forced_even_where_a_copy_exists(self):
        with patch.dict(os.environ, {"GMES_BROWSER_PROFILE": "clean"}), \
             patch.object(chrome.os.path, "isdir", return_value=True):
            profile, _how = chrome.automation_profile(verbose=False)
        self.assertTrue(profile.endswith("browser-profile"))
        self.clone.assert_not_called()

    def test_refreshing_the_copy_happens_only_when_it_is_asked_for(self):
        chrome.automation_profile(verbose=False, refresh=True)
        self.assertTrue(self.clone.call_args.kwargs["refresh"])


class LaunchFallbackTests(TemporaryRuntime):
    """If one browser/profile combination will not open its debugging port,
    a different one is tried before the run gives up - never the same
    combination twice, and never Edge before every Chrome option is spent.

    `_wait_for_port` (did THIS attempt come up in time) is mocked directly
    rather than the polling loop underneath it, so the sequence of
    successes and failures across attempts can be stated as a plain list
    instead of choreographed through time.time()/time.sleep."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {"GMES_BROWSER_PROFILE": ""}))
        self.enterContext(patch.object(chrome, "cdp_is_up", return_value=False))
        self.enterContext(patch.object(chrome, "automation_profile",
                                       return_value=(r"C:\CDP Profile", "the existing copy")))
        self.enterContext(patch.object(chrome, "find_chrome", return_value=r"C:\chrome.exe"))
        self.enterContext(patch.object(chrome, "find_edge", return_value=r"C:\msedge.exe"))
        self.popen = self.enterContext(patch.object(chrome.subprocess, "Popen"))
        self.popen.return_value = Mock()

    def outcomes(self, *results):
        return patch.object(chrome, "_wait_for_port", side_effect=list(results))

    def test_a_working_first_attempt_never_tries_anything_else(self):
        with self.outcomes(True):
            result = chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        self.assertIs(result, self.popen.return_value)
        self.popen.assert_called_once()

    def test_popup_blocking_is_disabled_so_the_ad_sso_window_can_open(self):
        """AD SSO opens via window.open(); a profile without that origin in
        Chrome's popup allowlist silently blocks it, and find_sso_window()
        then waits out the full 45s having never seen a tab (HISTORY.md
        Phase 56.1)."""
        with self.outcomes(True):
            chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        args = self.popen.call_args.args[0]
        self.assertIn("--disable-popup-blocking", args)

    def test_kerberos_negotiate_is_allowed_for_the_sso_host(self):
        """Forward-hardening, not a confirmed fix: a live network capture
        showed ADFS answering the SSO popup's first request with a plain
        200 HTML form, never a 401 challenging for Negotiate/NTLM, so this
        flag has nothing to answer today - the failure is server-side ADFS
        policy. Kept so Chrome is ready the moment that changes
        (HISTORY.md Phase 56.3)."""
        with self.outcomes(True):
            chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        args = self.popen.call_args.args[0]
        self.assertIn("--auth-server-allowlist=*.secsso.net", args)
        self.assertIn("--auth-negotiate-delegate-allowlist=*.secsso.net", args)

    def test_a_profile_that_never_opens_falls_back_to_a_clean_one(self):
        with self.outcomes(False, True):
            result = chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        self.assertIs(result, self.popen.return_value)
        self.assertEqual(self.popen.call_count, 2)
        first_profile = self.popen.call_args_list[0].args[0][2]
        second_profile = self.popen.call_args_list[1].args[0][2]
        self.assertNotEqual(first_profile, second_profile)
        self.assertTrue(second_profile.endswith("browser-profile"))

    def test_the_failed_attempt_is_terminated_before_the_next_one_starts(self):
        with self.outcomes(False, True):
            chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        self.popen.return_value.terminate.assert_called_once()

    def test_a_chrome_that_will_not_start_at_all_falls_through_to_edge(self):
        with patch.object(chrome, "find_chrome", side_effect=RuntimeError("not installed")), \
             self.outcomes(True):
            chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        args = self.popen.call_args.args[0]
        self.assertEqual(args[0], r"C:\msedge.exe")

    def test_every_combination_failing_names_all_of_them(self):
        with self.outcomes(False, False, False):
            with self.assertRaisesRegex(RuntimeError, "Chrome.*Edge|Edge.*Chrome"):
                chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        self.assertEqual(self.popen.call_count, 3)   # copy, clean, edge

    def test_no_browser_at_all_is_reported_without_starting_anything(self):
        with patch.object(chrome, "find_chrome", side_effect=RuntimeError("not installed")), \
             patch.object(chrome, "find_edge", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CHROME_PATH|EDGE_PATH"):
                chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1)
        self.popen.assert_not_called()

    def test_an_already_open_port_is_reused_without_launching_anything(self):
        with patch.object(chrome, "cdp_is_up", return_value=True):
            self.assertIsNone(chrome.launch_chrome_with_user_profile(port=9999))
        self.popen.assert_not_called()

    def test_a_refresh_request_is_never_silently_swapped_for_another_combination(self):
        """Asking to refresh the copy is explicit; trying something else in
        its place would answer a different question than the one asked."""
        with self.outcomes(False):
            with self.assertRaises(RuntimeError):
                chrome.launch_chrome_with_user_profile(port=9999, wait_seconds=1,
                                                       refresh_profile=True)
        self.assertEqual(self.popen.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

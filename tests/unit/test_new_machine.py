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


if __name__ == "__main__":
    unittest.main(verbosity=2)

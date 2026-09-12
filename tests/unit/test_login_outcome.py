"""Offline tests for gmes.contracts.login.LoginOutcome and the pure-logic
parts of gmes.auth.login_flow that don't need a real browser.

gmes_login.py's bare OK=0/FAILED=1/REJECTED=2 constants only appear in
its main() - the CLI-driving sign-in retry loop, which is
application/sign_in_uc.py's job in a later migration phase, not
auth/login_flow.py or auth/session.py (neither of which ever touched
those bare ints in the original either). So this file tests the enum
itself plus what auth/login_flow.py actually ported, with the browser
calls (list_windows, evaluate) patched out.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.contracts import LoginAttempt, LoginOutcome  # noqa: E402
from gmes.auth import login_flow  # noqa: E402


class LoginOutcomeShape(unittest.TestCase):
    def test_three_distinct_members(self):
        members = {LoginOutcome.OK, LoginOutcome.FAILED, LoginOutcome.REJECTED}
        self.assertEqual(len(members), 3)

    def test_login_attempt_defaults(self):
        attempt = LoginAttempt(outcome=LoginOutcome.OK)
        self.assertEqual(attempt.detail, "")
        self.assertEqual(attempt.attempts_used, 1)

    def test_failed_is_not_rejected(self):
        # The whole point of the enum: these must never compare equal, or
        # a future caller could retry a REJECTED (terminal, account-lockout
        # risk) outcome by mistaking it for a FAILED (transient) one.
        self.assertNotEqual(LoginOutcome.FAILED, LoginOutcome.REJECTED)


class FindSsoWindow(unittest.TestCase):
    def test_picks_the_tab_whose_url_contains_the_sso_mark(self):
        tabs = [
            {"url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index.html"},
            {"url": "https://stseu.secsso.net/adfs/ls/?SAMLRequest=abc123"},
        ]
        with patch.object(login_flow, "list_windows", return_value=tabs):
            found = login_flow.find_sso_window()
        self.assertIs(found, tabs[1])

    def test_returns_none_when_no_tab_matches(self):
        tabs = [{"url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index.html"}]
        with patch.object(login_flow, "list_windows", return_value=tabs):
            self.assertIsNone(login_flow.find_sso_window())


class LoginError(unittest.TestCase):
    def test_returns_trimmed_text_when_found(self):
        with patch.object(login_flow, "evaluate",
                          return_value={"found": True, "text": "  Auth bad credentials  "}):
            self.assertEqual(login_flow.login_error(object()), "Auth bad credentials")

    def test_returns_empty_string_when_not_found(self):
        with patch.object(login_flow, "evaluate", return_value={"found": False}):
            self.assertEqual(login_flow.login_error(object()), "")

    def test_returns_empty_string_on_exception_rather_than_raising(self):
        with patch.object(login_flow, "evaluate", side_effect=RuntimeError("boom")):
            self.assertEqual(login_flow.login_error(object()), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

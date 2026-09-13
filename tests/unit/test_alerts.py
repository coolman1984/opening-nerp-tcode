"""A failure should be found the same night, not discovered from a log
nobody opens until morning - but only ever as a best-effort extra, never
as something that can turn a real result into a script error.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import alerts
from gmes.auth import credentials
from gmes.contracts import LoginAttempt, LoginOutcome, RunExecution, RunResult


def unconfigured():
    """Guarantee a clean environment regardless of what the real shell has set."""
    return patch.dict(os.environ, {}, clear=True)


class TemporaryRuntime(unittest.TestCase):
    """Isolates the DPAPI-backed alert credential store from real disk -
    it now lives under gmes_root(), the same as every other secret.

    Real Windows DPAPI is unavailable on the (Linux) test runner, exactly
    like the rest of this project's credential tests
    (test_auth_credentials.py); a reversible stand-in cipher is swapped in
    so save()/load() round-trip without touching ctypes.windll."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": directory.name}))
        self.enterContext(patch.object(
            credentials, "encrypt", side_effect=lambda data: bytes(byte ^ 0xA5 for byte in data)))
        self.enterContext(patch.object(
            credentials, "decrypt", side_effect=lambda data: bytes(byte ^ 0xA5 for byte in data)))


class ConfiguredTests(unittest.TestCase):
    def test_nothing_set_means_not_configured(self):
        with unconfigured():
            self.assertFalse(alerts.configured())

    def test_only_a_host_with_no_recipient_is_not_enough(self):
        with unconfigured(), patch.dict(os.environ, {"GMES_ALERT_SMTP_HOST": "mail.local"}):
            self.assertFalse(alerts.configured())

    def test_both_set_is_configured(self):
        with unconfigured(), patch.dict(os.environ, {"GMES_ALERT_SMTP_HOST": "mail.local",
                                                      "GMES_ALERT_TO": "ops@example.com"}):
            self.assertTrue(alerts.configured())


class NotifyTests(TemporaryRuntime):
    def configured_env(self, **extra):
        # Not clear=True: that would also erase the outer TemporaryRuntime's
        # patched LOCALAPPDATA, silently pointing the DPAPI credential
        # lookup at a completely different (real) directory mid-test.
        env = {"GMES_ALERT_SMTP_HOST": "mail.local", "GMES_ALERT_TO": "ops@example.com",
              "GMES_ALERT_SMTP_USER": "", "GMES_ALERT_SMTP_PASSWORD": ""}
        env.update(extra)
        return patch.dict(os.environ, env)

    def test_nothing_is_sent_when_not_configured(self):
        with unconfigured(), patch.object(alerts.smtplib, "SMTP") as smtp:
            self.assertFalse(alerts.notify("subject", "body"))
        smtp.assert_not_called()

    def test_a_configured_alert_is_sent_with_the_right_envelope(self):
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            self.assertTrue(alerts.notify("the subject", "the body"))
        sent = server.send_message.call_args.args[0]
        self.assertEqual(sent["Subject"], "the subject")
        self.assertEqual(sent["To"], "ops@example.com")
        self.assertEqual(sent.get_content().strip(), "the body")

    def test_ehlo_is_sent_before_asking_what_the_server_supports(self):
        """`has_extn` only reports what a PRIOR ehlo/helo response listed -
        asking before calling ehlo() always came back empty, so STARTTLS
        was never actually reached whatever the server offered."""
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        self.assertGreaterEqual(server.ehlo.call_count, 1)
        ehlo_order = [call[0] for call in server.method_calls].index("ehlo")
        has_extn_order = [call[0] for call in server.method_calls].index("has_extn")
        self.assertLess(ehlo_order, has_extn_order)

    def test_starttls_is_used_when_the_server_offers_it_and_ehlo_repeats_after(self):
        server = Mock()
        server.has_extn.return_value = True
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.starttls.assert_called_once()
        # RFC 3207: the extension list must be re-read after STARTTLS.
        self.assertEqual(server.ehlo.call_count, 2)

    def test_starttls_is_skipped_when_the_server_does_not_offer_it(self):
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.starttls.assert_not_called()

    def test_no_saved_credential_means_no_login_attempt(self):
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.login.assert_not_called()

    def test_a_saved_dpapi_credential_is_used_to_log_in_over_an_encrypted_channel(self):
        credentials.save("bot", "secret", path=alerts.alert_credentials_path())
        server = Mock()
        server.has_extn.return_value = True   # STARTTLS offered
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.login.assert_called_once_with("bot", "secret")

    def test_a_saved_credential_is_never_sent_over_an_unencrypted_channel(self):
        """A real secret must never go on the wire in the clear - refuse
        the whole alert instead (HISTORY.md Phase 55.1)."""
        credentials.save("bot", "secret", path=alerts.alert_credentials_path())
        server = Mock()
        server.has_extn.return_value = False   # no STARTTLS offered
        logged = []
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            self.assertFalse(alerts.notify("s", "b", log=logged.append))
        server.login.assert_not_called()
        server.send_message.assert_not_called()
        self.assertTrue(any("unencrypted" in line for line in logged))

    def test_the_alert_credential_is_never_read_from_an_environment_variable(self):
        """CLAUDE.md 2.2: no passwords anywhere but the DPAPI store - not
        even a secondary one, and not even via os.environ."""
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(GMES_ALERT_SMTP_USER="bot",
                                 GMES_ALERT_SMTP_PASSWORD="from-the-environment"), \
             patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.login.assert_not_called()   # nothing was ever saved to DPAPI

    def test_a_password_is_never_present_in_the_message_or_a_log_call(self):
        credentials.save("bot", "do-not-leak-me", path=alerts.alert_credentials_path())
        server = Mock()
        server.has_extn.return_value = True   # encrypted, so login is actually attempted
        logged = []
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b", log=logged.append)
        server.login.assert_called_once_with("bot", "do-not-leak-me")
        sent = server.send_message.call_args.args[0]
        self.assertNotIn("do-not-leak-me", str(sent))
        self.assertNotIn("do-not-leak-me", " ".join(logged))

    def test_a_mail_server_that_is_unreachable_never_raises(self):
        with self.configured_env(), \
             patch.object(alerts.smtplib, "SMTP", side_effect=OSError("connection refused")):
            self.assertFalse(alerts.notify("s", "b", log=lambda _: None))

    def test_an_unreachable_server_is_reported_once_in_the_log(self):
        logged = []
        with self.configured_env(), \
             patch.object(alerts.smtplib, "SMTP", side_effect=OSError("connection refused")):
            alerts.notify("s", "b", log=logged.append)
        self.assertTrue(any("could not send" in line for line in logged))


class ReportBatchTests(unittest.TestCase):
    def test_a_fully_successful_batch_sends_nothing(self):
        execution = RunExecution(LoginAttempt(LoginOutcome.OK),
                                 (RunResult("A", ok=True, rows=5),))
        with patch.object(alerts, "notify") as notify:
            self.assertFalse(alerts.report_batch(execution))
        notify.assert_not_called()

    def test_a_sign_in_failure_is_reported_with_its_own_detail(self):
        execution = RunExecution(LoginAttempt(LoginOutcome.REJECTED, "no saved credentials"))
        with patch.object(alerts, "notify", return_value=True) as notify:
            alerts.report_batch(execution)
        subject, body = notify.call_args.args[:2]
        self.assertIn("no saved credentials", subject)

    def test_a_batch_with_a_failed_screen_lists_it_by_name(self):
        execution = RunExecution(LoginAttempt(LoginOutcome.OK),
                                 (RunResult("A", ok=True, rows=5),
                                  RunResult("B", ok=False, error="no complete .xlsx")))
        with patch.object(alerts, "notify", return_value=True) as notify:
            alerts.report_batch(execution)
        subject, body = notify.call_args.args[:2]
        self.assertIn("B", subject)
        self.assertIn("1 of 2", subject)
        self.assertIn("no complete .xlsx", body)
        self.assertIn("A", body)   # the successful screen is listed too

    def test_the_body_points_at_the_log_file(self):
        execution = RunExecution(LoginAttempt(LoginOutcome.OK),
                                 (RunResult("A", ok=False, error="x"),))
        with patch.object(alerts, "notify", return_value=True) as notify:
            alerts.report_batch(execution)
        body = notify.call_args.args[1]
        self.assertIn(str(alerts.log_path()), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)

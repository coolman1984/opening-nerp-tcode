"""A failure should be found the same night, not discovered from a log
nobody opens until morning - but only ever as a best-effort extra, never
as something that can turn a real result into a script error.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.application import alerts
from gmes.contracts import LoginAttempt, LoginOutcome, RunExecution, RunResult


def unconfigured():
    """Guarantee a clean environment regardless of what the real shell has set."""
    return patch.dict(os.environ, {}, clear=True)


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


class NotifyTests(unittest.TestCase):
    def configured_env(self, **extra):
        env = {"GMES_ALERT_SMTP_HOST": "mail.local", "GMES_ALERT_TO": "ops@example.com"}
        env.update(extra)
        return patch.dict(os.environ, env, clear=True)

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

    def test_starttls_is_used_when_the_server_offers_it(self):
        server = Mock()
        server.has_extn.return_value = True
        with self.configured_env(), patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.starttls.assert_called_once()

    def test_credentials_are_used_only_when_both_are_present(self):
        server = Mock()
        server.has_extn.return_value = False
        with self.configured_env(GMES_ALERT_SMTP_USER="bot"), \
             patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.login.assert_not_called()

        with self.configured_env(GMES_ALERT_SMTP_USER="bot", GMES_ALERT_SMTP_PASSWORD="secret"), \
             patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b")
        server.login.assert_called_once_with("bot", "secret")

    def test_a_password_is_never_present_in_the_message_or_a_log_call(self):
        server = Mock()
        server.has_extn.return_value = False
        logged = []
        with self.configured_env(GMES_ALERT_SMTP_USER="bot",
                                 GMES_ALERT_SMTP_PASSWORD="do-not-leak-me"), \
             patch.object(alerts.smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            alerts.notify("s", "b", log=logged.append)
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

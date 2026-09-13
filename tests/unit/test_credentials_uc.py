"""Credential setup never exposes secrets beyond the DPAPI writer."""
import unittest
from unittest.mock import patch

from gmes.application import credentials_uc


class CredentialSetupTests(unittest.TestCase):
    def test_set_saves_only_a_complete_prompt_result(self):
        with patch.object(credentials_uc.credentials, "ask_credentials", return_value=("test-user", "test-password")), \
             patch.object(credentials_uc.credentials, "save", return_value="opaque-path") as save:
            result = credentials_uc.set_credentials()
        self.assertTrue(result.saved)
        self.assertNotIn("test-user", result.message)
        self.assertNotIn("test-password", result.message)
        save.assert_called_once_with("test-user", "test-password")

    def test_cancelled_prompt_leaves_store_unchanged(self):
        with patch.object(credentials_uc.credentials, "ask_credentials", return_value=(None, None)), \
             patch.object(credentials_uc.credentials, "save") as save:
            result = credentials_uc.set_credentials()
        self.assertFalse(result.saved)
        save.assert_not_called()


class AlertCredentialSetupTests(unittest.TestCase):
    """The SMTP secret for alerts.py goes through the SAME DPAPI writer as
    the G-MES login, but to its OWN file - never the G-MES store, never a
    plain environment variable (CLAUDE.md 2.2)."""

    def test_set_saves_to_the_separate_alert_path_never_the_gmes_one(self):
        with patch.object(credentials_uc.credentials, "ask_credentials",
                          return_value=("smtp-bot", "smtp-secret")) as ask, \
             patch.object(credentials_uc.credentials, "save", return_value="opaque-path") as save:
            result = credentials_uc.set_alert_credentials()
        self.assertTrue(result.saved)
        self.assertNotIn("smtp-bot", result.message)
        self.assertNotIn("smtp-secret", result.message)
        used_path = save.call_args.kwargs.get("path", save.call_args.args[-1]
                                              if len(save.call_args.args) > 2 else None)
        self.assertEqual(used_path, credentials_uc.alert_credentials_path())
        self.assertNotEqual(credentials_uc.alert_credentials_path(),
                            credentials_uc.credentials.credentials_path())
        ask.assert_called_once()

    def test_a_cancelled_prompt_saves_nothing(self):
        with patch.object(credentials_uc.credentials, "ask_credentials", return_value=(None, None)), \
             patch.object(credentials_uc.credentials, "save") as save:
            result = credentials_uc.set_alert_credentials()
        self.assertFalse(result.saved)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()

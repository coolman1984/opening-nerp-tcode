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


if __name__ == "__main__":
    unittest.main()

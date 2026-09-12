"""Offline tests for gmes.auth.credentials - the DPAPI-backed store.

Uses an obviously-fake password ("test-password-not-real-123") so that
even unittest's default assertEqual failure message (which DOES print
both values on a mismatch - unavoidable stdlib behaviour) can never be
mistaken for a real credential. Never touches the real
%LOCALAPPDATA%\\GMES or %LOCALAPPDATA%\\GMES_Automation store - LOCALAPPDATA
is patched to a throwaway temp directory for every test here.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes.auth import credentials  # noqa: E402

FAKE_USER = "test.user"
FAKE_PASSWORD = "test-password-not-real-123"


class WithFakeLocalAppData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch = patch.dict(os.environ, {"LOCALAPPDATA": self._tmp.name})
        self._patch.start()
        self.addCleanup(self._patch.stop)


class EncryptDecryptRoundTrip(WithFakeLocalAppData):
    def test_round_trips_arbitrary_bytes(self):
        blob = credentials.encrypt(b"arbitrary-bytes-not-a-password")
        self.assertEqual(credentials.decrypt(blob), b"arbitrary-bytes-not-a-password")

    def test_encrypted_blob_does_not_contain_the_plaintext(self):
        blob = credentials.encrypt(FAKE_PASSWORD.encode("utf-8"))
        self.assertNotIn(FAKE_PASSWORD.encode("utf-8"), blob)


class SaveLoadClear(WithFakeLocalAppData):
    def test_load_before_save_returns_none_none(self):
        self.assertEqual(credentials.load(), (None, None))

    def test_save_then_load_round_trips(self):
        credentials.save(FAKE_USER, FAKE_PASSWORD)
        user, password = credentials.load()
        self.assertEqual(user, FAKE_USER)
        self.assertEqual(password, FAKE_PASSWORD)

    def test_save_writes_under_the_new_unified_path_not_the_legacy_one(self):
        from gmes import paths
        credentials.save(FAKE_USER, FAKE_PASSWORD)
        self.assertTrue(paths.credentials_path().is_file())
        self.assertFalse(paths.legacy_credentials_path().exists())

    def test_clear_removes_the_store_and_reports_whether_it_existed(self):
        credentials.save(FAKE_USER, FAKE_PASSWORD)
        self.assertTrue(credentials.clear())
        self.assertEqual(credentials.load(), (None, None))
        self.assertFalse(credentials.clear())   # nothing left to clear


if __name__ == "__main__":
    unittest.main(verbosity=2)

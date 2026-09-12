"""Offline tests for gmes.paths - the %LOCALAPPDATA%\\GMES resolver."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))

from gmes import paths  # noqa: E402


class WithFakeLocalAppData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch = patch.dict(os.environ, {"LOCALAPPDATA": self._tmp.name})
        self._patch.start()
        self.addCleanup(self._patch.stop)


class DirectoryResolution(WithFakeLocalAppData):
    def test_each_dir_is_under_the_fake_root_and_created(self):
        root = Path(self._tmp.name) / "GMES"
        for fn, expected in (
            (paths.profiles_dir, root / "profiles"),
            (paths.logs_dir, root / "logs"),
            (paths.screenshots_dir, root / "screenshots"),
            (paths.cache_dir, root / "cache"),
            (paths.nexacro_cache_dir, root / "cache" / "nexacro"),
            (paths.config_dir, root / "config"),
            (paths.evidence_dir, root / "evidence"),
            (paths.exports_dir, root / "exports"),
        ):
            got = fn()
            self.assertEqual(got, expected)
            self.assertTrue(got.is_dir(), f"{fn.__name__} did not create its directory")

    def test_credentials_path_is_a_file_under_the_root_not_a_created_dir(self):
        got = paths.credentials_path()
        self.assertEqual(got, Path(self._tmp.name) / "GMES" / "credentials.dat")
        self.assertFalse(got.exists())          # the file itself is not created
        self.assertTrue(got.parent.is_dir())    # but its parent is

    def test_config_path_sits_under_config_dir(self):
        self.assertEqual(paths.config_path(), paths.config_dir() / "settings.json")

    def test_log_path_is_under_the_runtime_tree(self):
        self.assertEqual(paths.log_path("run"), paths.logs_dir() / "run.log")
        with self.assertRaises(ValueError):
            paths.log_path("../outside")


class LegacyCredentialMigration(WithFakeLocalAppData):
    def _write_legacy(self, content=b"legacy-blob"):
        legacy = paths.legacy_credentials_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(content)
        return legacy

    def test_copies_when_new_is_absent_and_legacy_exists(self):
        legacy = self._write_legacy(b"secret-bytes")
        message = paths.migrate_legacy_credentials()
        self.assertIsNotNone(message)
        new_path = paths.credentials_path()
        self.assertTrue(new_path.exists())
        self.assertEqual(new_path.read_bytes(), b"secret-bytes")
        # never deletes the original
        self.assertTrue(legacy.exists())
        self.assertEqual(legacy.read_bytes(), b"secret-bytes")

    def test_does_nothing_when_new_path_already_has_a_file(self):
        self._write_legacy(b"old-secret")
        new_path = paths.credentials_path()
        new_path.write_bytes(b"already-here")
        message = paths.migrate_legacy_credentials()
        self.assertIsNone(message)
        self.assertEqual(new_path.read_bytes(), b"already-here")  # not overwritten

    def test_does_nothing_when_neither_path_has_anything(self):
        self.assertIsNone(paths.migrate_legacy_credentials())
        self.assertFalse(paths.credentials_path().exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

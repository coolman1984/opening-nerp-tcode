"""Runtime evidence must never default to the repository or current directory."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RuntimeStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_failure_screenshot_defaults_under_localappdata_gmes(self):
        from gmes.browser import screenshots
        with patch.object(screenshots, "capture_screenshot", side_effect=lambda path: path):
            path = screenshots.screenshot_on_failure("failure")
        self.assertEqual(Path(path).parent, Path(self.tmp.name) / "GMES" / "screenshots")

    def test_relative_named_screenshot_is_redirected_under_runtime_state(self):
        from gmes.browser import screenshots
        expected = Path(self.tmp.name) / "GMES" / "screenshots" / "runtime_ready.png"
        self.assertEqual(screenshots._runtime_screenshot_path("runtime_ready.png"), expected)
        with patch.object(screenshots, "get_page_tab", return_value=None):
            self.assertIsNone(screenshots.capture_screenshot("runtime_ready.png"))

    def test_chrome_copy_remains_the_established_copy_of_default_profile(self):
        from gmes.browser import chrome
        self.assertEqual(Path(chrome.working_profile_dir()),
                         Path(self.tmp.name) / "Google" / "Chrome" / "CDP Profile")

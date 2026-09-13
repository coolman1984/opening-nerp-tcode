"""capture_screenshot() must target the actual G-MES tab, not whichever
page-type CDP target happens to be listed first.

Pinned live (HISTORY.md Phase 56.4): a leftover AD SSO popup left open by
an earlier diagnostic run meant `screenshot_on_failure()` silently
screenshotted the ADFS page instead of G-MES's own rejected login form -
a diagnostic that shows the wrong page reads as evidence and is not.
"""
import unittest
from unittest.mock import patch

from gmes.browser import screenshots


class ScreenshotTargetTests(unittest.TestCase):
    def test_capture_screenshot_prefers_the_gmes_tab_over_other_pages(self):
        with patch.object(screenshots, "get_page_tab") as get_page_tab, \
             patch.object(screenshots, "connect"), \
             patch.object(screenshots, "send", return_value={"result": {"data": ""}}), \
             patch.object(screenshots, "_runtime_screenshot_path", return_value="/tmp/x.png"), \
             patch("builtins.open", unittest.mock.mock_open()):
            get_page_tab.return_value = {"webSocketDebuggerUrl": "ws://x"}
            screenshots.capture_screenshot("gmes_failure.png")

        self.assertEqual(get_page_tab.call_args.kwargs["prefer_url_substring"],
                          "seegmes4.sec.samsung.net")


if __name__ == "__main__":
    unittest.main()

"""Chrome/CDP transport, forked from cdp_common.py's shared (non-N-ERP) subset.

No wait_for_busy_indicator_clear() / waits.py here: the only generic
busy-wait helper in cdp_common.py polls an SAP-shell-specific element id
("hiddenLoadingToolbarButton") that G-MES never uses. G-MES's own
settle-detection is Nexacro-dataset-based (poll_inquiry, HISTORY.md Phase
7.3/10.4) and belongs in screens/verification.py (a later migration
phase), not a generic browser primitive.
"""

from .cdp import (
    CDP_HOST, CDP_PORT, cdp_is_up, connect, evaluate, get_page_tab, get_tabs,
    ipv4, list_windows, navigate_page, next_id, send,
)
from .chrome import (
    chrome_is_running, clone_user_profile, close_browser,
    default_user_profile_dir, find_chrome, launch_chrome_with_user_profile,
    working_profile_dir,
)
# LAST_CHROME_PROCESS is deliberately NOT re-exported here: it is a
# module-level global that launch_chrome_with_user_profile() reassigns via
# `global LAST_CHROME_PROCESS` inside chrome.py. A `from .chrome import
# LAST_CHROME_PROCESS` binding here would freeze at whatever value it held
# at package-import time (None) and never see later reassignments - the
# same "from X import Y" staleness trap the original cdp_common.py callers
# avoided by always writing `cdp_common.LAST_CHROME_PROCESS`, never
# importing the name directly. Callers here must do the same:
# `gmes.browser.chrome.LAST_CHROME_PROCESS`.
from .interaction import (
    JS_IS_VISIBLE, JS_SET_VALUE, click_element_by_rect, dispatch_key_combo,
)
from .screenshots import capture_screenshot, screenshot_on_failure

__all__ = [
    "CDP_HOST", "CDP_PORT", "cdp_is_up", "connect", "evaluate", "get_page_tab",
    "get_tabs", "ipv4", "list_windows", "navigate_page", "next_id", "send",
    "chrome_is_running", "clone_user_profile",
    "close_browser", "default_user_profile_dir", "find_chrome",
    "launch_chrome_with_user_profile", "working_profile_dir",
    "JS_IS_VISIBLE", "JS_SET_VALUE", "click_element_by_rect",
    "dispatch_key_combo", "capture_screenshot", "screenshot_on_failure",
]

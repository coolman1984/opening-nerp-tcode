"""Nexacro-application primitives: DOM lookup, popups, app/storage state.

Only the subset the sign-in flow needs exists yet (Phase 4 of the
migration folded this forward from its originally planned Phase 5a).
find_elements/click_control/screen_report (pattern-based lookup used by
screen discovery, not login) land with the rest of nexacro/ in the
discovery/screens phase.
"""
from .app_state import app_is_built, prune_nexacro_cache, storage_state
from .dom import click_by_id, js_find_by_id, set_value_by_id
from .js_snippets import JS_IS_VISIBLE, JS_SET_VALUE
from .popups import close_child_popups, close_popups_when_they_appear, find_child_popups

__all__ = [
    "app_is_built", "prune_nexacro_cache", "storage_state",
    "click_by_id", "js_find_by_id", "set_value_by_id",
    "JS_IS_VISIBLE", "JS_SET_VALUE",
    "close_child_popups", "close_popups_when_they_appear", "find_child_popups",
]

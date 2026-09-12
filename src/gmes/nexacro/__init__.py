"""Nexacro-application primitives: DOM lookup, popups, app/storage state."""
from .app_state import app_is_built, prune_nexacro_cache, storage_state
from .dom import (
    click_by_id,
    click_control,
    find_elements,
    js_find_by_id,
    js_find_elements,
    set_value_by_id,
)
from .js_snippets import JS_IS_VISIBLE, JS_SET_VALUE
from .popups import close_child_popups, close_popups_when_they_appear, find_child_popups

__all__ = [
    "app_is_built", "prune_nexacro_cache", "storage_state",
    "click_by_id", "js_find_by_id", "set_value_by_id",
    "click_control", "find_elements", "js_find_elements",
    "JS_IS_VISIBLE", "JS_SET_VALUE",
    "close_child_popups", "close_popups_when_they_appear", "find_child_popups",
]

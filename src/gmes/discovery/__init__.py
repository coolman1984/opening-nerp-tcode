"""Screen discovery: reading what a screen offers, opening/activating it,
the catalogue search behind the top search box, and noticing when a
learned screen has changed.

Forked from gmes_core.py (discover/left_options/org_trees/Screen),
gmes_open_screen.py (catalogue) and gmes_profile.py (fingerprint/
describe_change) - Phase 5c of the standalone gmes.exe migration.
"""
from .catalogue import activate_screen, catalogue, open_screens
from .fingerprint import describe_change, fingerprint
from .screen import Screen, looks_like_a_screen_code, open_screen
from .screen_discovery import discover, left_options, org_trees

__all__ = [
    "discover", "left_options", "org_trees",
    "Screen", "open_screen", "looks_like_a_screen_code",
    "catalogue", "open_screens", "activate_screen",
    "fingerprint", "describe_change",
]

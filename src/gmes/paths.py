"""Single source of truth for the %LOCALAPPDATA%\\GMES runtime-state tree.

Nothing under here lives beside the executable: profiles, credentials,
logs, screenshots, cache and config all resolve through this module.
User exports (Excel/CSV) are NOT here - they stay in a user-selected
output folder, per the caller's own --output-dir.

Every *_dir() function creates the directory it names before returning
it, so a caller never has to remember to mkdir. Root resolution is a
function, not a module-level constant, so tests can monkeypatch
LOCALAPPDATA cleanly without reloading the module.

The Chrome CDP profile copy (%LOCALAPPDATA%\\Google\\Chrome\\CDP Profile,
see HISTORY.md Phase 4.1) is deliberately NOT under this tree and is not
managed here - it is large, tightly coupled to Chrome's own profile-dir
rules, and moving it buys no consistency benefit that matters to a user.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "GMES"
LEGACY_APP_NAME = "GMES_Automation"      # gmes_credentials.py's original STORE_DIR


def _local_app_data() -> Path:
    return Path(os.environ["LOCALAPPDATA"])


def gmes_root() -> Path:
    return _local_app_data() / APP_NAME


def credentials_path() -> Path:
    root = gmes_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "credentials.dat"


def profiles_dir() -> Path:
    path = gmes_root() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = gmes_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshots_dir() -> Path:
    path = gmes_root() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = gmes_root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def nexacro_cache_dir() -> Path:
    path = cache_dir() / "nexacro"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    path = gmes_root() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "settings.json"


# ---------------------------------------------------------------------------
# Legacy migration - the credential store used to live under a differently
# named folder (GMES_Automation) written before this unified tree existed.
# ---------------------------------------------------------------------------

def legacy_credentials_path() -> Path:
    return _local_app_data() / LEGACY_APP_NAME / "credentials.dat"


def migrate_legacy_credentials() -> str | None:
    """Copy (never move) a legacy credential store into the new location.

    Returns a human-readable message describing what happened, or None
    if there was nothing to do - either the new path already has a file
    (never overwritten; it may be newer than the legacy one) or the
    legacy path has nothing either. The legacy file is left in place so
    a rollback never looks like data loss (see the migration plan)."""
    new_path = credentials_path()
    if new_path.exists():
        return None
    legacy_path = legacy_credentials_path()
    if not legacy_path.exists():
        return None
    shutil.copy2(legacy_path, new_path)
    return (f"copied the saved GMES login from the old location "
            f"({legacy_path}) to {new_path}")

"""JSON persistence for safe, per-user G-MES screen profiles."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from gmes.discovery.fingerprint import fingerprint
from gmes.paths import profiles_dir
from gmes.profiles.drift import _merge_values
from gmes.profiles.refs import field_ref, grid_ref, tree_ref


def _normalised_code(code: str) -> str:
    code = str(code).strip().upper()
    if not code or any(part in code for part in ("/", "\\", ".")):
        raise ValueError("profile screen code must be a plain screen identifier")
    return code


def _path_for(code: str) -> Path:
    return profiles_dir() / f"{_normalised_code(code)}.json"


def load(code):
    """Load one profile, returning None for missing or malformed JSON."""
    try:
        with _path_for(code).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def known():
    """Return valid saved profiles, newest first."""
    profiles = []
    try:
        paths = profiles_dir().glob("*.json")
    except OSError:
        return profiles
    for path in paths:
        data = load(path.stem)
        if data:
            profiles.append(data)
    profiles.sort(key=lambda profile: profile.get("learned", ""), reverse=True)
    return profiles


def forget(code):
    """Remove one known profile.  A missing profile is a safe no-op."""
    try:
        _path_for(code).unlink()
        return True
    except OSError:
        return False


def save(code, title, menu_id, info, from_ref=None, to_ref=None,
         division=None, grid=None, rows=0, command="", options=(), values=None):
    """Persist only a successful run's allowlisted replay information.

    The caller is responsible for calling this only after query, verification,
    and export have all completed.  This function never serializes ``info``;
    it uses it solely to calculate the already-tested fingerprint.
    """
    screen = _normalised_code(code)
    path = _path_for(screen)
    data = {
        "screen": screen,
        "title": str(title or ""),
        "menuId": str(menu_id or ""),
        "learned": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fingerprint": fingerprint(info),
        "from": field_ref(from_ref),
        "to": field_ref(to_ref),
        "division": tree_ref(division) if division else None,
        "grid": grid_ref(grid),
        "options": [str(option) for option in options],
        "values": _merge_values(load(screen), values),
        "proved": {"rows": rows, "command": str(command or "")},
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return path


__all__ = ["forget", "known", "load", "save"]

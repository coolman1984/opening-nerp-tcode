"""Safe profile replay checks and remembered run values.

Fingerprint comparison remains in discovery.fingerprint: it is already the
tested source of truth for screen shape.  This module adds profile-specific
value recovery and exposes that comparison without attempting any repair.
"""
from __future__ import annotations

import re

from gmes.contracts import ProfileDrift
from gmes.discovery.fingerprint import _still_there, describe_change, fingerprint


def last_values(profile):
    """Return values remembered by a profile, recovering old command-only files."""
    profile = profile or {}
    values = dict(profile.get("values") or {})
    if any(value for key, value in values.items() if key != "sets") or values.get("sets"):
        return values

    command = (profile.get("proved") or {}).get("command", "")
    recovered = {}
    for flag, key in (("--division", "division"), ("--from", "from"),
                      ("--to", "to")):
        found = re.search(re.escape(flag) + r"\s+(\S+)", command)
        if found and found.group(1) not in ("None", "none", ""):
            recovered[key] = found.group(1)
    if recovered:
        recovered.setdefault("sets", {})
        return recovered
    return values


def _merge_values(previous, fresh):
    """Keep last non-empty answers; a blank run must never erase memory."""
    merged = dict(last_values(previous or {}))
    for key, value in (fresh or {}).items():
        if key == "sets":
            if value:
                merged["sets"] = dict(value)
            continue
        if str(value or "").strip():
            merged[key] = value
    merged.setdefault("sets", {})
    return merged


def detect_drift(profile, info) -> ProfileDrift:
    """Report drift; callers must rediscover rather than repair silently."""
    problems = tuple(describe_change(profile, info))
    return ProfileDrift(changed=bool(problems), problems=problems)


__all__ = [
    "_merge_values", "_still_there", "describe_change", "detect_drift",
    "fingerprint", "last_values",
]

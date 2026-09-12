"""The only discovered-reference shapes permitted in a saved profile.

Profiles name durable Nexacro concepts; they never capture a rendered rect,
generated instance id, dataset row, session token, or credential.  Keep this
allowlist small so adding a field requires an explicit security decision.
"""
from __future__ import annotations

from collections.abc import Mapping


def _value(reference, name: str) -> str:
    if isinstance(reference, Mapping):
        return str(reference.get(name, "") or "")
    return str(getattr(reference, name, "") or "")


def field_ref(flt):
    """Return a persisted filter reference without its live value or id."""
    if not flt:
        return None
    return {name: _value(flt, name)
            for name in ("dataset", "column", "control", "form", "label")}


def grid_ref(grid):
    """Return a persisted grid reference without runtime geometry or rows."""
    if not grid:
        return None
    return {name: _value(grid, name) for name in ("name", "dataset", "form")}


def tree_ref(form, dataset=None, entry=None):
    """Return a persisted tree entry by its stable form/dataset/name tuple.

    Accepting a discovered TreeRef as the sole argument keeps the typed
    standalone API convenient while preserving the legacy three-argument
    caller shape.
    """
    if dataset is None and entry is None and not isinstance(form, str):
        reference = form
        return {name: _value(reference, name) for name in ("form", "dataset", "entry")}
    return {"form": str(form or ""), "dataset": str(dataset or ""),
            "entry": str(entry or "")}

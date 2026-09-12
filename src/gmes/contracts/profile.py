"""What gmes_profile.py remembers about a screen after a run that
actually worked - never coordinates, window ids or dataset contents.
See gmes_profile.py's module docstring for the full reasoning.

`from_ref`/`to_ref` hold the JSON keys "from"/"to" (both Python
keywords-adjacent, `from` literally is one) - profiles/store.py maps
`from_ref` <-> "from" and `to_ref` <-> "to" when it (de)serializes this
to/from the on-disk JSON in a later phase. Nothing here does that
mapping yet; this is only the shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gmes.contracts.screen import FilterRef, GridRef


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    screen: str
    title: str = ""
    menu_id: str = ""
    learned: str = ""
    fingerprint: str = ""
    from_ref: FilterRef | None = None
    to_ref: FilterRef | None = None
    division: str | None = None
    grid: GridRef | None = None
    options: tuple[str, ...] = ()
    values: dict[str, object] = field(default_factory=dict)
    proved: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileDrift:
    """Replaces describe_change()'s bare list[str] of problems.

    `changed` is true whenever `problems` is non-empty; kept as an
    explicit field (rather than computed) so a caller doesn't have to
    remember that convention, and so it stays correct even where a
    caller wants to record "no problems, but not yet checked" some day."""
    changed: bool
    problems: tuple[str, ...] = ()

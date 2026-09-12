"""Typed shapes for what a G-MES screen looks like once discovered.

These mirror the real dicts produced by gmes_core.py's JS_DISCOVER,
JS_LEFT_OPTIONS and JS_ORG_TREES (and persisted by gmes_profile.py's
field_ref/grid_ref/tree_ref) field-for-field - no renamed keys - so a
later phase can swap the dict-returning JS-eval call sites for these
without translating shapes at the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FilterRef:
    """One discovered (or remembered) filter control.

    Bound filters carry `dataset`/`column` (settable through the Nexacro
    dataset); unbound ones carry only `control`/`form`/`id` and are typed
    into with real key events instead. `bound` tells you which."""
    dataset: str
    column: str
    control: str
    label: str = ""
    form: str = ""
    value: str = ""
    visible: bool = False
    kind: str = ""
    id: str = ""
    bound: bool = True


@dataclass(frozen=True, slots=True)
class GridRef:
    """A candidate result grid."""
    name: str
    dataset: str
    form: str = ""
    area: int = 0
    visible: bool = False
    row_count_hint: int = 0


@dataclass(frozen=True, slots=True)
class TreeRef:
    """A category tree (Org/Prod/Fac/Proc), found by shape
    (commonName + _checked columns), not by name.

    `names`/`checked`/`rows`/`settable` come from live discovery
    (org_trees()). `entry` is populated only on a persisted reference
    (gmes_profile.tree_ref) - the single name a profile recorded as the
    one that worked, re-verified against `names` before being trusted."""
    form: str
    dataset: str
    rows: int = 0
    settable: bool = True
    names: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    entry: str = ""


@dataclass(frozen=True, slots=True)
class OptionRef:
    """A left-panel option (Plan Date/Create Date, PLANT/STD, Quick View...).

    `state` is Nexacro's own reported state string ('selected',
    'not selected', 'checked', 'unchecked', 'unknown'); `selected` is a
    convenience view over it, not a second source of truth."""
    label: str
    id: str = ""
    cls: str = ""
    state: str = "unknown"
    kind: str = ""
    x: float = 0.0
    y: float = 0.0

    @property
    def selected(self) -> bool:
        return self.state in ("selected", "checked")


@dataclass(frozen=True, slots=True)
class QuickViewRef:
    """A Quick View entry - a shortcut to a DIFFERENT screen, never a filter.

    See HISTORY.md Phase 27 / GMES_SKILL #46: this renders as a Grid, so
    the left-panel option scan never sees it; it needs its own shape."""
    screen: str
    name: str = ""
    active: bool = False


@dataclass(frozen=True, slots=True)
class ScreenInfo:
    """What discover() returns for one screen: everything a run can act on."""
    code: str
    title: str = ""
    window: str = ""
    filters: tuple[FilterRef, ...] = ()
    unbound: tuple[FilterRef, ...] = ()
    grids: tuple[GridRef, ...] = ()
    trees: tuple[TreeRef, ...] = ()
    options: tuple[OptionRef, ...] = ()
    quick_views: tuple[QuickViewRef, ...] = ()
    has_inquiry: bool = False
    has_excel: bool = False

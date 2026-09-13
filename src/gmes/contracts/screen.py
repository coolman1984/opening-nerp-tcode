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
    """What discover() returns for one screen: everything a run can act on.

    `datasets` is discover()'s own diagnostic map of every dataset found on
    the work window (name -> {rows, cols, form}) - not consumed by any
    decision in screens/ or discovery/ today, but part of the real
    JS_DISCOVER response and kept here rather than silently dropped, per
    this project's rule that a cap or omission must never hide discovered
    data (CLAUDE.md 4.5)."""
    code: str
    title: str = ""
    window: str = ""
    filters: tuple[FilterRef, ...] = ()
    unbound: tuple[FilterRef, ...] = ()
    grids: tuple[GridRef, ...] = ()
    trees: tuple[TreeRef, ...] = ()
    options: tuple[OptionRef, ...] = ()
    quick_views: tuple[QuickViewRef, ...] = ()
    datasets: dict = field(default_factory=dict)
    has_inquiry: bool = False
    has_excel: bool = False


@dataclass(frozen=True, slots=True)
class ScreenPreview:
    """Every choice one live screen offers, read before anything is applied.

    This exists so an operator is never asked to name a filter, an option or
    a division from memory. The guided workflow used to ask "extra filters as
    Name=Value" against a blank prompt: the screen knew its own answer the
    whole time, and the person in front of it had to guess the spelling of a
    column they could see on screen.

    Presentation is the caller's business - this carries what was found, in
    the order the screen reports it, with nothing truncated (CLAUDE.md 4.5)."""
    code: str
    title: str = ""
    filters: tuple[FilterRef, ...] = ()
    unbound: tuple[FilterRef, ...] = ()
    options: tuple[OptionRef, ...] = ()
    trees: tuple[TreeRef, ...] = ()
    quick_views: tuple[QuickViewRef, ...] = ()
    grids: tuple[GridRef, ...] = ()
    date_columns: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def settable(self) -> tuple[FilterRef, ...]:
        """Every control a value can be put into, bound or typed."""
        return self.filters + self.unbound

    @property
    def divisions(self) -> tuple[str, ...]:
        """Names that can actually be ticked, across every tickable tree.

        A name appearing in more than one tree is listed once; which tree it
        comes from is decided at run time by the data, not here."""
        names = {name for tree in self.trees if tree.settable for name in tree.names}
        return tuple(sorted(names))

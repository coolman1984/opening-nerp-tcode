"""Date parsing/matching and filter resolution - pure logic, no browser.

Forked from gmes_core.py. Every function here takes typed
`gmes.contracts.screen` objects (ScreenInfo/FilterRef) instead of the
loose dicts gmes_core.py passes around: discovery/screen_discovery.py
builds these from the raw JS_DISCOVER response once, and everything
downstream works with real attributes instead of `.get("column")`.
"""
import re
from datetime import datetime

from .grids import digits_only


def normalise_date(value):
    """Accept the ways people actually type a date; return G-MES's YYYYMMDD.

    A date typed as 2026-09-07 used to be written into the filter verbatim.
    G-MES stores YYYYMMDD, so the query ran against a value it could not
    interpret - no error, just a different answer. Anything not resolvable to
    a real calendar date is rejected rather than passed through and hoped
    for."""
    raw = (value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) != 8:
        raise ValueError(f"{value!r} is not a date. Use YYYYMMDD (20260907) or "
                         "YYYY-MM-DD (2026-09-07).")
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{value!r} is not a real calendar date.")
    return digits


def fit_date_to_field(yyyymmdd, current_value):
    """Match the width the field is actually storing.

    Not every G-MES period field holds a full date. Month fields (`stdYm`,
    `paramYm`) hold YYYYMM, and writing eight digits into one of those is the
    same class of mistake as writing "2026-09-07" into a YYYYMMDD field: it is
    accepted, and the query then answers something else. The width already in
    the box is the screen telling us which it wants."""
    existing = re.sub(r"[^\d]", "", (current_value or "").strip())
    if len(existing) == 6:
        return yyyymmdd[:6]
    if len(existing) == 4:
        return yyyymmdd[:4]
    return yyyymmdd


_DATE_WORDS = {"date", "dates", "ymd", "ym", "dt", "day", "period", "yyyymmdd"}
_FROM_WORDS = {"from", "start", "fr", "st", "begin"}
_TO_WORDS = {"end", "to", "thru", "through", "until", "last"}


def words(name):
    """Split an identifier into lowercase words: paramFromDate -> from, date.

    Substring matching is not safe here and produced a concrete trap:
    `paramVendorCode` contains "end", so a plain search classified a vendor
    code as the period's end date. Only whole camel-case or underscore words
    count."""
    parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", name or "")
    return {p.lower() for p in parts if p}


def is_date_field(flt):
    """Whether a discovered filter (a FilterRef) is a date or period field.

    Two signals, because neither holds alone. The column or label naming a
    date is the strong one. Failing that, Nexacro's own control type: a date
    is a masked edit or a calendar (`msk`, `cal`) holding four, six or eight
    digits. The shape of the value is deliberately NOT a signal on its own -
    plenty of eight-digit codes are not dates."""
    named = (words(flt.column) | words(flt.label)) & _DATE_WORDS
    if named:
        return True
    control = (flt.control or "").lower()
    value = digits_only(flt.value)
    return control.startswith(("msk", "cal")) and len(value) in (0, 4, 6, 8)


def date_targets(info):
    """Split the screen's date fields into (from, to, singles).

    The previous rule matched only `*fromdate*` / `*enddate*`, so a screen
    storing `paramYmd` or `stdYm` was reported as having no date filter at all
    and the run silently used whatever the screen had in it."""
    dates = [f for f in info.filters if is_date_field(f)]

    def tagged(vocab):
        for f in dates:
            if words(f.column) & vocab or words(f.control) & vocab:
                return f
        return None

    frm = tagged(_FROM_WORDS)
    to = tagged(_TO_WORDS)
    singles = [f for f in dates if f is not frm and f is not to]
    return frm, to, singles


def match_filter(info, key, include_unbound=True):
    """Resolve a name to a discovered control (a FilterRef).

    Accepts the column name, the visible label, or the control name - in that
    order of confidence - so a screen can be driven either the way it reads on
    screen or the way it is stored. Returns one control, a list when the name
    is ambiguous, or None."""
    pool = list(info.filters)
    if include_unbound:
        pool += list(info.unbound)
    k = key.strip().lower()

    for attr in ("column", "label", "control"):
        exact = [f for f in pool if (getattr(f, attr) or "").lower() == k]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return exact
    partial = [f for f in pool
               if k in (f.label or "").lower()
               or k in (f.column or "").lower()
               or k in (f.control or "").lower()]
    if len(partial) == 1:
        return partial[0]
    return partial or None

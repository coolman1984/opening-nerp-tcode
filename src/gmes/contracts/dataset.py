"""Shapes for reading a Nexacro Dataset a page at a time.

DatasetPage is what one offset/limit round trip over CDP returns.
DatasetResult is the fully-drained shape existing callers (CSV export,
a small `data read`) expect - assembled by concatenating DatasetPages,
never by asking the JS side to materialize everything in one call.
See gmes_data.py's js_read()/read_dataset() for the dict shape this
replaces.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DatasetPage:
    rows: tuple[dict, ...]
    offset: int
    returned: int
    total: int


@dataclass(frozen=True, slots=True)
class DatasetResult:
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    total: int
    path: str = ""
    file: str = ""

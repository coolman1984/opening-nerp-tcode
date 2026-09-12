"""Shapes for reading a Nexacro Dataset a page at a time.

DatasetPage is what one offset/limit round trip over CDP returns.
DatasetResult is the future fully-drained typed shape. Existing callers
still expect the legacy dictionary from ``query.dataset_reader.read_dataset``;
that boundary stays in place until ``screens.verification`` can migrate with
its callers. The reader does nevertheless assemble full reads from pages.
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

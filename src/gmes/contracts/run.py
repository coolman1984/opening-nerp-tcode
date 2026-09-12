"""What a run is asked to do, and what it proved.

Field names match gmes_core.run_screen()'s real keyword arguments and
its real result dict (`sets`, `grid_name`, `out_dir`, `screen`/`ok`/
`rows`/`files`/`applied`/`cleared`, ...) rather than inventing new
names, so a later phase can adapt the existing function to return one
of these without a translation layer at the boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Everything a caller can ask for on one screen. Dates are always
    already-decided YYYYMMDD strings - nothing in here calculates a date."""
    screen_code: str
    division: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sets: dict[str, str] = field(default_factory=dict)
    options: tuple[str, ...] = ()
    export: str = "both"          # "xlsx" | "csv" | "both" | "none"
    out_dir: str | None = None
    grid_name: str | None = None
    tree: str | None = None
    verify: tuple[str, str | None] | None = None     # (column, expected|None)
    dry_run: bool = False
    close_after: bool = False
    use_profile: bool = True


@dataclass(frozen=True, slots=True)
class RunResult:
    """What actually happened, proven rather than assumed."""
    screen: str
    ok: bool
    rows: int = 0
    files: tuple[str, ...] = ()
    error: str | None = None
    warnings: tuple[str, ...] = ()
    applied: dict[str, str] = field(default_factory=dict)
    options: tuple[str, ...] = ()
    cleared: tuple[str, ...] = ()
    dry_run: bool = False
    title: str = ""
    menu_id: str = ""
    window: str = ""
    duration_s: float = 0.0
    used_profile: bool = False
    grid: str = ""
    division: str = ""
    dates: tuple[tuple[str, str], ...] = ()
    verified: dict = field(default_factory=dict)
    result_dates: dict = field(default_factory=dict)
    excel_bytes: int = 0
    csv_rows: int = 0
    closed: bool | None = None
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class ExportResult:
    """The pairing download_excel()/check_download() produce together today."""
    path: str
    format: str            # "xlsx" | "csv"
    row_count: int
    checked: bool

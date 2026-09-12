"""Stream a discovered Nexacro dataset to a machine-readable CSV."""
import csv
import itertools
import os

from ..contracts import ExportResult
from ..query.dataset_reader import read_dataset_paged


def _exported_columns(row):
    """Keep Nexacro's dataset order while excluding its private columns."""
    return [column for column in row if not column.startswith("_")]


def write_csv(ws, screen_code, dataset, path):
    """Write pages in order, retaining every row with an exported value.

    The generic exporter cannot infer a business key such as ``poNo``.  It
    therefore drops only rows empty across all public columns and reports the
    number written as an ``ExportResult``.  Pages are consumed one at a time:
    no full data result is materialised in either browser JavaScript or Python.
    """
    pages = iter(read_dataset_paged(ws, screen_code, dataset))
    try:
        first_page = next(pages)
    except StopIteration:
        return ExportResult(path="", format="csv", row_count=0, checked=False)

    if not first_page.rows:
        return ExportResult(path="", format="csv", row_count=0, checked=False)
    columns = _exported_columns(first_page.rows[0])
    if not columns:
        return ExportResult(path="", format="csv", row_count=0, checked=False)

    written = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for page in itertools.chain((first_page,), pages):
            for row in page.rows:
                if not any(str(row.get(column) or "").strip() for column in columns):
                    continue
                writer.writerow(row)
                written += 1

    # A successful context-manager close plus an existing path is the useful
    # delivery check for CSV; Excel's 512-byte minimum is not valid for small
    # but legitimate CSV exports.
    return ExportResult(path=path, format="csv", row_count=written,
                        checked=os.path.isfile(path))

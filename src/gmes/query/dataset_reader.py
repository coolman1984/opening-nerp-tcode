"""Read a Nexacro dataset's rows without materialising a large result in JS.

Bounded reads retain gmes_data.py's single-CDP-call dictionary contract.
Unbounded reads page through the same JS helper and concatenate the pages
into that dictionary shape because ``screens.verification`` still consumes
it. ``DatasetResult`` remains deliberately unwired until its callers can
move together in a later phase.
"""
import json

from ..browser.cdp import evaluate
from ..contracts.dataset import DatasetPage
from .form_locator import JS_HELPERS


def js_read(screen_code, ds_name, limit, offset):
    return """
    (function() {
        %s
        const hit = _dataset(%s, %s);
        if (!hit) return JSON.stringify({found: false});
        const ds = hit.ds;
        const cols = [];
        const n = ds.getColCount();
        for (let i = 0; i < n; i++) cols.push(ds.getColID(i));

        const total = ds.getRowCount();
        const start = %d, limit = %d;
        const end = limit < 0 ? total : Math.min(total, start + limit);
        const rows = [];
        for (let r = start; r < end; r++) {
            const row = {};
            for (const c of cols) {
                let v;
                try { v = ds.getColumn(r, c); } catch (e) { v = null; }
                row[c] = (v === undefined || v === null) ? "" : String(v);
            }
            rows.push(row);
        }
        return JSON.stringify({found: true, path: hit.path, file: hit.file,
                               columns: cols, total: total, rows: rows});
    })()
    """ % (JS_HELPERS, json.dumps(screen_code), json.dumps(ds_name), offset, limit)


def _read_dataset_page_results(ws, screen_code, ds_name, page_size, offset=0):
    """Yield each raw CDP result with its page, retaining metadata for callers.

    The public generator intentionally exposes only ``DatasetPage``. The
    raw result travels alongside it here so the legacy dictionary-returning
    API can preserve ``found``, ``path``, ``file``, and ``columns`` without
    spending a separate metadata CDP call.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    running_offset = offset
    while True:
        result = evaluate(ws, js_read(screen_code, ds_name, page_size,
                                      running_offset))
        if not result.get("found"):
            yield result, None
            return

        rows = result.get("rows", [])
        returned = len(rows)
        if not returned:
            yield result, None
            return

        total = result.get("total", 0)
        yield result, DatasetPage(rows=tuple(rows), offset=running_offset,
                                  returned=returned, total=total)

        # A server can return fewer rows than requested. Advance only by what
        # arrived: using page_size would skip rows in that case.
        running_offset += returned
        if running_offset >= total:
            return


def read_dataset_paged(ws, screen_code, ds_name, page_size=300):
    """Yield ``DatasetPage`` values until the dataset is exhausted.

    Each round trip asks for one bounded slice. An empty first page (including
    an empty or missing dataset) yields nothing, so callers terminate without
    needing browser-specific sentinel handling.
    """
    for _result, page in _read_dataset_page_results(
            ws, screen_code, ds_name, page_size):
        if page is not None:
            yield page


def read_dataset(ws, screen_code, ds_name, limit=-1, offset=0):
    """Return the legacy dictionary result, paging only unbounded reads."""
    if limit >= 0:
        # Callers use small/zero limits for verification and polling. Their
        # one-call behavior is part of the existing contract.
        return evaluate(ws, js_read(screen_code, ds_name, limit, offset))

    first_result = None
    rows = []
    for result, page in _read_dataset_page_results(
            ws, screen_code, ds_name, page_size=300, offset=offset):
        if first_result is None:
            first_result = result
        if page is not None:
            rows.extend(page.rows)

    # _read_dataset_page_results always evaluates at least once.
    if not first_result.get("found"):
        return first_result
    full_result = dict(first_result)
    full_result["rows"] = rows
    return full_result

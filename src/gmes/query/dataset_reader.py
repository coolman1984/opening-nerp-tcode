"""Read a Nexacro dataset's rows.

Forked from gmes_data.py, pulled forward (see form_locator.py's
docstring for why). FAITHFUL PORT: `read_dataset(..., limit=-1)` still
materializes the whole result set in one JS `evaluate()` call / one CDP
message, exactly as gmes_data.py does today. The paged reader
(`read_dataset_paged`, chunked offset/limit round trips) is a deliberate
behavior change planned for its own dedicated commit with its own test
and HISTORY.md entry - not bundled into this port so that "what moved"
and "what changed" stay separable.
"""
import json

from ..browser.cdp import evaluate
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


def read_dataset(ws, screen_code, ds_name, limit=-1, offset=0):
    """Every row of a dataset, as a list of dicts keyed by column name."""
    return evaluate(ws, js_read(screen_code, ds_name, limit, offset))

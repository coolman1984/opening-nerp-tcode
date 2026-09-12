"""Write values into a Nexacro dataset - typically a screen's filter DVO.

Forked from gmes_data.py, pulled forward (see form_locator.py's
docstring). Faithful port, unchanged behavior.
"""
import json

from ..browser.cdp import evaluate
from .form_locator import JS_HELPERS


def js_set_values(screen_code, ds_name, values, row):
    return """
    (function() {
        %s
        const hit = _dataset(%s, %s);
        if (!hit) return JSON.stringify({found: false});
        const ds = hit.ds;
        const values = %s;
        if (ds.getRowCount() === 0) ds.addRow();
        const applied = {};
        for (const key in values) {
            try { ds.setColumn(%d, key, values[key]); applied[key] = ds.getColumn(%d, key); }
            catch (e) { applied[key] = 'ERROR: ' + e.message; }
        }
        return JSON.stringify({found: true, path: hit.path, applied: applied});
    })()
    """ % (JS_HELPERS, json.dumps(screen_code), json.dumps(ds_name),
           json.dumps(values), row, row)


def set_filter(ws, screen_code, ds_name, values, row=0):
    """Write values into a dataset - typically the screen's filter DVO."""
    return evaluate(ws, js_set_values(screen_code, ds_name, values, row))

"""Locate a Nexacro form by its screen code, then reach a dataset on it.

Forked from gmes_data.py. Pulled forward into this phase (originally
scheduled for Phase 5d) because screens/verification.py and
discovery/screen_discovery.py both need it to read/find datasets, and a
generic-runner or CLI cannot be tested without a working read path. This
is a FAITHFUL, unchanged port - the paging fix planned for the dataset
reader lands as its own dedicated, tested, HISTORY-documented change once
dataset_reader.py's read path is revisited.

Everything below re-resolves the form each call rather than caching a
path, because G-MES renumbers the window id every time a screen is
reopened (GMES_SKILL #7).
"""
import json

JS_HELPERS = r"""
function _typeName(o) {
    try { return (o && (o._type_name || (o.constructor && o.constructor.name))) || '?'; }
    catch (e) { return '?'; }
}
function _findForms(match) {
    const app = nexacro.getApplication();
    const hits = [];
    function walkForm(form, path, depth) {
        if (!form || depth > 12 || hits.length > 400) return;
        const url = String(form.url || form._url || '');
        const file = url.split('/').pop();
        if (!match || (file && file.toLowerCase().indexOf(match.toLowerCase()) === 0)
                   || path.toLowerCase().indexOf(match.toLowerCase()) >= 0) {
            hits.push({path: path, file: file, form: form});
        }
        let comps = null;
        try { comps = form.components; } catch (e) { return; }
        if (!comps || comps.length === undefined) return;
        for (let i = 0; i < comps.length; i++) {
            let c = null, inner = null;
            try { c = comps[i]; inner = c && c.form; } catch (e) { continue; }
            if (inner) walkForm(inner, path + '.' + (c.name || i), depth + 1);
        }
    }
    function walkFrame(node, path, depth) {
        if (!node || depth > 10) return;
        const here = path ? path + '.' + (node.name || '?') : (node.name || 'app');
        let form = null;
        try { form = node.form || null; } catch (e) {}
        if (form) walkForm(form, here, depth);
        let kids = [];
        try {
            const fr = node._frames || node.frames;
            if (fr && fr.length !== undefined)
                for (let i = 0; i < fr.length; i++) kids.push(fr[i]);
        } catch (e) {}
        try { if (node.mainframe) kids.push(node.mainframe); } catch (e) {}
        kids.forEach(k => walkFrame(k, here, depth + 1));
    }
    walkFrame(app, '', 0);
    return hits;
}
function _dataset(screenCode, dsName) {
    const forms = _findForms(screenCode);
    for (const h of forms) {
        let ds = null;
        try { ds = h.form[dsName]; } catch (e) { continue; }
        if (ds && _typeName(ds) === 'Dataset') return {ds: ds, path: h.path, file: h.file};
    }
    return null;
}
"""


def js_list_forms():
    return """
    (function() {
        %s
        const hits = _findForms(null).map(h => {
            const names = [];
            try {
                for (const k of Object.keys(h.form)) {
                    let o = h.form[k];
                    if (o && _typeName(o) === 'Dataset') names.push(k);
                }
            } catch (e) {}
            return {path: h.path, file: h.file, datasets: names};
        });
        return JSON.stringify({count: hits.length, forms: hits});
    })()
    """ % JS_HELPERS


def js_find_column(column, min_rows=1):
    """Find every dataset anywhere in the app that has a given column."""
    return """
    (function() {
        %s
        const wanted = %s.toLowerCase();
        const out = [];
        for (const h of _findForms(null)) {
            let keys = [];
            try { keys = Object.keys(h.form); } catch (e) { continue; }
            for (const k of keys) {
                let ds = null;
                try { ds = h.form[k]; } catch (e) { continue; }
                if (!ds || _typeName(ds) !== 'Dataset') continue;
                let cols = [], rows = 0;
                try {
                    rows = ds.getRowCount();
                    const n = ds.getColCount();
                    for (let i = 0; i < n; i++) cols.push(ds.getColID(i));
                } catch (e) { continue; }
                if (rows < %d) continue;
                if (!cols.some(c => c.toLowerCase() === wanted)) continue;
                out.push({file: h.file, path: h.path, name: k, rows: rows, cols: cols});
            }
        }
        out.sort((a, b) => b.rows - a.rows);
        return JSON.stringify({count: out.length, hits: out.slice(0, 30)});
    })()
    """ % (JS_HELPERS, json.dumps(column), min_rows)


def list_forms(ws):
    from ..browser.cdp import evaluate
    return evaluate(ws, js_list_forms())

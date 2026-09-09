"""
Read and write GMES data through Nexacro's Datasets instead of the screen.

    python gmes_data.py forms                       # which screens are open
    python gmes_data.py read P1112WM00 dsFilterDVO  # show a dataset's rows
    python gmes_data.py csv  P1112WM00 dsMasterProdPlan out.csv

Why go through the Datasets rather than the visible grid:

  * A Nexacro grid only builds DOM elements for the rows on screen. Reading
    the page returns whatever happens to be scrolled into view, so a
    5,000-row result quietly becomes 20 rows and the job reports success.
    The Dataset holds every row.
  * Column names come back as the system's own field names (planYmd,
    modelCode, poNo...), not as translated screen labels that change with
    the UI language.
  * Filters can be set directly, so there is no fighting with date pickers
    and dropdown widgets.

Screens are addressed by their SCREEN CODE (the xfdl file name, e.g.
P1112WM00), never by the full element path - GMES renumbers the window every
time a screen is opened, so a path captured today is wrong tomorrow.
"""
import csv
import json
import sys

import cdp_common
from cdp_common import evaluate
from gmes_common import connect_gmes


# Locate a form by its screen code, then reach a dataset on it. Everything
# below re-resolves the form each call rather than caching a path, because
# the window id changes whenever the screen is reopened.
JS_HELPERS = r"""
function _typeName(o) {
    try { return (o && (o._type_name || (o.constructor && o.constructor.name))) || '?'; }
    catch (e) { return '?'; }
}
function _findForms(match) {
    const app = nexacro.getApplication();
    const hits = [];
    function walkForm(form, path, depth) {
        if (!form || depth > 12 || hits.length > 60) return;
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


def list_forms(ws):
    return evaluate(ws, js_list_forms())


def read_dataset(ws, screen_code, ds_name, limit=-1, offset=0):
    """Every row of a dataset, as a list of dicts keyed by column name."""
    return evaluate(ws, js_read(screen_code, ds_name, limit, offset))


def set_filter(ws, screen_code, ds_name, values, row=0):
    """Write values into a dataset - typically the screen's filter DVO."""
    return evaluate(ws, js_set_values(screen_code, ds_name, values, row))


def write_csv(result, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=result["columns"])
        writer.writeheader()
        writer.writerows(result["rows"])
    return path


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    command = argv[0]
    ws = connect_gmes()
    try:
        if command == "forms":
            info = list_forms(ws)
            print(f"Open forms: {info['count']}\n")
            for f in info["forms"]:
                if not f["datasets"]:
                    continue
                short = f["path"].replace("application.mainframe.vFrameSet1.vFrameSet2.", "")
                print(f"  {f['file'] or '(no file)'}   {short}")
                print(f"      datasets: {', '.join(f['datasets'][:12])}"
                      + (" ..." if len(f["datasets"]) > 12 else ""))
                print()
            return 0

        if command in ("read", "csv"):
            if len(argv) < 3:
                print("Usage: gmes_data.py read <SCREENCODE> <datasetName> [limit]")
                return 2
            screen, ds_name = argv[1], argv[2]
            limit = -1 if command == "csv" else int(argv[4]) if len(argv) > 4 else 20
            result = read_dataset(ws, screen, ds_name, limit=limit)
            if not result.get("found"):
                print(f"No dataset {ds_name!r} on a form matching {screen!r}. "
                      "Run 'gmes_data.py forms' to see what is open.")
                return 1

            print(f"Screen  : {result['file']}")
            print(f"Dataset : {ds_name}   total rows: {result['total']}")
            print(f"Columns : {', '.join(result['columns'])}\n")

            if command == "csv":
                out = argv[3] if len(argv) > 3 else f"{screen}_{ds_name}.csv"
                print(f"Wrote {result['total']} rows to {write_csv(result, out)}")
                return 0

            for i, row in enumerate(result["rows"]):
                shown = {k: v for k, v in row.items() if v and not k.startswith("_")}
                print(f"  [{i}] {shown}")
            if result["total"] > len(result["rows"]):
                print(f"\n  ... {result['total'] - len(result['rows'])} more rows")
            return 0

        print(__doc__)
        return 2
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

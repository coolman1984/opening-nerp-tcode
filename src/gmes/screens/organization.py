"""Ticking a category tree (Org/Prod/Fac/Proc), and reading back what the
screen itself believes is selected.

Forked from gmes_core.py. `tick_org`/`org_selection` return the raw JS-eval
result dicts as before (ticked/cleared/missing/available lists, or the
screen's own summary text) - there is no natural typed contract for a
one-shot tick outcome, so this is left as-is rather than a forced fit.
"""
import json

from ..browser.cdp import evaluate
from ..query.form_locator import JS_HELPERS

# Organisation trees: the left panel offers Org / Prod / Fac / Proc,
# and each tab has a tree of its own. They are found by SHAPE instead: a
# dataset carrying a `commonName` column and a `_checked` flag is a category
# tree, whatever it is called and wherever it lives.
JS_TICK_ORG = r"""
(function() {
    %s
    const treeName = %s;
    const wanted = %s;
    const exclusive = %s;
    const screenCode = %s;

    // EVERY instance of the tree, not the first one found.
    //
    // A screen can hold the same category tree several times - Work Calendar
    // has THREE copies of OrgCategory_GDS.dsCatCommonTreeNodeDVO, one per
    // panel tab - and `_dataset()` returns whichever the form walk reaches
    // first. Writing to that one and reporting success is how a run announced
    // "Tick the division ... VD" while the screen still had MOBILE ticked by
    // hand, and then exported MOBILE's rows under a VD heading.
    //
    // They are the same logical tree, so writing all of them is both safe and
    // the only way to be sure the visible one was included.
    const targets = [];
    for (const h of _findForms(screenCode)) {
        let ds = null;
        try { ds = h.form[treeName]; } catch (e) { continue; }
        if (!ds || _typeName(ds) !== 'Dataset') continue;
        let cols = [];
        try { const n = ds.getColCount();
              for (let i = 0; i < n; i++) cols.push(ds.getColID(i)); } catch (e) { continue; }
        if (cols.indexOf('commonName') < 0) continue;
        if (cols.indexOf('_checked') < 0) continue;
        targets.push({ds: ds, file: h.file});
    }
    if (!targets.length)
        return JSON.stringify({found: false, reason:
            'no instance of this tree has a _checked column'});

    const want = wanted.map(w => String(w).trim().toLowerCase());
    const ticked = [], cleared = [], present = {};
    let available = [];

    for (const t of targets) {
        const ds = t.ds;
        for (let r = 0; r < ds.getRowCount(); r++) {
            let nm = '';
            try { nm = String(ds.getColumn(r, 'commonName') || '').trim(); }
            catch (e) { continue; }
            const low = nm.toLowerCase();
            // Case-insensitive: a user typing "vd" must find "VD". An exact
            // comparison once failed a run with the answer sitting in the
            // very error message it printed.
            const isWanted = want.indexOf(low) >= 0;
            let was = '';
            try { was = String(ds.getColumn(r, '_checked') || ''); } catch (e) {}

            if (isWanted) {
                present[low] = true;
                try {
                    ds.setColumn(r, '_checked', 1);
                    let pathKey = '';
                    try { pathKey = String(ds.getColumn(r, 'commonPathKey') || ''); }
                    catch (e) {}
                    ticked.push({name: nm, pathKey: pathKey,
                                 now: String(ds.getColumn(r, '_checked'))});
                } catch (e) {}
            } else if (exclusive && was === '1') {
                // A tick SURVIVES between runs, and can also have been made
                // by hand a moment ago. Leaving one behind means the next run
                // silently queries a different organisation and answers
                // confidently with the wrong scope.
                try { ds.setColumn(r, '_checked', 0); cleared.push(nm); } catch (e) {}
            }
        }
        if (!available.length) {
            for (let r = 0; r < ds.getRowCount(); r++) {
                try { const n = String(ds.getColumn(r, 'commonName') || '').trim();
                      if (n) available.push(n); } catch (e) {}
            }
        }
    }

    const missing = want.filter(w => !present[w]);
    return JSON.stringify({found: missing.length === 0, ticked: ticked,
                           cleared: cleared, missing: missing,
                           instances: targets.length,
                           file: targets[0].file, available: available});
})()
"""


def tick_org(ws, form_code, dataset, names, exclusive=True):
    """Tick entries in a category tree by their visible name."""
    if isinstance(names, str):
        names = [names]
    return evaluate(ws, JS_TICK_ORG % (JS_HELPERS,
                                       json.dumps(dataset),
                                       json.dumps(list(names)),
                                       "true" if exclusive else "false",
                                       json.dumps(form_code)))


# The screen's own summary of what organisation is selected - the ground
# truth, and the only thing that would have caught the MOBILE-under-a-VD-label
# run. Reads "Org VD l Prod All l Proc All".
JS_ORG_SELECTION = r"""
(function() {
    const isVisible = %s;
    let best = null;
    for (const el of document.querySelectorAll('div')) {
        const id = el.id || '';
        if (!/staCategory(Ori)?(:text)?$/.test(id)) continue;
        if (!isVisible(el)) continue;
        const text = (el.textContent || '').trim();
        if (!/^Org\s/.test(text) || text.length > 120) continue;
        if (!best || text.length < best.length) best = text;
    }
    if (best === null) return JSON.stringify({found: false});
    // "Org VD l Prod All l Proc All" - the separator renders as a lowercase
    // L in one place and a pipe in another, so both are accepted.
    const first = best.split(/\s+[l|]\s+/)[0];
    return JSON.stringify({found: true, text: best,
                           org: first.replace(/^Org\s+/, '').trim()});
})()
"""


def org_selection(ws):
    """What the SCREEN says is selected, e.g. {'org': 'VD'}.

    Read back after ticking, because the dataset write is not proof. The
    write went into one of three copies of the tree while the visible one
    still had MOBILE ticked by hand; the run reported VD and exported
    MOBILE's rows. This label is what the screen itself believes."""
    from ..nexacro.js_snippets import JS_IS_VISIBLE
    try:
        return evaluate(ws, JS_ORG_SELECTION % JS_IS_VISIBLE)
    except Exception as e:
        return {"found": False, "reason": str(e)}

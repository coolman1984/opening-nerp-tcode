"""Nexacro application bootstrap state: is it built, and is its
localStorage engine cache full.

Forked from gmes_common.py. G-MES caches its whole Nexacro engine in
localStorage under a key made of a timestamp and the engine URL, writes a
new one on every load, and never removes the old ones. At about fifty
loads the ~5MB per-site quota fills, the bootstrap throws
QuotaExceededError, and nexacro.getApplication() stays empty forever - a
blank page with a spinner that looks identical to a merely slow one from
outside (HISTORY.md Phase 22). Automation hits this far sooner than a
person does, because it reloads the page all day.
"""
import json

from ..browser.cdp import evaluate

_ENGINE_KEY = r"^\d{10,}http.*\/engine$"

JS_STORAGE_STATE = r"""
(function() {
    let bytes = 0, engine = 0;
    try {
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            bytes += k.length + (localStorage.getItem(k) || '').length;
            if (new RegExp(%s).test(k)) engine++;
        }
        return JSON.stringify({ok: true, entries: localStorage.length,
                               bytes: bytes, engineCopies: engine});
    } catch (e) {
        return JSON.stringify({ok: false, reason: e.message});
    }
})()
"""

JS_PRUNE_ENGINE_CACHE = r"""
(function() {
    const keep = %d;
    try {
        const keys = [];
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (new RegExp(%s).test(k)) keys.push(k);
        }
        // The timestamp prefix is fixed width, so a plain sort puts the
        // oldest first. Only the engine cache is touched - anything else the
        // site keeps here (a remembered ID, for one) is left alone.
        keys.sort();
        const stale = keep > 0 ? keys.slice(0, -keep) : keys;
        let freed = 0;
        for (const k of stale) {
            freed += (localStorage.getItem(k) || '').length;
            localStorage.removeItem(k);
        }
        return JSON.stringify({ok: true, found: keys.length,
                               removed: stale.length, freed: freed});
    } catch (e) {
        return JSON.stringify({ok: false, reason: e.message});
    }
})()
"""

JS_APP_BUILT = """
(function() {
    let app = false;
    try { app = (typeof nexacro !== 'undefined') && !!nexacro.getApplication(); }
    catch (e) {}
    return JSON.stringify({app: app, divs: document.querySelectorAll('div').length,
                           ready: document.readyState});
})()
"""


def storage_state(ws):
    """How full this site's localStorage is, and how many engine copies."""
    try:
        return evaluate(ws, JS_STORAGE_STATE % json.dumps(_ENGINE_KEY))
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def prune_nexacro_cache(ws, keep=1):
    """Delete the stale engine caches, keeping the newest `keep`.

    Safe to call at any time: this is a cache the application rebuilds on
    its next load. It is not a fix for a slow page - it is the fix for a
    page that cannot start at all."""
    try:
        return evaluate(ws, JS_PRUNE_ENGINE_CACHE % (keep, json.dumps(_ENGINE_KEY)))
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def app_is_built(ws):
    """Whether the Nexacro application object exists yet.

    A page that is merely slow and a page that has failed to bootstrap
    look identical from the outside - both are blank. This is the
    difference."""
    try:
        return bool(evaluate(ws, JS_APP_BUILT).get("app"))
    except Exception:
        return False

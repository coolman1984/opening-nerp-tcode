"""Find and drive Nexacro elements: by exact DOM id, or by pattern.

Forked from gmes_common.py. The exact-id lookups (`js_find_by_id`,
`click_by_id`, `set_value_by_id`) were ported in Phase 4 for the sign-in
flow. `js_find_elements`/`find_elements`/`click_control` (pattern-based:
by id regex, CSS class, or visible text) are added here in Phase 5b,
because screens/verification.py's `poll_inquiry()` needs `click_control`
to find the Inquiry button, which has no stable full id.

Full ids must NEVER be hardcoded for anything INSIDE a work screen - GMES
renumbers each opened screen instance. What is safe to hardcode here is
the shell frames (topFrame, loginFrame, mdiFrame), because there is only
ever one of each; every id used by the exact-id lookups below is one of
those. The pattern-based lookups exist precisely for everything else -
a work screen's own controls, matched by CSS class or visible label
rather than by the id that changes every time the screen reopens.
"""
import json
import time

from ..browser.cdp import evaluate
from ..browser.interaction import click_element_by_rect
from .js_snippets import JS_IS_VISIBLE, JS_SET_VALUE


def js_find_by_id(element_id):
    """Locate one Nexacro element by its exact id and report where it is."""
    return """
    (function() {
        const isVisible = %s;
        const el = document.getElementById(%s);
        if (!el) return JSON.stringify({found: false, reason: 'no such id'});
        if (!isVisible(el)) return JSON.stringify({found: false, reason: 'not visible'});
        const r = el.getBoundingClientRect();
        return JSON.stringify({found: true, text: (el.textContent || '').trim().slice(0, 40),
                               x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """ % (JS_IS_VISIBLE, json.dumps(element_id))


def click_by_id(ws, element_id, attempts=20, delay=0.5):
    """Click a Nexacro control by id, waiting for it to appear first.

    Polls rather than assuming the control is ready: a Nexacro screen
    builds itself in JavaScript after the page reports 'complete', so a
    control can be seconds away from existing when we first look."""
    for _ in range(attempts):
        info = evaluate(ws, js_find_by_id(element_id))
        if info.get("found"):
            click_element_by_rect(ws, info["x"], info["y"])
            return info
        time.sleep(delay)
    return None


def set_value_by_id(ws, element_id, value):
    """Type into a Nexacro input. Nexacro listens for the events, so a bare
    value assignment is not enough."""
    js = """
    (function() {
        const value = %s;
        const el = document.getElementById(%s);
        if (!el) return JSON.stringify({found: false});
        %s
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return JSON.stringify({found: true, value: el.value});
    })()
    """ % (json.dumps(value), json.dumps(element_id), JS_SET_VALUE)
    return evaluate(ws, js)


# --------------------------------------------------------------------------
# Finding controls by pattern, not by full id
# --------------------------------------------------------------------------
#
# The stable parts of a work-screen control are the screen code
# (winPPM0219), the trailing control path (form.divLeft.form.btnSearch),
# the CSS class Nexacro assigns by control type (btn_LF_Search_New), and
# the visible label. Match on those instead.

def js_find_elements(id_regex=None, cls=None, text=None, exact_text=True,
                     visible_only=True, limit=40):
    return """
    (function() {
        const isVisible = %s;
        const idRe   = %s;
        const cls    = %s;
        const text   = %s;
        const exact  = %s;
        const visOnly = %s;

        const rx = idRe ? new RegExp(idRe) : null;
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            const id = el.id || '';
            const klass = (typeof el.className === 'string') ? el.className : '';
            const t = (el.textContent || '').trim();

            if (rx && !rx.test(id)) continue;
            if (cls && !klass.split(/\\s+/).includes(cls)) continue;
            if (text !== null) {
                if (exact ? t !== text : !t.toLowerCase().includes(text.toLowerCase()))
                    continue;
            }
            if (visOnly && !isVisible(el)) continue;

            const r = el.getBoundingClientRect();
            out.push({id: id, cls: klass.slice(0, 60), text: t.slice(0, 40),
                      tag: el.tagName, w: Math.round(r.width), h: Math.round(r.height),
                      x: r.left + r.width/2, y: r.top + r.height/2,
                      area: r.width * r.height});
            if (out.length >= %d) break;
        }
        // Smallest first: the real control, not a container wrapping it.
        out.sort((a, b) => a.area - b.area);
        return JSON.stringify({count: out.length, hits: out});
    })()
    """ % (JS_IS_VISIBLE,
           json.dumps(id_regex) if id_regex else "null",
           json.dumps(cls) if cls else "null",
           json.dumps(text) if text is not None else "null",
           "true" if exact_text else "false",
           "true" if visible_only else "false",
           limit)


def find_elements(ws, **criteria):
    return evaluate(ws, js_find_elements(**criteria))


def click_control(ws, attempts=20, delay=0.5, **criteria):
    """Click the smallest visible control matching the criteria, waiting for
    it to appear first. Returns the clicked element, or None."""
    for _ in range(attempts):
        found = find_elements(ws, **criteria)
        if found.get("count"):
            target = found["hits"][0]
            click_element_by_rect(ws, target["x"], target["y"])
            return target
        time.sleep(delay)
    return None

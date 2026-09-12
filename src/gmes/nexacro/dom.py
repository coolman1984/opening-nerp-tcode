"""Find and drive one Nexacro element by its exact DOM id.

Forked from gmes_common.py. Only the subset the sign-in flow (auth/)
needs is ported here in this phase (Phase 4 of the migration, folded
forward from its originally planned Phase 5a); `find_elements`/
`click_control`/`js_find_elements` (pattern-based lookup, used by
screen discovery rather than login) land with the rest of nexacro/
in the discovery/screens phase.

Full ids must NEVER be hardcoded for anything INSIDE a work screen - GMES
renumbers each opened screen instance. What is safe to hardcode here is
the shell frames (topFrame, loginFrame, mdiFrame), because there is only
ever one of each; every id used in this module is one of those.
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

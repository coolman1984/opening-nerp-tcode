"""Real mouse/keyboard input dispatch and shared JS predicates.

Forked from cdp_common.py. G-MES's own Nexacro controls are <div>s wired
to mouse events, not <button>s with a click handler - element.click() does
nothing on them, the same lesson N-ERP's SAP WebGUI already taught. Real
Input.dispatchMouseEvent sequences are required.

JS_IS_VISIBLE and JS_SET_VALUE live here (not yet in a dedicated
nexacro/js_snippets.py) because interaction.py is the lowest-level module
that needs them; nexacro/dom.py (Phase 5a of the migration) imports them
from here rather than duplicating the strings. They will move to
nexacro/js_snippets.py once that package exists, at which point this
module will import them back for its own use.
"""
import time

from .cdp import send

# Shared JS predicate: an element is only clickable if it has a non-zero box
# AND that box actually intersects the viewport. Some dropdown widgets
# pre-render off-screen (observed at y = -99984) with a perfectly valid
# width/height, so a size-only check finds them, clicks empty space, and the
# whole flow fails silently with no error anywhere.
JS_IS_VISIBLE = """
    function(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.bottom <= 0 || r.right <= 0) return false;
        if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;
        return true;
    }
"""

# Shared by every "type into a field" call site that isn't going through
# per-character key events. A bare `.value =` assignment is not observed by
# either SAP or Nexacro controls, so the input/change events must be fired
# too.
JS_SET_VALUE = """
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
"""


def click_element_by_rect(ws, x, y, msg_id_start=None):
    """Real mouse event simulation. Required because element.click() is
    ignored by Nexacro's <div>-based controls - they are wired to
    mousedown/mouseup, with no click handler to invoke at all.

    msg_id_start is accepted for backwards compatibility and ignored; ids
    come from the shared counter in cdp.py."""
    send(ws, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    time.sleep(0.1)
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def dispatch_key_combo(ws, key, code, vk, ctrl=False, shift=False, alt=False,
                       msg_id_start=None):
    """Dispatch a keyboard shortcut to whichever target ws is connected to.
    modifiers bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8."""
    mods = (1 if alt else 0) | (2 if ctrl else 0) | (8 if shift else 0)
    params = {
        "modifiers": mods,
        "key": key,
        "code": code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    send(ws, "Input.dispatchKeyEvent", {"type": "rawKeyDown", **params})
    send(ws, "Input.dispatchKeyEvent", {"type": "keyUp", **params})

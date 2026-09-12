"""Typing into a control that has no dataset behind it.

Forked from gmes_core.py. Nexacro's own `set_value()` fills a box and
changes nothing the control reacts to - the suggestion lists, validation
and value commits all hang off the key handlers, so the keys have to be
real (the same lesson the top search box already taught, GMES_SKILL #22).
"""
import json
import time

from ..browser.cdp import evaluate, send
from ..browser.interaction import click_element_by_rect, dispatch_key_combo
from ..nexacro.dom import js_find_by_id
from .grids import digits_only

# What a control shows right now - used to confirm that a typed value landed.
JS_CONTROL_VALUE = r"""
(function() {
    const el = document.getElementById(%s);
    if (!el) return JSON.stringify({found: false, reason: 'no such id'});
    let v = '';
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') v = el.value || '';
    else {
        const inner = el.querySelector('input, textarea');
        v = inner ? (inner.value || '') : (el.textContent || '').trim();
    }
    return JSON.stringify({found: true, value: v});
})()
"""


def _key_events(ch):
    """CDP key parameters for one character.

    `char` carries the actual text, which is what the input consumes; the
    keyDown/keyUp pair is what Nexacro's own onkeyup handlers watch for. The
    code/virtual-key values are only right for letters and digits, and that is
    enough - punctuation still arrives through the `char` event."""
    if ch.isalpha():
        return f"Key{ch.upper()}", ord(ch.upper())
    if ch.isdigit():
        return f"Digit{ch}", ord(ch)
    return "", 0


def type_text(ws, dom_id, text, clear=True, commit=True, verify=True):
    """Type into a control with real key events, then confirm what it shows."""
    box = evaluate(ws, js_find_by_id(dom_id))
    if not box.get("found"):
        raise RuntimeError(f"the control {dom_id.split('.')[-1]} is not on screen "
                           f"({box.get('reason')})")
    click_element_by_rect(ws, box["x"], box["y"])
    time.sleep(0.3)

    if clear:
        dispatch_key_combo(ws, "a", "KeyA", 65, ctrl=True)
        dispatch_key_combo(ws, "Delete", "Delete", 46)
        time.sleep(0.1)

    for ch in str(text):
        code, vk = _key_events(ch)
        for kind in ("keyDown", "char", "keyUp"):
            params = {"type": kind, "key": ch, "code": code}
            if kind == "char":
                params["text"] = ch
            elif vk:
                params["windowsVirtualKeyCode"] = vk
            send(ws, "Input.dispatchKeyEvent", params)
        time.sleep(0.05)

    if commit:
        # Nexacro commits an edit on blur. Without this the value sits in the
        # editor and the Inquiry runs on the previous one.
        dispatch_key_combo(ws, "Tab", "Tab", 9)
        time.sleep(0.3)

    if not verify:
        return str(text)
    shown = evaluate(ws, JS_CONTROL_VALUE % json.dumps(dom_id))
    got = (shown.get("value") or "").strip()
    if digits_only(got) != digits_only(text) and got != str(text).strip():
        raise RuntimeError(f"typing into {dom_id.split('.')[-1]} did not take - "
                           f"it shows {got!r}, not {str(text)!r}")
    return got

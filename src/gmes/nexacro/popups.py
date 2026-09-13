"""Close Nexacro's floating child-window popups (Notice, etc).

Forked from gmes_common.py. Nexacro gives every floating popup a title bar
with the same three controls; matching on the CSS class rather than the
popup's own name matters, because the Notice window's id contains Korean
text (`공지사항`) and the next popup will have a different name again -
a name-based rule would only ever close this one popup on this one
screen.

The scope is deliberately narrow: only title bars marked
`titlebarChildFrame`, i.e. floating child windows. The user's actual work
screen also has a close button, and closing that would throw away the
thing the automation just opened.

Two ways of closing exist here, because clicking the X is not reliable.
A popup whose close button is covered by a later popup, or which has
been repositioned mid-click, swallows the click and stays open - the run
then fails much later, on a control the notice was sitting on top of.
`close_child_popups` therefore falls back to Nexacro's own
`ChildFrame.close()`, resolved from the title bar's DOM id.

IMPORTANT (GMES_SKILL #6): the Excel export dialog is also a child popup,
so closing every popup indiscriminately would close it. That blanket
closer runs only during sign-in. `close_notices()` is the one safe to
call during a run: it closes only popups it can positively identify as
notices, and reports anything it does not recognise instead of clicking
it (CLAUDE.md 3.9).
"""
import json
import time

from ..browser.cdp import evaluate
from ..browser.interaction import click_element_by_rect
from .js_snippets import JS_IS_VISIBLE

# A popup is only closed during a run when its own title says what it is.
# These are the notice windows G-MES raises after sign-in and, occasionally,
# while a screen is open: the Korean notice board, its English label, and the
# notice screen code seen in a live run (S9502UP01).
NOTICE_MARKS = ("공지사항", "notice", "notification", "공지", "알림", "s9502up")

# Anything that asks the operator a question is NOT a notice, whatever else
# it says. The Excel export dialog lives here: closing it mid-export cancels
# the download and leaves the run waiting for a file that is never coming.
DIALOG_MARKS = ("excel", "엑셀", "save", "저장", "download", "다운로드",
                "print", "인쇄", "confirm", "확인하", "delete", "삭제")

JS_CLOSE_CHILD_POPUPS = """
(function() {
    const isVisible = %s;
    const closed = [];
    const bars = Array.from(document.querySelectorAll('.TitleBarControl.titlebarChildFrame'));
    for (const bar of bars) {
        if (!isVisible(bar)) continue;
        const btn = bar.querySelector('.closebutton');
        if (!btn || !isVisible(btn)) continue;
        const r = btn.getBoundingClientRect();
        closed.push({
            name: (bar.textContent || '').trim().slice(0, 40),
            id: btn.id,
            // The frame path is the title bar's own id minus its trailing
            // '.titlebar' segment; Nexacro builds the DOM id from the
            // component path, so this is the popup's address, not a guess.
            frame: (bar.id || '').replace(/\\.titlebar$/, ''),
            x: r.left + r.width / 2,
            y: r.top + r.height / 2
        });
    }
    return JSON.stringify({count: closed.length, popups: closed});
})()
""" % JS_IS_VISIBLE


# Nexacro's own close. Child frames are NOT properties of their parent -
# they live in `_frames`, an ObjectArray with numeric indexing (GMES_SKILL
# #10) - so a plain property walk stops dead at the popup's own segment.
# This walks properties where it can and searches `_frames` by name where it
# cannot, which is the only way the Korean-named notice frame is reachable.
JS_CLOSE_FRAME = r"""
(function() {
    const path = %s;
    function childByName(node, name) {
        try {
            const fr = node._frames || node.frames;
            if (fr && fr.length !== undefined)
                for (let i = 0; i < fr.length; i++)
                    if (fr[i] && String(fr[i].name) === name) return fr[i];
        } catch (e) {}
        return null;
    }
    let node = null;
    try { node = nexacro.getApplication(); } catch (e) {
        return JSON.stringify({closed: false, reason: 'no Nexacro application'});
    }
    const parts = path.split('.');
    for (const part of parts) {
        if (!node) break;
        let next = null;
        try { next = node[part]; } catch (e) { next = null; }
        if (!next) next = childByName(node, part);
        if (!next) return JSON.stringify({closed: false, reason: 'no frame at ' + part});
        node = next;
    }
    if (!node || typeof node.close !== 'function')
        return JSON.stringify({closed: false, reason: 'that frame has no close()'});
    try { node.close(); } catch (e) {
        return JSON.stringify({closed: false, reason: 'close() raised: ' + e.message});
    }
    return JSON.stringify({closed: true});
})()
"""


def classify(popup):
    """What a floating popup is, from the text in its own title bar.

    Only three answers, and the middle one matters most: `unknown` means
    do not touch it. A popup this cannot name is either a dialog the run
    itself raised or something new on the screen, and clicking it blind is
    how a diagnosis gets destroyed."""
    title = f"{popup.get('name', '')} {popup.get('frame', '')}".casefold()
    if any(mark in title for mark in DIALOG_MARKS):
        return "dialog"
    if any(mark in title for mark in NOTICE_MARKS):
        return "notice"
    return "unknown"


def find_child_popups(ws):
    """Every visible floating popup, each tagged with what it appears to be."""
    found = evaluate(ws, JS_CLOSE_CHILD_POPUPS)
    for popup in found.get("popups", []):
        popup["kind"] = classify(popup)
    return found


def _close_one(ws, popup, settle=3.0, poll=0.25):
    """Click the X, and fall back to the frame's own close() if it did not go.

    The click is tried first because it is what a person does, and it
    leaves Nexacro's own event handlers to run. The API call is the
    fallback for the case that actually bites: a close button that is
    present, visible and simply not receiving the click.

    Each attempt is confirmed by watching the popup disappear, not by
    assuming the click worked. The wait polls and returns the instant the
    popup is gone, so proving the normal case costs one extra read."""
    click_element_by_rect(ws, popup["x"], popup["y"])
    if _gone(ws, popup, settle, poll):
        return "clicked"
    if popup.get("frame"):
        result = evaluate(ws, JS_CLOSE_FRAME % json.dumps(popup["frame"]))
        if result.get("closed") and _gone(ws, popup, settle, poll):
            return "closed through Nexacro"
    return ""


def _gone(ws, popup, timeout, poll):
    deadline = time.time() + timeout
    while True:
        if not _still_open(ws, popup):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(poll)


def _still_open(ws, popup):
    open_now = find_child_popups(ws).get("popups", [])
    return any(other.get("frame") == popup.get("frame")
               and other.get("id") == popup.get("id") for other in open_now)


def _name(popup):
    return popup.get("name") or popup.get("frame") or popup.get("id")


def _close_kind(ws, kind, rounds, delay, settle):
    """Close every visible popup of one classification, and name the rest.

    Returns (closed, left_alone). The second list is every popup this
    refused to touch - it is what lets a caller say the screen is not clear
    instead of carrying on as though it were."""
    closed, left = [], []
    for _ in range(rounds):
        on_screen = find_child_popups(ws).get("popups", [])
        wanted = [p for p in on_screen if p["kind"] == kind]
        left = [f"{_name(p)} ({p['kind']})" for p in on_screen if p["kind"] != kind]
        if not wanted:
            break
        progressed = False
        for popup in wanted:
            if _close_one(ws, popup, settle=settle):
                closed.append(_name(popup))
                progressed = True
            else:
                left.append(f"{_name(popup)} (would not close)")
        if not progressed:
            break
        time.sleep(delay)
    return closed, left


def close_notices(ws, rounds=4, delay=0.5, settle=3.0):
    """Close only the popups positively identified as notices.

    Safe to call while a report screen is open, which the blanket closer is
    not: a notice raised after sign-in sits over the left panel and eats the
    Inquiry click, and the run then fails on a control that is present,
    visible and covered."""
    return _close_kind(ws, "notice", rounds, delay, settle)


def close_dialogs(ws, rounds=3, delay=0.5, settle=3.0):
    """Dismiss a dialog left open by an attempt of our own.

    Narrow on purpose, and not a general-purpose closer. It exists for one
    situation: an export attempt that opened the Save-to-Excel dialog and
    then failed, leaving it on screen. Clicking the Excel icon again with
    that dialog still up would fire a shortcut into an open dialog
    (CLAUDE.md 3.9), so the dialog we raised is dismissed first.

    Only popups classified as dialogs are touched. A popup this cannot name
    comes back in the second list, and the caller is expected to stop rather
    than carry on past a window nobody recognises."""
    return _close_kind(ws, "dialog", rounds, delay, settle)


def close_popups_when_they_appear(ws, appear_wait=45, poll_interval=1.0,
                                  quiet_rounds=3, verbose=True):
    """Wait for popups to show up, then close them - and keep watching.

    Checking once straight after signing in finds nothing: the Notice
    window is opened by the app a few seconds AFTER the user name appears
    in the top bar, so a single check races it and reports "none were
    open" while the popup is on its way. It then sits there blocking
    every later click.

    So this waits for the first popup to appear, closes it, and keeps
    looking until several consecutive checks come back empty - which also
    catches notices that queue up one behind another."""
    closed = []
    started = time.time()
    deadline = started + appear_wait
    quiet, stuck = 0, 0

    # `or closed` used to keep this loop alive indefinitely once anything
    # had been closed, and the deadline was pushed out another 8s on every
    # pass that clicked something - so a popup that would not close kept
    # the loop running and the list growing. It is bounded now, in both
    # directions.
    while time.time() < deadline and time.time() - started < appear_wait * 2:
        found = find_child_popups(ws)
        before = found.get("count", 0)
        if before:
            quiet = 0
            for popup in found["popups"]:
                if not _close_one(ws, popup):
                    continue
                closed.append(_name(popup))
                if verbose:
                    print(f"  closed popup: {_name(popup)}")
            time.sleep(poll_interval)
            if find_child_popups(ws).get("count", 0) >= before:
                stuck += 1
                if stuck >= 2:
                    if verbose:
                        print("  a popup is not responding to its close button - "
                              "leaving it and carrying on")
                    break
            else:
                stuck = 0
                deadline = max(deadline, time.time() + 8)   # let a queued one arrive
            continue

        quiet += 1
        if closed and quiet >= quiet_rounds:
            break
        time.sleep(poll_interval)

    return closed


def close_child_popups(ws, rounds=8, delay=0.5):
    """Click the X on every floating popup, until they are actually gone.

    Repeats because popups queue up: the Notice window can be followed by
    another one that only appears once the first is gone, so a single
    pass leaves the screen blocked.

    But it stops when clicking stops WORKING. A real sign-in reported
    closing the same popup - `S9502UP01` - twenty-three times, because
    each pass re-found the one before it and clicked it again. The count
    is checked after every pass: if it has not dropped twice running, the
    clicks are not closing anything and going round again only burns
    time."""
    closed, stuck = [], 0
    for _ in range(rounds):
        found = find_child_popups(ws)
        before = found.get("count", 0)
        if not before:
            break
        for popup in found["popups"]:
            if _close_one(ws, popup):
                closed.append(_name(popup))
        time.sleep(delay)

        if find_child_popups(ws).get("count", 0) >= before:
            stuck += 1
            if stuck >= 2:
                break
        else:
            stuck = 0
    return closed

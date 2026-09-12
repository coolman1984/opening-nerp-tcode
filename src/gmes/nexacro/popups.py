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
thing the automation just opened. IMPORTANT (GMES_SKILL #6): the Excel
export dialog is also a child popup, so this must run only during
sign-in, never around an export - that separation is the calling code's
responsibility, not enforced here.
"""
import time

from ..browser.cdp import evaluate
from ..browser.interaction import click_element_by_rect
from .js_snippets import JS_IS_VISIBLE

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
            x: r.left + r.width / 2,
            y: r.top + r.height / 2
        });
    }
    return JSON.stringify({count: closed.length, popups: closed});
})()
""" % JS_IS_VISIBLE


def find_child_popups(ws):
    return evaluate(ws, JS_CLOSE_CHILD_POPUPS)


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
                click_element_by_rect(ws, popup["x"], popup["y"])
                name = popup["name"] or popup["id"]
                closed.append(name)
                if verbose:
                    print(f"  closed popup: {name}")
                time.sleep(0.4)
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
            click_element_by_rect(ws, popup["x"], popup["y"])
            closed.append(popup["name"] or popup["id"])
            time.sleep(0.3)
        time.sleep(delay)

        if find_child_popups(ws).get("count", 0) >= before:
            stuck += 1
            if stuck >= 2:
                break
        else:
            stuck = 0
    return closed

"""
Step 3 - "export to excel file": on the currently-open SAP WebGUI list screen
(after a T-code has been opened and Executed), open the export dialog and save
as "<T-code>_<YYYYMMDD_HHMMSS>.xlsx".

There is no single universal export shortcut - SAP status key bindings are
configured per transaction (gotcha #17), and different list widgets use
genuinely different dialogs. So this fires triggers in order and identifies
the resulting dialog by its CONTENT, never by assuming a fixed
shortcut-to-flow mapping:

  Flow A - "Export As" dialog (Ctrl+Shift+F7 on standard ALV grids like MB52;
  also Shift+F4 on MB51): filename defaults to "EXPORT_YYYYMMDD_HHMMSS",
  then "Export to..." opens a second "Enter file name to save" dialog, then
  "OK".

  Flow B - direct "Enter file name to save" (Shift+F7 on hierarchical/tree
  reports like ZRPPM400300's MRP list): filename already ends in .XLSX, no
  intermediate "Export to..." step - fill and click "OK".

  Flow C - "Save list in file..." format chooser (Ctrl+Shift+F9, e.g.
  ZRMMK121040's "Split xls" list): no filename field yet, only format radio
  buttons with no Excel option. Pick "Text with Tabs", click the icon-only
  "Continue", then in the "Enter file name to save" dialog switch the
  "Save as" dropdown from "Text Files (*.txt)" to "Spreadsheet Files
  (*.xlsx)" - without that switch you get a tab-separated .txt, not a real
  workbook - then fill the name and click "OK".

  Fallback - toolbar "Export" icon (title exactly "Export", e.g. id
  _MB_EXPORT102 on ZRPPD410200): click it, choose "Spreadsheet" from the
  dropdown, and it lands in flow A. Mouse-driven, so it is the last resort
  after every keyboard shortcut fails.

Usage:
    python export_to_excel.py MB52
    python export_to_excel.py ZRMMK121040 --name MyCustomName

The file lands in the SAP GUI download destination shown in the dialog
(e.g. "Z:\\MB52_20260905_095146.xlsx" in this environment).
"""
import json
import sys
import time
from datetime import datetime

import cdp_common
from cdp_common import (
    connect, evaluate, get_webgui_tab, click_element_by_rect,
    dispatch_key_combo, find_visible_leaf_by_text, find_visible_by_title,
    describe_visible_dialog,
)


# Flow A's filename field arrives pre-populated with SAP's default export
# name; flow B's already carries an .XLSX extension. Both are matched on that
# value rather than on an element id, because the id is dynpro-generated and
# regenerated per screen (gotcha #10). This is SAP's generic SALV "Export As"
# dialog, so the approach generalises well beyond any one report.
FLOW_A_DEFAULT_PATTERN = r"^EXPORT_\d{8}_\d{6}$"
FLOW_B_DEFAULT_PATTERN = r"\.XLSX$"


def js_find_filename_field(pattern):
    """Locate (without modifying) a visible input whose current value looks
    like SAP's default export filename.

    Detection and mutation are deliberately separate here. The original code
    filled the field as a side effect of detecting it, inside a loop that
    ran once per candidate flow per poll - so a screen could be written to
    several times while merely being inspected."""
    return """
    (function() {
        const isVisible = %s;
        let inputs = Array.from(document.querySelectorAll('input[type="text"]'));
        let field = inputs.find(inp => isVisible(inp) && %s.test((inp.value || '').trim()));
        if (!field) return JSON.stringify({found: false});
        return JSON.stringify({found: true, id: field.id, value: field.value});
    })()
    """ % (cdp_common.JS_IS_VISIBLE, f"/{pattern}/i")


def js_set_filename_field(pattern, new_value):
    return """
    (function() {
        const value = %s;
        const isVisible = %s;
        let inputs = Array.from(document.querySelectorAll('input[type="text"]'));
        let el = inputs.find(inp => isVisible(inp) && %s.test((inp.value || '').trim()));
        if (!el) return JSON.stringify({found: false});
        %s
        return JSON.stringify({found: true, id: el.id, value: el.value});
    })()
    """ % (json.dumps(new_value), cdp_common.JS_IS_VISIBLE,
           f"/{pattern}/i", cdp_common.JS_SET_VALUE)


JS_FLOW_C_VISIBLE = """
(function() {
    const isVisible = %s;
    let found = Array.from(document.querySelectorAll('*')).some(el => {
        const t = (el.textContent || '').trim();
        return t === 'Text with Tabs' && isVisible(el);
    });
    return JSON.stringify({found: found});
})()
""" % cdp_common.JS_IS_VISIBLE


def click_button_by_text(ws, *texts):
    candidates = find_visible_leaf_by_text(ws, *texts)
    if not candidates:
        return None
    btn = candidates[0]
    click_element_by_rect(ws, btn["x"], btn["y"])
    return btn


def click_button_by_text_polled(ws, *texts, attempts=8, delay=0.5):
    """Poll for a button instead of a single fixed-delay lookup.

    Gotcha #18: only the first dialog-detection step used to poll; the
    follow-up "Export to..." and "OK" lookups were single-shot after a flat
    1.5s. On MB51 that transition rendered slower than 1.5s and the run died
    with 'OK confirmation button not found' while the dialog was appearing.
    Every lookup in the export chain must tolerate variable render speed."""
    for _ in range(attempts):
        btn = click_button_by_text(ws, *texts)
        if btn:
            return btn
        time.sleep(delay)
    return None


def click_button_by_title(ws, title_substr, attempts=8, delay=0.5):
    """Some SAP buttons are icon-only (the format dialog's Continue
    checkmark) and carry no usable visible text - only a title."""
    for _ in range(attempts):
        candidates = find_visible_by_title(ws, title_substr, max_size=40)
        if candidates:
            btn = candidates[0]
            click_element_by_rect(ws, btn["x"], btn["y"])
            return btn
        time.sleep(delay)
    return None


def trigger_export_icon(ws):
    """Click the toolbar "Export" icon (title exactly "Export") and pick
    "Spreadsheet" from the dropdown it reveals, landing in flow A.

    Silently does nothing when the icon is absent, so the caller's normal
    flow detection reports "no dialog" exactly as it would for any
    inapplicable shortcut."""
    icons = find_visible_by_title(ws, "Export", exact=True, max_size=80)
    if not icons:
        return
    icon = icons[0]
    click_element_by_rect(ws, icon["x"], icon["y"])
    # The dropdown pre-renders off-screen before repositioning (gotcha #20);
    # find_visible_leaf_by_text's viewport check is what stops the click
    # landing at y = -99984 and silently doing nothing.
    click_button_by_text_polled(ws, "Spreadsheet", attempts=6)


def run_flow_c(ws, base_filename):
    """'Text with Tabs' -> Continue -> switch 'Save as' to Spreadsheet
    (*.xlsx) -> set filename. Leaves the OK click to the shared tail."""
    btn = click_button_by_text(ws, "Text with Tabs")
    if not btn:
        print("ERROR: the 'Text with Tabs' option was not found.")
        return False
    print(f"Selected 'Text with Tabs' at ({btn['x']}, {btn['y']})")
    time.sleep(0.5)

    cont_btn = click_button_by_title(ws, "continue")
    if not cont_btn:
        print("ERROR: the 'Continue' button was not found.")
        return False
    print(f"Clicked 'Continue' at ({cont_btn['x']}, {cont_btn['y']})")

    # Poll for the format dropdown's dedicated arrow trigger
    # ('popupDialogFilterCbx-btn') rather than clicking near the field.
    js_combo = """
    (function() {
        const btn = document.getElementById('popupDialogFilterCbx-btn');
        if (!btn) return JSON.stringify({found: false});
        const r = btn.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return JSON.stringify({found: false});
        return JSON.stringify({found: true, x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """
    combo = {"found": False}
    for _ in range(12):
        combo = evaluate(ws, js_combo)
        if combo.get("found"):
            break
        time.sleep(0.5)

    if not combo.get("found"):
        print("ERROR: the 'Save as' format dropdown button was not found.")
        return False
    click_element_by_rect(ws, combo["x"], combo["y"])
    print(f"Opened the 'Save as' dropdown at ({combo['x']}, {combo['y']})")
    time.sleep(0.5)

    xlsx_btn = click_button_by_text_polled(ws, "Spreadsheet Files (*.xlsx)", attempts=6)
    if not xlsx_btn:
        print("ERROR: 'Spreadsheet Files (*.xlsx)' was not found in the dropdown. "
              "Without it the export would silently produce a .txt file, so stopping.")
        return False
    print(f"Selected 'Spreadsheet Files (*.xlsx)' at ({xlsx_btn['x']}, {xlsx_btn['y']})")
    time.sleep(0.3)

    js_fill = """
    (function() {
        const value = %s;
        const el = document.getElementById('popupDialogInputField');
        if (!el) return JSON.stringify({found: false});
        %s
        return JSON.stringify({found: true, value: el.value});
    })()
    """ % (json.dumps(base_filename + ".xlsx"), cdp_common.JS_SET_VALUE)
    fill_result = evaluate(ws, js_fill)
    print("Filename set:", fill_result)
    if not fill_result.get("found"):
        print("ERROR: the filename field ('popupDialogInputField') was not found.")
        return False
    return True


def detect_flow(ws, poll_attempts=8, delay=0.5):
    """Identify which export dialog (if any) is now open. Read-only.

    Polls rather than checking once after a flat sleep: gotcha #13, a dialog
    that a check right after sleep(2) reported as missing showed up in a
    screenshot taken a couple of seconds later."""
    for _ in range(poll_attempts):
        time.sleep(delay)

        result = evaluate(ws, js_find_filename_field(FLOW_A_DEFAULT_PATTERN))
        if result.get("found"):
            return "A", result

        result = evaluate(ws, js_find_filename_field(FLOW_B_DEFAULT_PATTERN))
        if result.get("found"):
            return "B", result

        result = evaluate(ws, JS_FLOW_C_VISIBLE)
        if result.get("found"):
            return "C", result

    return None, {"found": False}


def main(tcode, base_filename=None):
    webgui_tab = get_webgui_tab()
    if not webgui_tab:
        print("ERROR: no WebGUI iframe target found. Is a t-code screen open (post-Execute)?")
        sys.exit(1)

    print(f"Connected to WebGUI: {webgui_tab.get('url')}")
    ws = connect(webgui_tab["webSocketDebuggerUrl"], timeout=20)

    base_filename = base_filename or f"{tcode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Target export file name: {base_filename}.xlsx")

    mechanisms = [
        # Tried first: harmless where it does nothing (MB52), but it opens
        # flow A directly on MB51, so it is never a wasted step (gotcha #17).
        ("Shift+F4", lambda w: dispatch_key_combo(w, key="F4", code="F4", vk=115, shift=True)),
        ("Ctrl+Shift+F7", lambda w: dispatch_key_combo(w, key="F7", code="F7", vk=118, ctrl=True, shift=True)),
        ("Shift+F7", lambda w: dispatch_key_combo(w, key="F7", code="F7", vk=118, shift=True)),
        ("Ctrl+Shift+F9", lambda w: dispatch_key_combo(w, key="F9", code="F9", vk=120, ctrl=True, shift=True)),
        ("Export icon", trigger_export_icon),
    ]

    flow, detected = None, {"found": False}
    for label, trigger in mechanisms:
        print(f"Trying {label} (Export)...")
        trigger(ws)
        flow, detected = detect_flow(ws)
        print(f"After {label}: flow={flow}, {detected}")
        if flow is not None:
            print(f"{label} opened the flow-{flow} dialog.")
            break

        # If that trigger opened SOMETHING we do not recognise, stop rather
        # than firing the next shortcut into an open modal - the original
        # code did exactly that, so the final error named the last shortcut
        # tried instead of the dialog actually blocking progress.
        popup = describe_visible_dialog(ws)
        if popup.get("count"):
            print(f"ERROR: {label} opened an unrecognised dialog, so no further "
                  f"shortcuts were tried (firing into an open modal would make the "
                  f"diagnosis worse). Dialog text: {popup.get('texts')}")
            cdp_common.screenshot_on_failure(f"nerp_export_unknown_dialog_{tcode}")
            ws.close()
            sys.exit(1)

    if flow is None:
        print("ERROR: no recognised export dialog appeared after Shift+F4, "
              "Ctrl+Shift+F7, Shift+F7, Ctrl+Shift+F9, and the toolbar Export icon. "
              "This screen is most likely not a list at all (e.g. a single-record "
              "document view like CO03's order header). Do not guess further "
              "shortcuts - check the screenshot and ask how to proceed.")
        cdp_common.screenshot_on_failure(f"nerp_export_no_dialog_{tcode}")
        ws.close()
        sys.exit(1)

    # Now write the filename into whichever field the detected flow owns.
    if flow == "A":
        filled = evaluate(ws, js_set_filename_field(FLOW_A_DEFAULT_PATTERN, base_filename))
        print("Filename set:", filled)
        btn = click_button_by_text_polled(ws, "Export to...")
        if not btn:
            print("ERROR: the 'Export to...' button was not found.")
            cdp_common.screenshot_on_failure(f"nerp_export_to_{tcode}")
            ws.close()
            sys.exit(1)
        print(f"Clicked 'Export to...' at ({btn['x']}, {btn['y']})")
    elif flow == "B":
        filled = evaluate(ws, js_set_filename_field(FLOW_B_DEFAULT_PATTERN,
                                                    base_filename + ".xlsx"))
        print("Filename set:", filled)
    elif flow == "C":
        if not run_flow_c(ws, base_filename):
            cdp_common.screenshot_on_failure(f"nerp_export_flow_c_{tcode}")
            ws.close()
            sys.exit(1)

    # Poll for "OK" rather than guessing a duration. Render speed varies by
    # flow AND by dataset size: a "Stop Application" indicator sits over the
    # dialog for 20s+ while SAP prepares a large export (gotcha #23). The
    # loop exits the instant the button is seen, so a generous cap is free
    # on the fast path and is the only thing that matters on the slow one.
    ok_btn = click_button_by_text_polled(ws, "OK", attempts=240, delay=0.5)
    if not ok_btn:
        print("ERROR: the 'OK' confirmation button never appeared (waited ~120s).")
        cdp_common.screenshot_on_failure(f"nerp_export_ok_{tcode}")
        ws.close()
        sys.exit(1)
    print(f"Clicked 'OK' at ({ok_btn['x']}, {ok_btn['y']})")

    # Confirm via the status-bar "Download ... .xlsx" message. A synthetic
    # click on a dialog's OK has occasionally landed as focus-only, leaving
    # the dialog open (gotcha #14), so poll and re-click once partway
    # through rather than doing one click and one check.
    js_verify = """
    (function() {
        return JSON.stringify({
            downloadMsg: /Download[^\\n]{0,200}\\.xlsx/i.test(document.body.textContent)
        });
    })()
    """
    verify = {"downloadMsg": False}
    for attempt in range(120):
        time.sleep(0.5)
        verify = evaluate(ws, js_verify)
        if verify.get("downloadMsg"):
            break
        if attempt == 10:
            retry = click_button_by_text(ws, "OK")
            if retry:
                print(f"Re-clicked 'OK' at ({retry['x']}, {retry['y']}) "
                      "(the first click may have registered as focus only)")

    if verify.get("downloadMsg"):
        print(f"SUCCESS: Export completed as '{base_filename}.xlsx' (flow {flow})")
    else:
        print(f"WARNING: clicked through the whole flow but no 'Download ... .xlsx' "
              f"confirmation text was found. Expected file name: "
              f"'{base_filename}.xlsx' - verify visually. It may have completed "
              "just after the polling window closed.")
        cdp_common.screenshot_on_failure(f"nerp_export_unconfirmed_{tcode}")

    ws.close()
    return verify.get("downloadMsg", False)


if __name__ == "__main__":
    args = sys.argv[1:]
    name = None
    if "--name" in args:
        i = args.index("--name")
        name = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    main(args[0] if args else "EXPORT", base_filename=name)

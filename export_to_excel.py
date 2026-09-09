"""
"Export to excel file": on the currently-open SAP WebGUI list/data screen
(after a T-code has been opened and Executed), open the export dialog and
save as "<T-code>_<YYYYMMDD_HHMMSS>.xlsx".

Three different SAP list types use three different export mechanisms, so
this script tries shortcuts in order until one opens a recognized dialog:

  Flow A - "Export As" dialog (Ctrl+Shift+F7, standard ALV grid reports like
  MB52): filename field defaults to "EXPORT_YYYYMMDD_HHMMSS", then you click
  "Export to..." which opens a second "Enter file name to save" dialog, then
  click "OK".

  Flow B - direct "Enter file name to save" dialog (Shift+F7, hierarchical/
  tree list reports like ZRPPM400300's MRP list): filename field defaults to
  something like "MRP_List_YYYYMMDD.XLSX", and there's no intermediate
  "Export to..." step - you fill the field and click "OK" directly.

  Flow C - "Save list in file..." format-choice dialog (Ctrl+Shift+F9, e.g.
  ZRMMK121040's "Split xls" list): no filename field yet, just format radio
  buttons (Unconverted / Text with Tabs / Rich Text / HTML / Clipboard) with
  no direct Excel choice here. Select "Text with Tabs", click "Continue",
  which opens an "Enter file name to save" dialog - but its "Save as"
  dropdown DOES have a "Spreadsheet Files (*.xlsx)" option (initially
  defaulted to "Text Files (*.txt)"), so switch to that, set the filename to
  end in .xlsx, and click "OK".

  Final fallback - toolbar "Export" icon (a small icon + dropdown-chevron
  button, `title="Export"`, e.g. ZRPPD410200's "Production Order Change
  History Report"): click it to reveal a dropdown (Spreadsheet / Local File
  / Send / SAPoffice Folders / ABC Analys. / HTML download), click
  "Spreadsheet", which lands in the exact same flow-A "Export As" dialog as
  Ctrl+Shift+F7 - so once triggered it's completed via flow A's existing
  "Export to..." -> "Enter file name to save" -> "OK" steps. Used only if
  none of the four shortcuts above opened a recognized dialog.

Usage:
    python export_to_excel.py MB52
    python export_to_excel.py ZRPPM400300
    python export_to_excel.py ZRMMK121040
    python export_to_excel.py ZRPPD410200

The exported file lands in the user's default SAP GUI download directory
(seen as e.g. "Z:\\MB52_20260905_095146.xlsx" in the status bar confirmation).
"""
import json
import sys
import time
from datetime import datetime

from cdp_common import get_webgui_tab, send, click_element_by_rect, dispatch_key_combo, find_visible_leaf_by_text
import websocket


# Flow A: two-step "Export As" -> "Export to..." -> "Enter file name to save" -> OK
FLOW_A_DEFAULT_PATTERN = r"^EXPORT_\d{8}_\d{6}$"
# Flow B: one-step "Enter file name to save" -> OK, filename already ends in .XLSX
FLOW_B_DEFAULT_PATTERN = r"\.XLSX$"


def js_locate_filename_field(pattern, new_value):
    return """
    (function() {
        let inputs = Array.from(document.querySelectorAll('input[type="text"]'));
        let field = inputs.find(inp => %s.test((inp.value || '').trim()));
        if (!field) return JSON.stringify({found: false});
        field.focus();
        field.value = '%s';
        field.dispatchEvent(new Event('input', { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));
        return JSON.stringify({found: true, id: field.id, value: field.value});
    })()
    """ % (f"/{pattern}/i", new_value)


def js_flow_c_visible():
    """Flow C's first dialog has no filename field - detect it instead by
    the presence of the visible 'Text with Tabs' format radio option."""
    return """
    (function() {
        let found = Array.from(document.querySelectorAll('*')).some(el => {
            let t = (el.textContent || '').trim();
            if (t !== 'Text with Tabs') return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        return JSON.stringify({found: found});
    })()
    """


def click_button_by_text(ws, *texts, msg_id):
    candidates = find_visible_leaf_by_text(ws, *texts, msg_id=msg_id)
    if not candidates:
        return None
    btn = candidates[0]
    click_element_by_rect(ws, btn["x"], btn["y"], msg_id_start=msg_id + 10)
    return btn


def click_button_by_text_polled(ws, *texts, msg_id, attempts=8, delay=0.5):
    """Like click_button_by_text, but polls instead of a single fixed-delay
    lookup. Different shortcuts render their follow-up dialogs at different
    speeds (e.g. Shift+F4's "Export to..." -> "Enter file name to save"
    transition on MB51 was observed taking longer than the previously fixed
    1.5s wait, causing a false 'OK not found' error), so every button
    lookup in the export chain should tolerate slow rendering the same way
    the initial dialog-detection step already does."""
    for _ in range(attempts):
        candidates = find_visible_leaf_by_text(ws, *texts, msg_id=msg_id)
        if candidates:
            btn = candidates[0]
            click_element_by_rect(ws, btn["x"], btn["y"], msg_id_start=msg_id + 10)
            return btn
        time.sleep(delay)
    return None


def click_button_by_title(ws, title_substr, msg_id):
    """Some SAP icon-only buttons (e.g. the format dialog's 'Continue'
    checkmark) have no usable visible text, only a `title` attribute."""
    js = """
    (function() {
        let icons = Array.from(document.querySelectorAll('div, span')).filter(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0 || r.width > 40 || r.height > 40) return false;
            return (el.title || '').toLowerCase().includes('%s');
        });
        return JSON.stringify(icons.map(el => {
            const r = el.getBoundingClientRect();
            return { tag: el.tagName, id: el.id, title: el.title, x: r.left+r.width/2, y: r.top+r.height/2 };
        }));
    })()
    """ % title_substr.lower()
    resp = send(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True}, msg_id=msg_id)
    candidates = json.loads(resp["result"]["result"]["value"])
    if not candidates:
        return None
    btn = candidates[0]
    click_element_by_rect(ws, btn["x"], btn["y"], msg_id_start=msg_id + 10)
    return btn


def trigger_export_icon(ws):
    """Click the toolbar 'Export' icon (title="Export" exactly, small
    icon+dropdown-chevron button, e.g. id `_MB_EXPORT102`) then select
    "Spreadsheet" from the dropdown it reveals. This is a mouse-driven
    trigger rather than a keyboard shortcut, used as the last-resort
    fallback when no shortcut opens a recognized dialog. Silently does
    nothing (returns without error) if the icon isn't present on this
    screen - the caller's normal flow-detection polling will then correctly
    report "no dialog found" same as any other non-applicable shortcut."""
    js_find_icon = """
    (function() {
        let btn = Array.from(document.querySelectorAll('div')).find(el => (el.title || '').trim() === 'Export');
        if (!btn) return JSON.stringify({found: false});
        const r = btn.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return JSON.stringify({found: false});
        return JSON.stringify({found: true, x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """
    resp = send(ws, "Runtime.evaluate", {"expression": js_find_icon, "returnByValue": True}, msg_id=2)
    icon = json.loads(resp["result"]["result"]["value"])
    if not icon.get("found"):
        return
    click_element_by_rect(ws, icon["x"], icon["y"], msg_id_start=3)
    click_button_by_text_polled(ws, "Spreadsheet", msg_id=6, attempts=6)


def run_flow_c(ws, base_filename):
    """Select 'Text with Tabs' -> Continue -> switch 'Save as' dropdown to
    Spreadsheet (*.xlsx) -> set filename -> OK."""
    btn = click_button_by_text(ws, "Text with Tabs", msg_id=60)
    if not btn:
        print("ERROR: 'Text with Tabs' option not found.")
        return False
    print(f"Selected 'Text with Tabs' at ({btn['x']}, {btn['y']})")
    time.sleep(0.5)

    cont_btn = click_button_by_title(ws, "continue", msg_id=70)
    if not cont_btn:
        print("ERROR: 'Continue' button not found.")
        return False
    print(f"Clicked 'Continue' at ({cont_btn['x']}, {cont_btn['y']})")

    # The follow-up "Enter file name to save" dialog can take a moment to
    # render, so poll for its format-dropdown's dedicated button
    # ('popupDialogFilterCbx-btn' - the actual arrow trigger, more precise
    # than clicking near the field) rather than a single fixed sleep.
    js_locate_combo_btn = """
    (function() {
        let btn = document.getElementById('popupDialogFilterCbx-btn');
        if (!btn) return JSON.stringify({found: false});
        const r = btn.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return JSON.stringify({found: false});
        return JSON.stringify({found: true, x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """
    combo = {"found": False}
    for _ in range(6):
        resp = send(ws, "Runtime.evaluate", {"expression": js_locate_combo_btn, "returnByValue": True}, msg_id=80)
        combo = json.loads(resp["result"]["result"]["value"])
        if combo.get("found"):
            break
        time.sleep(0.5)

    if not combo.get("found"):
        print("ERROR: 'Save as' format dropdown button not found.")
        return False
    click_element_by_rect(ws, combo["x"], combo["y"], msg_id_start=81)
    print(f"Opened 'Save as' dropdown at ({combo['x']}, {combo['y']})")
    time.sleep(0.5)

    xlsx_btn = click_button_by_text(ws, "Spreadsheet Files (*.xlsx)", msg_id=90)
    if not xlsx_btn:
        print("ERROR: 'Spreadsheet Files (*.xlsx)' option not found in dropdown.")
        return False
    print(f"Selected 'Spreadsheet Files (*.xlsx)' at ({xlsx_btn['x']}, {xlsx_btn['y']})")
    time.sleep(0.3)

    js_fill = """
    (function() {
        let field = document.getElementById('popupDialogInputField');
        if (!field) return JSON.stringify({found: false});
        field.focus();
        field.value = '%s.xlsx';
        field.dispatchEvent(new Event('input', { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));
        return JSON.stringify({found: true, value: field.value});
    })()
    """ % base_filename
    resp2 = send(ws, "Runtime.evaluate", {"expression": js_fill, "returnByValue": True}, msg_id=100)
    fill_result = json.loads(resp2["result"]["result"]["value"])
    print("Filename set:", fill_result)
    if not fill_result.get("found"):
        print("ERROR: filename field ('popupDialogInputField') not found.")
        return False

    return True


def main(tcode):
    webgui_tab = get_webgui_tab()
    if not webgui_tab:
        print("ERROR: WebGUI iframe target not found. Is a t-code screen open (post-Execute)?")
        sys.exit(1)

    print(f"Connected to WebGUI: {webgui_tab.get('url')}")
    ws = websocket.create_connection(webgui_tab["webSocketDebuggerUrl"], timeout=20)
    send(ws, "Runtime.enable", msg_id=1)

    base_filename = f"{tcode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def try_shortcut(label, trigger_fn):
        """Run trigger_fn(ws) (a keyboard dispatch or a mouse-click
        sequence), then check which flow's dialog (if any) shows up.
        Returns (flow, fill_result) where flow is 'A', 'B', 'C', or None."""
        print(f"Trying {label} (Export)...")
        trigger_fn(ws)

        # Poll for up to ~4s rather than a single fixed sleep - dialogs can
        # take longer than 2s to render, which previously caused false
        # negatives (dialog shows up in a screenshot taken moments later,
        # even though the check right after a flat sleep(2) found nothing).
        for _ in range(8):
            time.sleep(0.5)

            resp_a = send(ws, "Runtime.evaluate", {
                "expression": js_locate_filename_field(FLOW_A_DEFAULT_PATTERN, base_filename)
            }, msg_id=10)
            result_a = json.loads(resp_a["result"]["result"]["value"])
            if result_a.get("found"):
                return "A", result_a

            resp_b = send(ws, "Runtime.evaluate", {
                "expression": js_locate_filename_field(FLOW_B_DEFAULT_PATTERN, base_filename + ".xlsx")
            }, msg_id=11)
            result_b = json.loads(resp_b["result"]["result"]["value"])
            if result_b.get("found"):
                return "B", result_b

            resp_c = send(ws, "Runtime.evaluate", {"expression": js_flow_c_visible()}, msg_id=12)
            result_c = json.loads(resp_c["result"]["result"]["value"])
            if result_c.get("found"):
                return "C", result_c

        return None, {"found": False}

    print(f"Target export file name: {base_filename}.xlsx")

    # Try mechanisms in order until one opens a recognized export dialog.
    # - Shift+F4: tried first (see gotcha #17 for what it actually does)
    # - Ctrl+Shift+F7: standard ALV grid reports (e.g. MB52) -> flow A
    # - Shift+F7: hierarchical/tree list reports (e.g. ZRPPM400300) -> flow B
    # - Ctrl+Shift+F9: some reports only respond to this -> flow C
    # - Export icon: last-resort mouse-driven fallback -> flow A
    mechanisms = [
        ("Shift+F4", lambda ws: dispatch_key_combo(ws, key="F4", code="F4", vk=115, shift=True, msg_id_start=2)),
        ("Ctrl+Shift+F7", lambda ws: dispatch_key_combo(ws, key="F7", code="F7", vk=118, ctrl=True, shift=True, msg_id_start=2)),
        ("Shift+F7", lambda ws: dispatch_key_combo(ws, key="F7", code="F7", vk=118, shift=True, msg_id_start=2)),
        ("Ctrl+Shift+F9", lambda ws: dispatch_key_combo(ws, key="F9", code="F9", vk=120, ctrl=True, shift=True, msg_id_start=2)),
        ("Export icon", trigger_export_icon),
    ]

    flow, fill_result = None, {"found": False}
    for label, trigger_fn in mechanisms:
        flow, fill_result = try_shortcut(label, trigger_fn)
        print(f"After {label}: flow={flow}, {fill_result}")
        if flow is not None:
            break

    if flow is None:
        print("ERROR: No recognized export dialog found after trying "
              "Shift+F4, Ctrl+Shift+F7, Shift+F7, Ctrl+Shift+F9, and the Export icon. "
              "Did a dialog open?")
        ws.close()
        sys.exit(1)

    if flow == "A":
        btn = click_button_by_text_polled(ws, "Export to...", msg_id=20)
        if not btn:
            print("ERROR: 'Export to...' button not found.")
            ws.close()
            sys.exit(1)
        print(f"Clicked 'Export to...' at ({btn['x']}, {btn['y']})")
    elif flow == "C":
        if not run_flow_c(ws, base_filename):
            ws.close()
            sys.exit(1)

    # Poll for "OK" rather than guessing a wait duration - the follow-up
    # "Enter file name to save" dialog's render speed varies by which
    # shortcut/flow triggered it (see click_button_by_text_polled), AND by
    # dataset size: a "Stop Application" loading indicator shows while SAP
    # prepares a large export (seen firsthand with MB51 + Movement Type
    # filter returning hundreds of rows) before the dialog appears, and how
    # long that takes isn't predictable from the outside. The loop already
    # exits the instant the dialog is detected, so a generous safety cap
    # costs nothing on the fast path - it only matters for genuinely slow
    # exports, so err large here rather than tuning a specific duration.
    ok_btn = click_button_by_text_polled(ws, "OK", msg_id=30, attempts=240, delay=0.5)
    if not ok_btn:
        print("ERROR: 'OK' confirmation button not found.")
        ws.close()
        sys.exit(1)
    print(f"Clicked 'OK' at ({ok_btn['x']}, {ok_btn['y']})")

    # Verify via the status-bar "Download ... .xlsx" confirmation message.
    # The OK click has occasionally landed as focus-only (dialog stays open)
    # rather than a full click-through, so poll and re-click once if the
    # dialog is still there rather than a single fixed sleep + check.
    js_verify = """
    (function() {
        return JSON.stringify({ downloadMsg: /Download.*\\.xlsx/i.test(document.body.textContent) });
    })()
    """
    # As with the "OK" lookup above, this errs toward a generous cap rather
    # than a tuned duration: writing a large export to disk can itself take
    # a while after OK is clicked, and the loop exits immediately on success.
    verify = {"downloadMsg": False}
    for attempt in range(120):
        time.sleep(0.5)
        resp2 = send(ws, "Runtime.evaluate", {"expression": js_verify, "returnByValue": True}, msg_id=50)
        verify = json.loads(resp2["result"]["result"]["value"])
        if verify.get("downloadMsg"):
            break
        if attempt == 10:
            # Still not confirmed partway through polling - the dialog may
            # still be open with OK merely focused; try clicking it again.
            retry_btn = click_button_by_text(ws, "OK", msg_id=55)
            if retry_btn:
                print(f"Re-clicked 'OK' at ({retry_btn['x']}, {retry_btn['y']}) (first click may not have registered)")

    if verify.get("downloadMsg"):
        print(f"SUCCESS: Export completed as '{base_filename}.xlsx' (flow {flow})")
    else:
        print(f"WARNING: clicked through the flow but no 'Download ...xlsx' confirmation text was found. "
              f"Expected file name: '{base_filename}.xlsx' - verify visually.")

    ws.close()


if __name__ == "__main__":
    tcode = sys.argv[1] if len(sys.argv) > 1 else "EXPORT"
    main(tcode)

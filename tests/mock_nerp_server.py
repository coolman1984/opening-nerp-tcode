"""
A local stand-in for the N-ERP portal that reproduces the specific quirks
this skill exists to survive. It is not a pretty mock - it is a trap course.

Deliberately reproduced, each mapping to a numbered gotcha in SKILL.md:

  #4/#24  The "Go" button does not exist for the first ~2.5s, so anything
          that assumes a fixed load duration fails.
  #5      Every button is a <div> that reacts to mousedown+mouseup only.
          element.click() genuinely does nothing, exactly as in Fiori/WebGUI.
  #6      The selection screen lives in a cross-origin iframe (served from
          the other loopback name so Chrome gives it its own CDP target),
          alongside an AppDynamics decoy whose URL-ENCODED address also
          contains "webgui" - and the decoy is stuffed with inputs, so a
          naive "most inputs wins" without the adrum exclusion picks it.
  #7      Fields carry unstable ids and stable `title` labels.
  #12     A stale, near-blank webgui iframe is emitted BEFORE the live one.
  #13/#18 Dialogs and their follow-up buttons render after a delay long
          enough to defeat a single fixed sleep.
  #16     The live iframe's fields appear a beat after the document itself.
  #17     Which shortcut triggers the export is per-"transaction" (?flow=).
  #20     The dropdown item renders at y = -99984 first, then repositions.
  #23     The final confirmation is delayed, as a big export would be.
  #25     Execute shows the busy indicator before the results render.

Run standalone to poke at it by hand:
    python mock_nerp_server.py            # prints its URL and serves
"""
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# Shared look and button behaviour. `sapButton` wires mousedown/mouseup and
# deliberately ignores click, so a synthetic element.click() does nothing -
# the exact behaviour that forces Input.dispatchMouseEvent (gotcha #5).
COMMON_JS = """
window.__clickEventsSeen = 0;
function sapButton(el, handler) {
    let armed = false;
    el.addEventListener('mousedown', () => { armed = true; });
    el.addEventListener('mouseup', () => { if (armed) { armed = false; handler(); } });
    el.addEventListener('click', () => { window.__clickEventsSeen++; });
}
function mkButton(text, opts) {
    opts = opts || {};
    const d = document.createElement('div');
    d.textContent = text;
    d.className = 'btn';
    if (opts.id) d.id = opts.id;
    if (opts.title) d.title = opts.title;
    if (opts.icon) d.className = 'btn icon';
    return d;
}
"""

COMMON_CSS = """
body { font-family: Arial, sans-serif; font-size: 13px; margin: 0; padding: 8px; }
.btn { display: inline-block; border: 1px solid #999; background: #eee;
       padding: 4px 10px; margin: 2px; cursor: pointer; user-select: none; }
.btn.icon { padding: 2px; width: 20px; height: 20px; text-align: center; }
.dialog { position: fixed; top: 60px; left: 40px; width: 420px; background: #fff;
          border: 2px solid #567; padding: 10px; z-index: 100; }
.menu { position: absolute; background: #fff; border: 1px solid #999; z-index: 200; }
.menu div { padding: 3px 12px; cursor: pointer; }
label { display: inline-block; width: 130px; }
"""

SHELL_HTML = """<!doctype html>
<html><head><title>N-ERP Home</title><style>%(css)s</style></head>
<body>
<h3>N-ERP Portal (mock)</h3>
<div id="shell">loading the shell...</div>
<div id="frames"></div>
<script>
%(js)s
// The iframe host is a different SITE to Chrome (both names are mapped to
// loopback with --host-resolver-rules), so with --site-per-process the
// iframes below become out-of-process frames and therefore separate CDP
// targets - which is how the real portal behaves, and the entire reason
// get_webgui_tab() has to exist at all.
const qp = new URLSearchParams(location.search);
const IFRAME_HOST = qp.get('fh') || (location.hostname === 'localhost' ? '127.0.0.1' : 'localhost');
const BASE = location.protocol + '//' + IFRAME_HOST + ':' + location.port;
const FLOW = qp.get('flow') || 'a';
const TC = qp.get('tc') || 'MB52';

// Gotcha #4/#24: nothing to interact with for the first couple of seconds.
setTimeout(function() {
    const shell = document.getElementById('shell');
    shell.innerHTML = '';
    const input = document.createElement('input');
    input.placeholder = 'Search Program';
    input.id = 'searchProgram';
    input.style.width = '260px';
    shell.appendChild(input);

    const go = mkButton('Go', {id: 'goBtn'});
    sapButton(go, function() {
        document.getElementById('frames').innerHTML =
            // Decoy first: an AppDynamics wrapper whose URL-ENCODED address
            // contains "webgui", loaded with plenty of inputs so that
            // matching it would beat the real one on input count.
            '<iframe src="' + BASE + '/adrum-xd.html#https%%3A%%2F%%2Fnerps%%2Fsap%%2Fbc%%2Fgui%%2Fsap%%2Fits%%2Fwebgui%%3Bfoo" ' +
            'style="width:200px;height:30px;border:1px dotted #f88"></iframe>' +
            // Stale placeholder from a "previous t-code", before the live one.
            '<iframe src="' + BASE + '/sap/bc/gui/sap/its/webgui?stale=1" ' +
            'style="width:300px;height:60px;border:1px solid #ccc"></iframe>' +
            // The live selection screen.
            '<iframe src="' + BASE + '/sap/bc/gui/sap/its/webgui?live=1&flow=' + FLOW +
            '&tc=' + encodeURIComponent(TC) + '" ' +
            'style="width:760px;height:460px;border:1px solid #888"></iframe>';
    });
    shell.appendChild(go);
}, %(go_delay)d);
</script>
</body></html>
"""

ADRUM_HTML = """<!doctype html>
<html><head><title>adrum</title></head><body>
<!-- The decoy carries many inputs on purpose: excluding it must be done by
     URL, not by "whichever target has the most fields". -->
%(inputs)s
</body></html>
"""

STALE_HTML = """<!doctype html>
<html><head><title>SAP</title><style>%(css)s</style></head><body>
<!-- A stale webgui target: near-blank, one transaction-code box. -->
<input type="text" title="Transaction Code" id="stale_okcode">
</body></html>
"""

WEBGUI_HTML = """<!doctype html>
<html><head><title>%(title)s</title><style>%(css)s</style></head>
<body>
<div id="screen">loading...</div>
<div id="hiddenLoadingToolbarButton" title="Click to stop long-running application"
     style="display:none; width:24px; height:24px; background:#fc0;">busy</div>
<div id="statusbar"></div>
<script>
%(js)s
const params = new URLSearchParams(location.search);
const FLOW = (params.get('flow') || 'a').toLowerCase();
const TC = params.get('tc') || 'MB52';
let state = 'selection';
let chosenName = '';
let comboValue = 'Text Files (*.txt)';

function statusText(t) { document.getElementById('statusbar').textContent = t; }

// Gotcha #16: the document is 'complete' before the fields exist, so a
// caller that proceeds on target-existence alone finds an empty screen.
setTimeout(function() {
    const s = document.getElementById('screen');
    // The t-code appears in the screen text, which is what the post-open
    // sanity check (gotcha #22) looks for.
    s.innerHTML =
        '<h4>Stock Overview: ' + TC + ' Selection Screen</h4>' +
        // Gotcha #7: ids are dynpro-style noise, titles are the stable labels.
        '<div><label>Material</label><input type="text" id="M0:46:::2:34" title="Material Number"></div>' +
        '<div><label>Plant</label><input type="text" id="M0:47:::2:35" title="Plant"></div>' +
        '<div><label>Storage Loc</label><input type="text" id="M0:48:::2:36" title="Storage Location"></div>';
    const exec = mkButton('Execute Emphasized', {id: 'execBtn', title: 'Execute (F8)'});
    sapButton(exec, runExecute);
    s.appendChild(exec);
}, %(fields_delay)d);

function runExecute() {
    if (state !== 'selection') return;
    // Gotcha #25: the busy indicator appears, then the results render.
    const busy = document.getElementById('hiddenLoadingToolbarButton');
    busy.style.display = 'block';
    setTimeout(function() {
        busy.style.display = 'none';
        state = 'list';
        const s = document.getElementById('screen');
        s.innerHTML = '<h4>Result list (mock)</h4><table id="alv">' +
            '<tr><th>Material</th><th>Plant</th><th>Qty</th></tr>' +
            '<tr><td>SM-A137FLBHMEB</td><td>P703</td><td>42</td></tr>' +
            '<tr><td>BN96-63249A</td><td>P703</td><td>17</td></tr></table>';
        if (FLOW === 'icon') {
            const ic = mkButton('\\u2913', {title: 'Export', icon: true});
            sapButton(ic, openExportMenu);
            s.appendChild(ic);
        }
    }, %(busy_ms)d);
}

document.addEventListener('keydown', function(e) {
    if (state !== 'list') return;
    const c = (e.ctrlKey ? 'C' : '') + (e.shiftKey ? 'S' : '') + (e.key || '');
    // Gotcha #17: which shortcut is bound to export is per-transaction.
    if (FLOW === 'a' && c === 'CSF7') openFlowA();
    else if (FLOW === 'b' && c === 'SF7') openFlowB();
    else if (FLOW === 'c' && c === 'CSF9') openFlowC();
    else if (FLOW === 'shiftf4' && c === 'SF4') openFlowA();
    else if (FLOW === 'unknown' && c === 'SF4') openUnknownDialog();
});

function dialog(id) {
    const d = document.createElement('div');
    d.className = 'dialog urPopupWindow';
    d.setAttribute('role', 'dialog');
    d.id = id;
    document.body.appendChild(d);
    return d;
}
function closeDialog(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function openUnknownDialog() {
    setTimeout(function() {
        const d = dialog('dlgUnknown');
        d.innerHTML = '<b>Information</b><p>No data was selected for this variant.</p>';
        const ok = mkButton('Continue', {});
        sapButton(ok, function() { closeDialog('dlgUnknown'); });
        d.appendChild(ok);
    }, %(dialog_ms)d);
}

// ---- Flow A: "Export As" -> "Export to..." -> file name -> OK ----------
function openFlowA() {
    setTimeout(function() {
        const d = dialog('dlgA');
        d.innerHTML = '<b>Export As...</b><br><label>File name</label>' +
                      '<input type="text" id="expName" value="EXPORT_20260101_101010">';
        const b = mkButton('Export to...', {});
        sapButton(b, function() {
            chosenName = document.getElementById('expName').value;
            closeDialog('dlgA');
            // Gotcha #18: this transition is slower than a 1.5s fixed sleep.
            setTimeout(openSaveDialog, %(slow_ms)d);
        });
        d.appendChild(b);
    }, %(dialog_ms)d);
}

// ---- Flow B: straight to the file-name dialog -------------------------
function openFlowB() {
    setTimeout(function() {
        const d = dialog('dlgB');
        d.innerHTML = '<b>Enter file name to save</b><br>' +
                      '<input type="text" id="expName" value="MRP_List_20260101.XLSX">';
        const ok = mkButton('OK', {});
        sapButton(ok, function() {
            chosenName = document.getElementById('expName').value;
            closeDialog('dlgB');
            finishDownload();
        });
        d.appendChild(ok);
    }, %(dialog_ms)d);
}

// ---- Flow C: format chooser -> Continue -> Save-as combo -> OK --------
function openFlowC() {
    setTimeout(function() {
        const d = dialog('dlgC');
        d.innerHTML = '<b>Save list in file...</b>';
        let picked = null;
        ['Unconverted', 'Text with Tabs', 'Rich Text', 'HTML', 'Clipboard'].forEach(function(fmt) {
            const row = mkButton(fmt, {});
            sapButton(row, function() {
                picked = fmt;
                row.style.background = '#cde';
            });
            d.appendChild(document.createElement('br'));
            d.appendChild(row);
        });
        // Icon-only Continue: no usable text, only a title (gotcha: this is
        // why click_button_by_title exists at all).
        const cont = mkButton('\\u2713', {title: 'Continue (Enter)', icon: true});
        sapButton(cont, function() {
            if (picked !== 'Text with Tabs') return;   // must actually be selected
            closeDialog('dlgC');
            setTimeout(openSaveDialogWithCombo, %(slow_ms)d);
        });
        d.appendChild(document.createElement('br'));
        d.appendChild(cont);
    }, %(dialog_ms)d);
}

function openSaveDialogWithCombo() {
    const d = dialog('dlgSaveC');
    d.innerHTML = '<b>Enter file name to save</b><br>' +
                  '<label>File name</label><input type="text" id="popupDialogInputField" value="">' +
                  '<br><label>Save as</label>' +
                  '<span id="popupDialogFilterCbx">' + comboValue + '</span>';
    const arrow = mkButton('\\u25BC', {id: 'popupDialogFilterCbx-btn', icon: true});
    sapButton(arrow, function() {
        const menu = document.createElement('div');
        menu.className = 'menu';
        // Gotcha #20: the menu is measured off-screen first, then moved into
        // place. A visibility check that only tests width/height finds the
        // item here, clicks at y = -99984, and silently hits nothing.
        menu.style.top = '-99984px';
        menu.style.left = '0px';
        ['Text Files (*.txt)', 'Spreadsheet Files (*.xlsx)', 'All Files (*.*)'].forEach(function(opt) {
            const item = document.createElement('div');
            item.textContent = opt;
            sapButton(item, function() {
                comboValue = opt;
                document.getElementById('popupDialogFilterCbx').textContent = opt;
                menu.remove();
            });
            menu.appendChild(item);
        });
        d.appendChild(menu);
        setTimeout(function() { menu.style.top = '160px'; menu.style.left = '60px'; },
                   %(offscreen_ms)d);
    });
    d.appendChild(arrow);

    const ok = mkButton('OK', {});
    sapButton(ok, function() {
        chosenName = document.getElementById('popupDialogInputField').value;
        closeDialog('dlgSaveC');
        // The whole point of flow C: picking "Text with Tabs" only yields a
        // real workbook if the Save-as combo was switched to xlsx first.
        finishDownload(comboValue.indexOf('xlsx') === -1 ? '.txt' : null);
    });
    d.appendChild(ok);
}

function openSaveDialog() {
    const d = dialog('dlgSave');
    d.innerHTML = '<b>Enter file name to save</b><br><span>' + chosenName + '</span>';
    const ok = mkButton('OK', {});
    sapButton(ok, function() { closeDialog('dlgSave'); finishDownload(); });
    d.appendChild(ok);
}

function openExportMenu() {
    const menu = document.createElement('div');
    menu.className = 'menu';
    menu.style.top = '-99984px';        // gotcha #20 again, on the icon path
    menu.style.left = '0px';
    ['Spreadsheet', 'Local File', 'Send', 'SAPoffice Folders', 'HTML download']
        .forEach(function(opt) {
            const item = document.createElement('div');
            item.textContent = opt;
            sapButton(item, function() {
                menu.remove();
                if (opt === 'Spreadsheet') openFlowA();
            });
            menu.appendChild(item);
        });
    document.body.appendChild(menu);
    setTimeout(function() { menu.style.top = '120px'; menu.style.left = '40px'; },
               %(offscreen_ms)d);
}

function finishDownload(forceExt) {
    // Gotcha #23: SAP takes its time writing a large export, so the
    // confirmation lands well after the OK click.
    setTimeout(function() {
        let name = chosenName || 'EXPORT';
        if (forceExt) name = name.replace(/\\.[^.]+$/, '') + forceExt;
        else if (!/\\.xlsx$/i.test(name)) name = name + '.xlsx';
        statusText('Download ' + 'Z:\\\\' + name + ' created');
    }, %(confirm_ms)d);
}
</script>
</body></html>
"""


class MockHandler(BaseHTTPRequestHandler):
    timings = {}

    def _send(self, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # The real portal frames itself; keep the mock permissive so the
        # iframes are allowed to load cross-origin.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        t = self.timings

        if path.startswith("/adrum-xd"):
            inputs = "\n".join(
                f'<input type="text" title="decoy {i}">' for i in range(25))
            return self._send(ADRUM_HTML % {"inputs": inputs})

        if "webgui" in path:
            if "stale=1" in query:
                return self._send(STALE_HTML % {"css": COMMON_CSS})
            return self._send(WEBGUI_HTML % {
                "css": COMMON_CSS, "js": COMMON_JS, "title": "SAP",
                "fields_delay": t.get("fields_delay", 800),
                "busy_ms": t.get("busy_ms", 1200),
                "dialog_ms": t.get("dialog_ms", 700),
                "slow_ms": t.get("slow_ms", 2000),
                "offscreen_ms": t.get("offscreen_ms", 350),
                "confirm_ms": t.get("confirm_ms", 1500),
            })

        return self._send(SHELL_HTML % {
            "css": COMMON_CSS, "js": COMMON_JS,
            "go_delay": t.get("go_delay", 2500),
        })

    def log_message(self, *args):
        pass  # keep the test output readable


def start(port=0, timings=None):
    """Start the mock in a daemon thread. Returns (server, base_url)."""
    MockHandler.timings = timings or {}
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://localhost:{server.server_port}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server, url = start(args.port)
    print(f"Mock N-ERP portal serving at {url}  (flows: ?flow=a|b|c|icon|shiftf4|unknown|none)")
    print("Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()

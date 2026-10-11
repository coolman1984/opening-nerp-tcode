"""Every popup G-MES shows - met, understood, dealt with safely, and remembered (HISTORY.md Phase 132).

Three kinds reach a run:
  1. native JavaScript dialogs (alert / confirm / prompt) - answered by the transport itself
     (cdp_common.answer_dialog: OK for an alert, Cancel for a question) and recorded here;
  2. G-MES's own floating windows (Nexacro child frames with a title bar): notices, messages,
     the Excel export dialog, popup lists;
  3. a popup that blocks a step nobody expected - the cause of a failure that names something else.

What is done with a floating window is decided by what it IS, read off the screen:
  informational  no input field, only OK / Close / X type buttons, no save / delete / approve
                 words -> closed with its own OK (or Close, or the title bar's X)
  decision       anything else (Yes / No, Save, a field, a list) -> NEVER clicked by guess:
                 the run stops and says what the popup says (CLAUDE.md 3.9)
A person can decide for one popup for good: `gmes_report.py popup-rule KEY close|stop|press:LABEL`.

Every popup met is kept in screens/popups.json (each G-MES site has its own): its key, title, text,
buttons, how often, when, and what was done - the catalogue the next run, person or agent reads."""
import datetime as _dt
import json
import os
import re
import tempfile

import cdp_common
import gmes_profile

CATALOGUE = "popups.json"
# Button words that only acknowledge (English and Korean as G-MES renders them).
SAFE_BUTTONS = {"ok", "close", "x", "확인", "닫기", "confirm", "got it", "dismiss"}
# Words that make a popup a decision whatever its buttons say.
RISKY = re.compile(r"(?i)\b(save|saved\?|delete|remove|approve|submit|apply|cancel the|overwrite|"
                   r"replace|transfer|send)\b|저장|삭제|승인|전송|적용|등록하시")
ACTIONS = ("auto", "close", "stop")                        # + "press:LABEL"
# The tool's OWN popups, whose answer is known: the Excel dialog left open by a failed export is
# cancelled (Cancel only stops that export - live-read 2026-10-11: title PopupExcelExport, a grid
# choice, Cancel / OK). A person's rule in the catalogue still wins.
BUILT_IN = {"popupExcelExport": "press:Cancel"}

# One survey of every visible floating window: its frame path, title, the texts and buttons
# inside its form, and whether it holds an input. Read-only.
JS_POPUP_SURVEY = """
(function() {
    const isVisible = %s;
    const out = [];
    const bars = Array.from(document.querySelectorAll('.TitleBarControl.titlebarChildFrame'));
    for (const bar of bars) {
        if (!isVisible(bar)) continue;
        const path = (bar.id || '').replace(/\\.titlebar$/, '');
        const root = document.getElementById(path) || bar.parentElement;
        const form = document.getElementById(path + '.form') || root;
        const texts = [], buttons = [];
        let inputs = 0;
        for (const el of (form ? form.querySelectorAll('div') : [])) {
            if (!isVisible(el)) continue;
            const cls = String(el.className || '');
            if (/\\b(Edit|MaskEdit|Combo|Calendar|Spin)\\b/.test(cls) && !/\\b(Static|TextArea)\\b/.test(cls)) {
                if (!/(:|\\.)(text|icontext|input)$/.test(el.id || '')) inputs++;
                continue;
            }
            if (/\\bButton\\b/.test(cls)) {
                const t = (el.textContent || '').trim();
                const r = el.getBoundingClientRect();
                if (t && t.length <= 30 && !buttons.some(b => b.text === t))
                    buttons.push({text: t, id: el.id, x: r.left + r.width / 2, y: r.top + r.height / 2});
                continue;
            }
            if (/\\b(Static|TextArea)\\b/.test(cls) && el.children.length <= 2) {
                const t = (el.textContent || '').trim();
                if (t && !texts.includes(t)) texts.push(t.slice(0, 200));
            }
        }
        const x = bar.querySelector('.closebutton');
        const xr = x ? x.getBoundingClientRect() : null;
        out.push({path: path, bar_id: bar.id, title: (bar.textContent || '').trim().slice(0, 80),
                  text: texts.join(' | ').slice(0, 600), buttons: buttons, inputs: inputs,
                  close: (x && isVisible(x)) ? {x: xr.left + xr.width / 2, y: xr.top + xr.height / 2} : null});
    }
    return JSON.stringify({count: out.length, popups: out});
})()
""" % cdp_common.JS_IS_VISIBLE


def survey(ws):
    """[popup] currently on screen - see JS_POPUP_SURVEY. [] when none (or the page cannot answer)."""
    try:
        r = cdp_common.evaluate(ws, JS_POPUP_SURVEY)
    except Exception:                                        # noqa: BLE001 - a survey must never fail a run
        return []
    return list(r.get("popups") or []) if isinstance(r, dict) else []


def key_of(popup):
    """A stable name for a popup: the last part of its frame path without the window number
    ('...mdiFrame.popupExcelExport' -> popupExcelExport; 'S9502UP01_0_12' -> S9502UP01)."""
    last = str(popup.get("path") or popup.get("bar_id") or "").split(".")[-1] or "popup"
    last = re.sub(r"_\d+_\d+$", "", last)
    return re.sub(r"[^\w-]", "_", last)[:60] or "popup"


def classify(popup, rule=None):
    """(action, why). action: 'close' (with which button), 'stop', or 'press:LABEL'."""
    if rule and rule != "auto":
        return rule, "the person's rule for this popup"
    labels = [str(b.get("text") or "").strip().lower() for b in popup.get("buttons") or []]
    words = f"{popup.get('title', '')} {popup.get('text', '')}"
    if popup.get("inputs"):
        return "stop", "it has a field to fill in - a decision, not a message"
    if RISKY.search(words):
        return "stop", "its words ask to save, delete, approve or send - never answered by guess"
    unsafe = [l for l in labels if l not in SAFE_BUTTONS]
    if unsafe:
        return "stop", f"it offers {', '.join(repr(u) for u in unsafe)} - a choice, not a message"
    return "close", "a message: no field, only OK / Close"


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------
def catalogue_path():
    return os.path.join(gmes_profile.SCREENS_DIR, CATALOGUE)


def catalogue():
    try:
        with open(catalogue_path(), encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    path = catalogue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".gmes-popups-", suffix=".partial", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _enabled():
    return os.environ.get("GMES_DOSSIER", "").strip().lower() not in ("off", "0", "no")


def remember(key, kind, title="", text="", buttons=(), action="", context="", now=None):
    """Count one meeting with a popup in the catalogue. Never raises."""
    if not _enabled():
        return None
    try:
        data = catalogue()
        at = (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        entry = data.get(key) or {"key": key, "kind": kind, "first_seen": at, "count": 0, "rule": "auto"}
        entry.update(kind=kind, last_seen=at, count=int(entry.get("count") or 0) + 1,
                     title=str(title)[:120] or entry.get("title", ""),
                     text=_redact(text)[:400] or entry.get("text", ""),
                     buttons=list(buttons) or entry.get("buttons", []),
                     last_action=action, last_context=str(context)[:120])
        data[key] = entry
        _save(data)
        return entry
    except Exception:                                        # noqa: BLE001 - best effort
        return None


def _redact(text):
    try:
        import gmes_redact
        return gmes_redact.redact_text(str(text or ""))
    except Exception:                                        # noqa: BLE001
        return str(text or "")


def rule_for(key):
    rule = str((catalogue().get(key) or {}).get("rule") or "auto")
    return BUILT_IN.get(key, "auto") if rule == "auto" else rule


def set_rule(key, rule):
    """A person's lasting decision for one popup: auto | close | stop | press:LABEL."""
    rule = str(rule or "").strip()
    if not (rule in ACTIONS or (rule.startswith("press:") and rule[6:].strip())):
        raise ValueError("a popup rule is auto, close, stop or press:LABEL")
    data = catalogue()
    entry = data.get(key)
    if not entry:
        raise ValueError(f"no popup {key!r} has been met yet - the catalogue knows: {', '.join(sorted(data)) or 'none'}")
    entry["rule"] = rule
    _save(data)
    return entry


def record_dialog(entry):
    """cdp_common.ON_DIALOG: a native dialog joins the catalogue."""
    key = "dialog-" + re.sub(r"[^\w]+", "-", str(entry.get("message") or entry.get("type") or "")[:40]).strip("-").lower()
    remember(key or "dialog", "native " + str(entry.get("type") or "dialog"), title=str(entry.get("type") or ""),
             text=entry.get("message", ""), buttons=["OK"] if entry.get("accepted") else ["Cancel"],
             action=("accepted" if entry.get("accepted") else "cancelled") + f" - {entry.get('why', '')}")


# --------------------------------------------------------------------------
# Dealing with what is on screen
# --------------------------------------------------------------------------
def deal_with(ws, context="", log=print, expected=(), shot_code=None):
    """Survey, classify and act on every floating window on screen; keep each in the catalogue.
    Returns {"closed": [...], "left": [{key, title, text, why}]}. A 'left' popup is a decision a
    person must make - the caller stops (CLAUDE.md 3.9). `expected` keys are the run's own (the
    Excel dialog, a popup list) and are not touched."""
    import time
    from cdp_common import click_element_by_rect
    closed, left = [], []
    for rnd in range(4):                                     # a closed message can reveal the next one
        found = [p for p in survey(ws) if key_of(p) not in expected]
        if not found:
            break
        progressed = False
        for p in found:
            key = key_of(p)
            action, why = classify(p, rule_for(key))
            labels = [b.get("text") for b in p.get("buttons") or []]
            if action == "stop":
                if not any(x["key"] == key for x in left):
                    left.append({"key": key, "title": p.get("title"), "text": _redact(p.get("text")),
                                 "buttons": labels, "why": why})
                    remember(key, "window", p.get("title"), p.get("text"), labels, f"left on screen - {why}", context)
                    if shot_code:
                        try:
                            import gmes_dossier
                            gmes_dossier.shot(shot_code, "popup")
                        except Exception:                    # noqa: BLE001
                            pass
                continue
            target = None
            if action.startswith("press:"):
                want = action[6:].strip().lower()
                target = next((b for b in p.get("buttons") or [] if str(b.get("text", "")).strip().lower() == want), None)
            else:
                target = next((b for b in p.get("buttons") or [] if str(b.get("text", "")).strip().lower()
                               in ("ok", "확인", "close", "닫기", "confirm")), None)
            try:
                if target:
                    click_element_by_rect(ws, target["x"], target["y"])
                elif p.get("close"):
                    click_element_by_rect(ws, p["close"]["x"], p["close"]["y"])
                time.sleep(0.6)
                if any(key_of(q) == key for q in survey(ws)):
                    import gmes_common
                    gmes_common.fallback_close_popup(ws, p.get("bar_id"))
                    time.sleep(0.4)
            except Exception:                                # noqa: BLE001
                pass
            gone = not any(key_of(q) == key for q in survey(ws))
            how = f"pressed {target['text']!r}" if target else "closed with its X"
            remember(key, "window", p.get("title"), p.get("text"), labels,
                     (how if gone else f"{how} - but it stayed") + f" ({why})", context)
            if gone:
                closed.append(key)
                progressed = True
                if log:
                    log(f"  popup    : {key} '{(p.get('title') or '')[:40]}' {how} - {why}"
                        + (f" - it said: {_redact(p.get('text'))[:120]}" if p.get("text") else ""))
            elif not any(x["key"] == key for x in left):
                left.append({"key": key, "title": p.get("title"), "text": _redact(p.get("text")),
                             "buttons": labels, "why": "it would not close"})
        if not progressed:
            break
    return {"closed": closed, "left": left}


def words(left):
    """One sentence for the popups a person must deal with."""
    return "; ".join(f"popup {x['key']} '{x.get('title') or ''}' says {x.get('text') or '(no text)'!r} "
                     f"[{', '.join(x.get('buttons') or [])}] - {x.get('why')}" for x in left)

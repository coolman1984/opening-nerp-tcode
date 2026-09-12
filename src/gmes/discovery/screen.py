"""A live handle on one open, active G-MES work screen."""
import json
import re
import time

from ..browser.cdp import evaluate
from ..browser.interaction import click_element_by_rect
from ..export import csv_export, excel
from ..nexacro.js_snippets import JS_IS_VISIBLE
from ..query.dataset_writer import set_filter as write_dataset_filter
from ..screens.filters import (
    _DATE_WORDS,
    date_targets,
    fit_date_to_field,
    is_date_field,
    match_filter,
    words,
)
from ..screens.grids import choose_grid, digits_only
from ..screens.input_events import type_text
from ..screens.organization import org_selection, tick_org
from ..screens.verification import poll_inquiry, read_rows, verify_rows
from . import catalogue as _catalogue
from .screen_discovery import discover, left_options, org_trees

# Shell frame ids safe to hardcode - there is only ever one of each.
TAB_PREFIX = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.divTab.form.TAB_"

# A full screen code or menu id, e.g. P1112UM00 or PPM0219 - never a partial
# one like "P111", which would match several open screens at once, and never
# a bare menu NAME, which has to go through the catalogue to be validated.
_SCREEN_CODE_RE = re.compile(r"[A-Za-z]{1,4}\d{4,}[A-Za-z0-9]*")


def looks_like_a_screen_code(text):
    return bool(_SCREEN_CODE_RE.fullmatch(text or ""))


# Closing a tab. The close control is looked for INSIDE the tab element and
# matched by class or id, never guessed at by position - and if there is no
# such control this reports that instead of clicking something unknown
# (CLAUDE.md 3.9).
JS_TAB_CLOSE_TARGET = r"""
(function() {
    const isVisible = %s;
    const tab = document.getElementById(%s);
    if (!tab) return JSON.stringify({found: false, reason: 'no tab with that id'});
    const cands = [];
    for (const el of tab.querySelectorAll('div, span, button')) {
        const cls = (typeof el.className === 'string') ? el.className : '';
        const id = el.id || '';
        if (!/close/i.test(cls) && !/close/i.test(id)) continue;
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        cands.push({id: id, cls: cls.slice(0, 50), area: r.width * r.height,
                    x: r.left + r.width / 2, y: r.top + r.height / 2});
    }
    if (!cands.length)
        return JSON.stringify({found: false, reason: 'the tab has no close control'});
    cands.sort((a, b) => a.area - b.area);
    return JSON.stringify({found: true, target: cands[0]});
})()
"""


class Screen:
    """A live handle on one open, active G-MES work screen."""

    def __init__(self, ws, code, opened, info):
        self.ws = ws
        self.code = code.strip().upper()
        self.menu_id = opened.get("menuId", "")
        self.win_id = opened.get("winId", "")
        self.title = opened.get("title", "") or self.code
        self.info = info
        self.warnings = []
        self.last_tree = None       # which category tree the division came from

    # -- introspection ------------------------------------------------------

    def refresh(self):
        """Re-read the screen. Required after anything that rebuilds the left
        panel - a category tab or a Quick View entry replaces the controls,
        so a handle taken before the click points at elements that no longer
        exist."""
        self.info = discover(self.ws, self.code)
        return self.info

    @property
    def filters(self):
        return self.info.filters

    @property
    def unbound(self):
        return self.info.unbound

    def options(self):
        return left_options(self.ws)

    def trees(self):
        return org_trees(self.ws)

    def grid(self, prefer=None):
        grid, rivals = choose_grid(self.info, prefer)
        if grid is None:
            if rivals:
                names = ", ".join(f"{g.name} -> {g.dataset}" for g in rivals[:6])
                raise RuntimeError(f"which grid? this screen has: {names}. "
                                   "Name one with --grid.")
            raise RuntimeError("no result grid was found on this screen")
        if rivals:
            names = ", ".join(f"{g.name}({g.dataset})" for g in rivals[:4])
            self.warnings.append(
                f"{grid.name} chosen as the result grid, but {names} "
                f"{'is' if len(rivals) == 1 else 'are'} comparable in size - "
                f"pass --grid to be certain")
        return grid

    @staticmethod
    def form_code(entry):
        """The screen code a dataset lives on. `_findForms` matches on the
        file name, so the .xfdl.js suffix has to come off."""
        return (entry.form or "").replace(".xfdl.js", "")

    # -- setting ------------------------------------------------------------

    def set_option(self, label, verify_wait=6):
        """Click a left-panel option by its visible label, unless it is
        already selected, and confirm the class actually changed."""
        found = left_options(self.ws)
        matches = [o for o in found if o.label.lower() == label.lower()]
        if not matches:
            matches = [o for o in found if label.lower() in o.label.lower()]
        if not matches:
            names = ", ".join(o.label for o in found[:14])
            raise RuntimeError(f"no left-panel option called {label!r}. Available: {names}")
        opt = matches[0]

        if opt.state == "selected":
            return f"{opt.label} (already selected)"

        click_element_by_rect(self.ws, opt.x, opt.y)

        deadline = time.time() + verify_wait
        outcome = f"{opt.label} (clicked; could not confirm)"
        while time.time() < deadline:
            time.sleep(0.5)
            now = left_options(self.ws)
            cur = next((o for o in now if o.label.lower() == opt.label.lower()), None)
            if cur and cur.state in ("selected", "checked"):
                outcome = f"{opt.label} -> {cur.state}"
                break
            if cur and cur.state == "unknown":
                outcome = f"{opt.label} (clicked; state not reported)"
                break
        # The panel may have been rebuilt by that click, which invalidates
        # every control path discovered before it.
        self.refresh()
        return outcome

    def select_org(self, names, tree=None, prefer=None, exclusive=True):
        """Tick one or more entries in a category tree.

        Without this the query returns nothing at all and the screen says
        "Select Search Criteria" - the single most likely cause of a silent
        empty export.

        The tree is found by shape rather than by its name, so the Prod / Fac
        / Proc tabs work as well as Org. `exclusive` clears ticks this run did
        not ask for: a tick survives between runs exactly as a typed filter
        does, and one left behind widens the query without saying so."""
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n and n.strip()]
        if not names:
            return None

        found = self.trees()
        settable = [t for t in found if t.settable]
        if not settable:
            raise RuntimeError("this screen has no category tree to tick")

        wanted_low = {n.strip().lower() for n in names}
        if tree:
            low = tree.lower()
            pool = [t for t in settable
                    if low in t.dataset.lower() or low in t.form.lower()]
            if not pool:
                have = ", ".join(f"{t.form}.{t.dataset}" for t in settable[:6])
                raise RuntimeError(f"no category tree matching {tree!r}. Present: {have}")
        else:
            # Choose by DATA: the tree that actually contains what was asked
            # for. Picking the first tree, or the biggest, is a guess that
            # fails silently on a screen with four of them.
            pool = [t for t in settable
                    if wanted_low <= {n.strip().lower() for n in t.names}]
            if not pool:
                have = sorted({n for t in settable for n in t.names})[:20]
                raise RuntimeError(
                    f"{', '.join(names)} is not in any category tree on this "
                    f"screen. Present: {have}")
            if len(pool) > 1:
                # A name can live in more than one tree - "VD" is in the Org
                # tree and the Prod one. `prefer` is the tree a previous run
                # actually proved, so a remembered screen stops re-deciding
                # this. It is only a preference: if the tree that worked
                # before does not hold what is being asked for now, the
                # data-driven choice still applies.
                chosen = [t for t in pool if prefer
                          and prefer.lower() in (t.dataset.lower(), t.form.lower())]
                if chosen:
                    pool = chosen
                else:
                    self.warnings.append(
                        f"{len(pool)} category trees contain {names[0]!r}; using "
                        f"{pool[0].form}.{pool[0].dataset}")

        target = pool[0]
        # Remembered so a successful run can record WHICH tree the division
        # came from - a screen with four trees can have the same name in more
        # than one, and next time we want the one that worked.
        self.last_tree = {"form": self.form_code(target) or target.form,
                          "dataset": target.dataset, "entry": names[0]}
        result = tick_org(self.ws, self.last_tree["form"],
                          target.dataset, names, exclusive=exclusive)
        if not result.get("found"):
            raise RuntimeError(
                f"could not tick {', '.join(names)}: "
                f"{result.get('reason') or 'missing ' + str(result.get('missing'))}. "
                f"Present: {result.get('available', '(tree not loaded)')}")

        # Now ask the SCREEN what it thinks is selected. Writing the dataset
        # is not proof: a run announced "VD" while the screen still had MOBILE
        # ticked by hand, queried MOBILE, and delivered 288 rows of MOBILE
        # data in a file labelled VD. Nothing in the log looked wrong.
        deadline = time.time() + 10
        shown = {}
        while time.time() < deadline:
            shown = org_selection(self.ws)
            if not shown.get("found"):
                break                          # no such label on this screen
            got = (shown.get("org") or "").strip().lower()
            if any(got == n.strip().lower() for n in names):
                result["confirmed"] = shown.get("org")
                return result
            time.sleep(0.5)

        if shown.get("found"):
            raise RuntimeError(
                f"the division did not take: asked for {', '.join(names)}, but "
                f"the screen still shows {shown.get('text')!r}. Refusing to "
                f"query the wrong organisation.")
        self.warnings.append(
            f"{', '.join(names)} was ticked in {result.get('instances', 1)} "
            f"tree copy/copies, but this screen has no organisation label to "
            f"confirm it against")
        return result

    def set_filter(self, key, value):
        """Set one filter by label, column or control name.

        Bound controls are written through their dataset - Nexacro binds the
        two, so the visible field follows and there is no date picker or combo
        widget to fight. Unbound controls are typed into instead; a screen
        that sets its filters in code (Q2241UM00 binds none) used to be
        undriveable for that reason."""
        flt = match_filter(self.info, key)
        if flt is None:
            hint = ""
            if any(w in key.lower() for w in ("division", "org", "category",
                                              "attribute", "plant", "std")):
                hint = (" That looks like an organisation choice: use the "
                        "Division prompt / --division, or --option for the "
                        "Org / Prod / Fac / Proc and STD / PLANT controls.")
            raise RuntimeError(f"no filter matches {key!r} on this screen "
                               f"(run 'describe {self.code}' to see them)." + hint)
        if isinstance(flt, list):
            names = ", ".join(f.label or f.column or f.control for f in flt[:6])
            raise RuntimeError(f"{key!r} is ambiguous - matches: {names}")
        return flt, self.apply(flt, value)

    def apply(self, flt, value):
        """Write one discovered control, whichever mechanism it needs.

        The read-back is checked, but a difference is only fatal when the
        field came back EMPTY - that is the failure mode that matters, a write
        that did not land. A field that came back changed is usually Nexacro
        normalising its own value (a mask reformatting a date, a combo storing
        a code for a label), so that is reported rather than treated as a
        failure and used to abort a good run."""
        if flt.bound:
            result = write_dataset_filter(self.ws, self.form_code(flt),
                                          flt.dataset, {flt.column: value})
            if not result.get("found"):
                raise RuntimeError(f"could not write {flt.dataset}.{flt.column}")
            applied = result["applied"].get(flt.column)
            wanted, got = str(value or "").strip(), str(applied or "").strip()
            if wanted and not got:
                raise RuntimeError(f"{flt.column} did not take: asked for "
                                   f"{value!r}, the field is empty")
            if got != wanted:
                self.warnings.append(
                    f"{flt.column} still reads {applied!r} after being cleared"
                    if not wanted else
                    f"{flt.column} was set to {value!r} and reads back as "
                    f"{applied!r} - G-MES reformatted it")
            return applied
        if not flt.id:
            raise RuntimeError(f"{flt.control} has no dataset behind it and "
                               "no reachable element - it cannot be set")
        return type_text(self.ws, flt.id, value)

    def find_ref(self, ref):
        """Locate the control a saved profile refers to, on the screen as it
        is right now. `ref` is a persisted profile reference (a plain dict -
        profiles/ has not been ported yet, see discovery/fingerprint.py's
        docstring). Matched by dataset+column, or by control name for the
        unbound ones - never by anything positional. Returns None if it has
        gone, which is the caller's signal to stop trusting the profile."""
        if not ref:
            return None
        for f in self.filters + self.unbound:
            if ref.get("column") and f.column == ref["column"] \
                    and f.dataset == ref["dataset"]:
                return f
            if not ref.get("column") and f.control == ref.get("control"):
                return f
        return None

    def set_date_range(self, from_value, to_value, profile=None):
        """Put the caller's own two dates into this screen's period fields.

        No date is ever calculated here. The two values arrive already
        decided; this only finds where they go and confirms they landed.

        A profile, when one has been proven, says which fields those are. On
        an unlearned screen they are worked out from the screen itself, and
        anything genuinely ambiguous stops the run rather than picking."""
        frm = self.find_ref(profile.get("from")) if profile else None
        to = self.find_ref(profile.get("to")) if profile else None

        if frm is None and to is None:
            frm, to, singles = date_targets(self.info)
            if frm is None and to is None:
                if not singles:
                    return []                       # the screen has no date at all
                if from_value != to_value:
                    names = ", ".join(s.column or s.control for s in singles)
                    raise RuntimeError(
                        f"this screen has no from/to pair - only {names}. "
                        "Give --from and --to the same value, or name the field "
                        "with --set.")
                frm = singles[0]

        written = []
        for flt, value, which in ((frm, from_value, "--from"), (to, to_value, "--to")):
            if value is None:
                continue
            if flt is None:
                # Refusing here rather than setting one end of the range and
                # querying a period nobody asked for.
                have = ", ".join(f.column for f in self.filters
                                 if is_date_field(f)) or "none"
                raise RuntimeError(f"this screen has no field for {which} "
                                   f"(date fields found: {have})")
            fitted = fit_date_to_field(value, flt.value)
            self.apply(flt, fitted)
            written.append((flt, fitted))
        return written

    def set_date(self, yyyymmdd):
        """Apply a date to whatever period fields the screen has.

        Returns a list of (column, written) so the caller can print exactly
        what happened - including nothing, on a screen with no date at all."""
        frm, to, singles = date_targets(self.info)
        pair = [f for f in (frm, to) if f]
        if pair:
            targets = pair
        elif singles:
            # One date field is unambiguous. Several, with no from/to naming
            # among them, are not - setting them all would be a guess about
            # what each one means, so only the first is set and the rest are
            # named so the caller can set them explicitly.
            targets = singles[:1]
            if len(singles) > 1:
                others = ", ".join(f.column or f.control for f in singles[1:])
                self.warnings.append(
                    f"this screen has more than one date field; only "
                    f"{targets[0].column or targets[0].control} was set. "
                    f"Others left alone: {others}")
        else:
            targets = []

        written = []
        for flt in targets:
            value = fit_date_to_field(yyyymmdd, flt.value)
            self.apply(flt, value)
            written.append((flt.column or flt.control, value))
        return written

    def clear_stale(self, keep=()):
        """Blank the free-text filters left behind by an earlier run.

        G-MES keeps a screen alive behind its tab, and a value typed into a
        filter STAYS there. A run asking only for a date returned zero rows
        because a Production Order from the previous run was still in the box:
        the date was right, the division was right, and the answer was empty
        with nothing to indicate why.

        Only `edt` text boxes are cleared, and only ones this run did not set.
        Combos and checkboxes hold meaningful defaults (`paramTecoYn` = "All",
        a status list = "1^2^3^4") and emptying those breaks the query a
        different way. Unbound boxes are only REPORTED: they are filled by the
        screen's own code, so a blank one may be a state the screen never
        expects to see."""
        cleared, noted = [], []
        for f in self.filters:
            if not (f.control or "").lower().startswith("edt"):
                continue
            if f.column in keep or not (f.value or "").strip():
                continue
            try:
                self.apply(f, "")
                cleared.append(f"{f.label or f.column}={f.value}")
            except RuntimeError:
                pass
        for u in self.unbound:
            if not (u.control or "").lower().startswith("edt"):
                continue
            if (u.value or "").strip():
                noted.append(f"{u.label or u.control}={u.value}")
        if noted:
            self.warnings.append("left as-is (the screen fills these in code): "
                                 + ", ".join(noted))
        return cleared

    # -- running ------------------------------------------------------------

    def inquiry(self, grid, **kwargs):
        """Click Inquiry and wait for THIS screen's result set to settle."""
        return poll_inquiry(self.ws, self.form_code(grid), grid.dataset, **kwargs)

    def rows(self, grid, limit=-1):
        return read_rows(self.ws, self.form_code(grid), grid.dataset, limit=limit)

    def verify_column(self, grid, column, expected, sample=8, strict=True):
        """Confirm the returned rows really carry the value that was asked for."""
        seen, problem = verify_rows(self.ws, self.form_code(grid), grid.dataset,
                                    column, expected, sample=sample)
        if problem:
            if strict:
                raise RuntimeError(problem + ". Refusing to export the wrong data.")
            self.warnings.append(problem)
        return seen

    def date_like_columns(self, grid, sample=3):
        """Result columns that really are dates - what `--verify` can be given.

        The first version asked only whether every sampled value was six or
        eight digits. On the Production Plan result that reported `prodTime`
        (000025 - a time), `planWeekno` (202636 - a week) and `modelDesc`
        (65856560 - a model) as "dates that came back", under a heading
        promising dates.

        It is the same mistake as offering every dataset with a `commonName`
        column as an organisation tree: **shape is not identity**. The column
        has to be NAMED like a date as well as look like one."""
        result = self.rows(grid, limit=sample)
        if not result.get("found") or not result["rows"]:
            return []
        out = []
        for c in result["columns"]:
            if c.startswith("_") or not words(c) & _DATE_WORDS:
                continue
            values = [digits_only(r.get(c)) for r in result["rows"]]
            values = [v for v in values if v]
            if values and all(len(v) in (6, 8) for v in values):
                out.append(c)
        return out

    # -- output -------------------------------------------------------------

    def export_excel(self, target_dir, timeout=240):
        """Delegate the browser-driven workbook download to ``export``."""
        return excel.download_excel(self.ws, target_dir, timeout=timeout)

    def to_csv(self, grid, path):
        """Stream this discovered grid's dataset to CSV through ``export``."""
        return csv_export.write_csv(self.ws, self.form_code(grid), grid.dataset, path)

    # -- lifecycle ----------------------------------------------------------

    def activate(self, max_wait=20):
        return _catalogue.activate_screen(self.ws, self.win_id, max_wait=max_wait)

    def close(self, timeout=20):
        """Close this screen's tab, and confirm it actually went.

        Screens accumulate: every one stays alive behind its tab holding its
        filters, its result set and its memory, and a long batch ends with a
        dozen of them. Returns (True, detail) or (False, reason) - it never
        clicks something it cannot identify as a close control."""
        target = evaluate(self.ws, JS_TAB_CLOSE_TARGET % (
            JS_IS_VISIBLE, json.dumps(TAB_PREFIX + self.win_id)))
        if not target.get("found"):
            return False, target.get("reason", "no close control")
        click_element_by_rect(self.ws, target["target"]["x"], target["target"]["y"])

        deadline = time.time() + timeout
        while time.time() < deadline:
            open_now = {r.get("winId") for r in
                        _catalogue.open_screens(self.ws).get("rows", [])}
            if self.win_id not in open_now:
                return True, f"closed {self.win_id}"
            time.sleep(0.5)
        return False, f"{self.win_id} was still open {timeout}s after clicking its X"


# ===========================================================================
# Opening
# ===========================================================================

def open_screen(ws, code, ready_wait=90, log=print):
    """Open a screen by code or name, bring it to the FRONT, and wait until
    it has actually built itself.

    Both halves matter. A background screen still accepts dataset writes, so
    filters apply cleanly and the Inquiry click then lands on whichever screen
    is really in front - that produced a run which set the date and division
    correctly, queried a completely different report, and reported zero rows.

    And a tab existing is not the same as a screen being built: Nexacro
    constructs the whole UI in JavaScript long after the tab appears, so this
    polls for the screen's own forms rather than reading them once and
    declaring the screen unreadable."""
    code = code.strip()

    # A screen already open is reached by clicking its tab. Driving the search
    # box again would work, but it types a code one character at a time and
    # waits on a suggestion list to reach a screen that is already there - and
    # a batch re-runs the same screen constantly.
    # Only a full screen code or menu id takes this path. A partial one
    # ("P111") would match several open screens and silently pick whichever
    # came first; a name goes through the catalogue, which validates it.
    opened = None
    if looks_like_a_screen_code(code):
        for row in _catalogue.open_screens(ws).get("rows", []):
            haystack = f"{row.get('pageUrl', '')} {row.get('menuId', '')}".upper()
            if code.upper() in haystack:
                opened = row
                break
    if opened is None:
        opened = _catalogue.open_screen(ws, code, log=log)

    if not _catalogue.activate_screen(ws, opened.get("winId", "")):
        raise RuntimeError(f"{code} is open as {opened.get('winId')} but its tab "
                           "could not be brought to the front")

    deadline = time.time() + ready_wait
    info, last = None, "the screen never reported any forms"
    while time.time() < deadline:
        try:
            info = discover(ws, code)
        except RuntimeError as e:
            last = str(e)
            time.sleep(1.0)
            continue
        if info.grids or info.filters:
            return Screen(ws, code, opened, info)
        time.sleep(1.0)
    raise RuntimeError(f"{code} opened but never finished building ({last})")

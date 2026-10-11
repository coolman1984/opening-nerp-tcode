"""
The G-MES tool for AI agents: an MCP server, and the same tools from a plain shell.

    python gmes_mcp.py                      # the MCP server (stdio) - what an agent's config starts
    python gmes_mcp.py tools                # every tool, its arguments and rules, as JSON
    python gmes_mcp.py call status          # one tool from a shell (no MCP); the answer is JSON
    python gmes_mcp.py call run_report --args-file run.json
    python gmes_mcp.py config               # how to connect Claude Code, Codex, Claude Desktop, ...
    GMES_Workflow.bat mcp ...               # the same, from the launcher

An agent connected here does not read the code: every tool says what it does, what it
changes and what to do with its answer, and the server gives the agent the standing rules
(INSTRUCTIONS) when it connects. HISTORY.md Phase 129.

**Not a second engine** (CLAUDE.md section 0). Each tool runs the command line a person
runs - `gmes_report.py`, `gmes_batch.py`, `gmes_twin.py`, `gmes_preflight.py` - as a child
process, its arguments built from a table and checked here first. The run lock,
`--verify`, the sign-in rules, the twin sync and every refusal are the command line's own.
The one result this file reads itself is the command line's `--manifest` JSON, and it
checks the files that manifest names on disk.

**The protocol.** JSON-RPC 2.0, one message per line on stdin/stdout, standard library
only (the official Python SDK needs about 16 packages - pydantic, starlette, uvicorn,
pyjwt[crypto], pywin32 ... - and this project is stdlib + websocket-client by rule, for a
locked-down corporate PC and the server package). Dual-era, as the 2026-07-28 revision
describes: a client that opens with `initialize` (2024-11-05 .. 2025-11-25) gets that
revision; a request carrying `_meta["io.modelcontextprotocol/protocolVersion"]` is served
statelessly as 2026-07-28 (`server/discover`, `resultType`, `-32022`).

Safety, enforced here in code - not by the descriptions:
- stdout belongs to the protocol; diagnostics go to stderr.
- No tool runs a command it was not built for: no shell, no free command line, options
  always written `--name=value`, codes and names matched against patterns.
- No tool reads, sets or prints credentials; every answer is passed through the project's
  secret redaction (gmes_redact) before it leaves.
- `run_report` refuses, unless `confirm: true`, anything that would change what a recorded
  screen's later replays and batches do: a different scope on a recorded screen, a pinned
  export/folder/team folder, relearn (CLAUDE.md 2.5 - the agent is told to ask the person).
- One tool call at a time; a second is refused at once, never queued behind a report.
- A call that runs past its time limit, is cancelled, or whose client goes away is stopped:
  its process is ended and waited for, the run lock it held is reclaimed, and the browser
  is closed through its own endpoint if this server started it (CLAUDE.md 2.6). A browser
  that was already running before is never closed.
- Success is proven, not assumed: exit 0 AND, for a run, the manifest's own result per
  screen AND every file it names present on disk with a size.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_NAME = "gmes"
SERVER_VERSION = "1.0.0"
MODERN_VERSIONS = ("2026-07-28",)
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")   # newest first
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
LOG_DIR = os.path.join(HERE, "logs", "mcp")
HEAD_LINES, TAIL_LINES = 60, 300          # a longer answer keeps both ends and names a file
PROGRESS_EVERY = 1.0                      # seconds between progress notifications
STOP_GRACE = 30                           # seconds a stopped process gets to exit
BUSY_WAIT = 120                           # seconds a call waits for the one before it
MINUTES = {"offline": 10, "live": 90}     # default time limit per call; timeout_minutes overrides

INSTRUCTIONS = """\
G-MES automation (Samsung's Nexacro MES) for an AI agent. Every G-MES action here is
READ-ONLY: open a screen, set filters, Inquiry, download G-MES's own Excel. The tools run the
project's own command line; you never need to read its code.

The prime directive: never deliver wrong data in a correctly named file. A run must PROVE the
screen, the division, the day and the grid; tell the person plainly what could not be proven
(every warning in the result).

How to work:
1. Start offline: `status` (recorded screens, last record check), `batch_list`, `batch_plan`
   (what a batch WOULD run - no browser). Offline tools cost nothing.
2. Live tools (`find_screen`, `describe_screen`, `run_report`) sign in to G-MES. ONE live call
   at a time; the browser stays open between calls - call `close_browser` when you are done.
3. Replaying a recorded screen: `run_report` with only `codes`. To run it for another day, or
   anything else, read `describe_screen` first.
4. A date needs `verify`: a result column carrying that date, found in `describe_screen`.
   Never guess one. A bare UI number means the standing recipe: division VD, yesterday (you
   compute YYYYMMDD), Excel. If VD is not in the screen's trees or no date exists to verify,
   STOP and ask the person - never substitute.
5. `run_report` asks for confirm=true when the call would change what a RECORDED screen's later
   replays and scheduled batches do (another scope, a pinned folder/export, relearn). Ask the
   person first. `dry_run` never changes anything.
6. SIGN-IN FAILED: stop all live tools, tell the person, wait at least 30 minutes. Many sign-ins
   in an hour stop the corporate SSO from opening. Never work around it.
7. "Another run has the browser": someone else's run (a schedule, the GMES Automation window,
   a person). Do not close it; tell the person and try later.
8. Do not print rows that describe people, never paste raw dataset contents; the Excel is
   DRM-protected and is checked by existence and size only.
9. Report: screen, scope, rows, files, what was proven, what was NOT, what the person decides.

Resources: `gmes://docs/agent-playbook` (the full procedure and every refusal explained),
`gmes://docs/gotchas` (G-MES's numbered traps), `gmes://docs/weekly-reports` (the MR.Park weekly
HQ reports: the manager's rules, the proofs, the weekly_hq batch)."""

DOCS = (("agent-playbook", "AGENT_PLAYBOOK.md", "How to record, replay and batch any UI number"),
        ("gotchas", "GMES_SKILL.md", "G-MES's numbered gotchas, each earned live"),
        ("readme", "README.md", "What the tool does and every command"),
        ("weekly-reports", "WEEKLY_REPORTS.md", "The MR.Park weekly HQ reports: rules old -> new, proofs, pipeline"))


def diag(message):
    """A line for whoever reads the server's stderr (the client's MCP log)."""
    try:
        sys.stderr.write(f"{datetime.now():%H:%M:%S} gmes-mcp: {message}\n")
        sys.stderr.flush()
    except Exception:                                     # noqa: BLE001 - never fatal
        pass


def redact(text):
    try:
        import gmes_redact
        return gmes_redact.redact_text(text)
    except Exception:                                     # noqa: BLE001
        return text


class BadInput(ValueError):
    """An argument this server will not pass on - said to the agent; nothing was run."""


# --------------------------------------------------------------------------
# Arguments: checked here, so nothing an agent sends can become a flag or a shell word
# --------------------------------------------------------------------------
CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,15}")
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
SELECTION_RE = re.compile(r"[A-Za-z0-9,!@_\-]{1,80}")
POLICY_RE = re.compile(r"[A-Za-z0-9:\-]{1,24}")
DATE_RE = re.compile(r"\d{4}-?\d{2}(-?\d{2})?|\d{4}/\d{2}/\d{2}")


def _text(value, what, limit=300, path=False):
    if not isinstance(value, str):
        raise BadInput(f"{what} must be text")
    value = value.strip()
    if not value:
        raise BadInput(f"{what} is empty")
    if len(value) > limit or any(ch in value for ch in "\r\n\x00"):
        raise BadInput(f"{what} is too long or has a line break")
    if value.startswith("-") and not path:
        raise BadInput(f"{what} cannot start with '-'")
    return value


def _code(value):
    value = _text(value, "a screen code", 20)
    if not CODE_RE.fullmatch(value):
        raise BadInput(f"{value!r} is not a G-MES screen code (e.g. P1112UM00)")
    return value.upper()


def _codes(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise BadInput("codes: give at least one screen code, e.g. [\"P1112UM00\"]")
    if len(value) > 20:
        raise BadInput("codes: at most 20 screens in one call")
    return [_code(v) for v in value]


def _matching(value, pattern, what, example):
    value = _text(value, what, 80, path=True)
    if not pattern.fullmatch(value):
        raise BadInput(f"{what} {value!r} is not valid (e.g. {example})")
    return value


def _list(value, what):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise BadInput(f"{what} must be a list")
    return value


def _date(value):
    return _matching(value, DATE_RE, "date", "20261009 (or 202609 for a month screen)")


def _policy(value):
    return _matching(value, POLICY_RE, "date policy", "yesterday, today, -3, keep, 20261009, 20261001:20261007")


class Argv:
    """The child's command line, built from the agent's arguments. Options are always
    written `--name=value`, so a value can never be read as another option."""

    def __init__(self, args):
        self.args = dict(args or {})
        self.out = []

    def has(self, key):
        return self.args.get(key) not in (None, "", [], {}, False)

    def get(self, key, default=None):
        return self.args.get(key, default)

    def add(self, *words):
        self.out.extend(words)

    def flag(self, key, option):
        value = self.args.get(key)
        if value is True:
            self.out.append(option)
        elif value not in (None, False):
            raise BadInput(f"{key} must be true or false")

    def opt(self, key, option, check=None, path=False):
        if self.has(key):
            value = check(self.args[key]) if check else _text(self.args[key], key, path=path)
            self.out.append(f"{option}={value}")

    def many(self, key, option, path=False):
        for item in _list(self.args.get(key), key):
            self.out.append(f"{option}={_text(item, key, path=path)}")


def _selection(a):
    words = []
    for item in _list(a.get("selection"), "selection"):
        for word in _text(item, "selection", 200, path=True).split():
            if word.startswith("-") or not SELECTION_RE.fullmatch(word):
                raise BadInput(f"selection {word!r} is not valid (all | 1,3,5-7 | P1112UM00 | !3 | @name)")
            words.append(word)
    return words


def is_recorded(code):
    try:
        import gmes_profile
        return os.path.isfile(gmes_profile.path_for(code))
    except Exception:                                     # noqa: BLE001
        return os.path.isfile(os.path.join(HERE, "screens", f"{code}.json"))


# What a successful run writes into a recorded screen's profile - so what its later bare
# replays and scheduled batches will do (gmes_core.run_screen saves the scope it used and
# pins an explicit export/folder/team folders). Dates are left out on purpose: a batch's
# date policy replaces remembered dates, and a bare replay re-runs the remembered day.
CHANGES_RECORDING = ("division", "tree", "set", "option", "grid")
PINS = ("export", "output_dir", "distribute_to", "relearn")


def _build_run(a):
    codes = _codes(a.get("codes"))
    if a.get("confirm") is not True and a.get("dry_run") is not True:
        pinned = [k for k in PINS if a.has(k)]
        recorded = [c for c in codes if is_recorded(c)]
        scoped = [k for k in CHANGES_RECORDING if a.has(k)]
        if pinned or (recorded and scoped):
            why = (f"{', '.join(pinned)} would be pinned for every later replay" if pinned else
                   f"{', '.join(recorded)} {'is' if len(recorded) == 1 else 'are'} recorded, and a "
                   f"successful run with {', '.join(scoped)} replaces what its replays and "
                   "scheduled batches use")
            raise BadInput(f"needs the person's yes: {why}. Ask them, then call again with "
                           "confirm=true - or use dry_run=true to only check the setup. Nothing was run.")
    a.add("run", *codes)
    a.opt("division", "--division")
    a.opt("tree", "--tree")
    a.opt("date", "--date", _date)
    a.opt("date_from", "--from", _date)
    a.opt("date_to", "--to", _date)
    a.opt("verify", "--verify")
    sets = a.get("set") or {}
    if not isinstance(sets, dict):
        raise BadInput("set must be an object of filter -> value, e.g. {\"fromDt\": \"202609\"}")
    for name, value in sets.items():
        name = _text(str(name), "a filter name", 80)
        value = str(value).strip()
        if len(value) > 300 or any(ch in value for ch in "\r\n\x00"):
            raise BadInput(f"the value of {name} is too long or has a line break")
        a.out.append(f"--set={name}={value}")
    a.many("option", "--option")
    a.opt("grid", "--grid")
    if a.has("export"):
        if a.get("export") not in ("xlsx", "csv", "none"):
            raise BadInput("export must be xlsx, csv or none")
        a.out.append(f"--export={a.get('export')}")
    a.opt("output_dir", "--output-dir", path=True)
    a.many("distribute_to", "--distribute-to", path=True)
    a.flag("dry_run", "--dry-run")
    a.flag("relearn", "--relearn")
    a.flag("close_tabs", "--close-tabs")
    return "gmes_report.py", a.out


def _build_describe(a):
    a.add("describe", *_codes(a.get("codes")))
    a.flag("close_tabs", "--close-tabs")
    return "gmes_report.py", a.out


def _build_find(a):
    return "gmes_report.py", ["find", _text(a.get("query"), "query", 80)]


def _build_plan(a):
    a.add("plan", *_selection(a))
    a.opt("batch", "--batch", lambda v: _matching(v, NAME_RE, "batch", "morning"))
    if not a.has("selection") and not a.has("batch"):
        raise BadInput("say what to plan: selection (e.g. [\"all\"]) or batch (a saved name)")
    a.opt("date", "--date", _policy)
    return "gmes_batch.py", a.out


# --------------------------------------------------------------------------
# The tools of this release (HISTORY.md Phase 129: discovery, status, describe, run)
# --------------------------------------------------------------------------
S = {"type": "string"}
B = {"type": "boolean"}
LIST = {"type": "array", "items": {"type": "string"}}
CODES = dict(LIST, minItems=1, maxItems=20, description="screen codes, e.g. [\"P1112UM00\"]")
TIMEOUT = {"type": "integer", "minimum": 1, "maximum": 600,
           "description": "stop the call after this many minutes (default: 10 offline, 90 live)"}

RUN_PROPS = {
    "codes": dict(CODES, description="screen codes, e.g. [\"P1112UM00\"]. With nothing else: replay as recorded"),
    "division": dict(S, description="e.g. \"VD\", \"SMD Part\" - ticked in the screen's category tree"),
    "tree": dict(S, description="name the category tree when several hold the same entry"),
    "date": dict(S, description="one day YYYYMMDD (from = to). You compute it - nothing is derived from today"),
    "date_from": dict(S, description="start of the period, YYYYMMDD (needs date_to)"),
    "date_to": dict(S, description="end of the period, YYYYMMDD"),
    "verify": dict(S, description="a result column carrying the date, e.g. \"planYmd\" - REQUIRED with a date "
                                  "(the run refuses to export unless the rows carry that day). From describe_screen; never guessed"),
    "set": {"type": "object", "additionalProperties": S,
            "description": "other filters by label, column or control name, e.g. {\"rdoSearchType\": \"Line\"}"},
    "option": dict(LIST, description="left-panel options, e.g. [\"Daily\"] or [\"PLANT\", \"Create Date\"]"),
    "grid": dict(S, description="which result grid - only on evidence, when describe shows rivals"),
    "dry_run": dict(B, description="apply everything, stop before Inquiry; exports and remembers nothing"),
    "close_tabs": dict(B, description="close each screen's window afterwards (after an exploratory run)"),
    "export": {"type": "string", "enum": ["xlsx", "csv", "none"],
               "description": "default: the screen's own (Excel). PINNED for later replays - needs confirm"},
    "output_dir": dict(S, description="where the file goes. PINNED for later replays - needs confirm"),
    "distribute_to": dict(LIST, description="extra team folders for the Excel. PINNED - needs confirm"),
    "relearn": dict(B, description="forget the saved shape and read the screen fresh - needs confirm"),
    "confirm": dict(B, description="true only after the person said yes to the change named in the refusal"),
    "timeout_minutes": TIMEOUT,
}


def _tool(name, title, description, build, props=None, required=(), kind="offline", example=None):
    props = dict(props or {})
    props.setdefault("timeout_minutes", TIMEOUT)
    return {"name": name, "title": title, "description": description, "build": build, "kind": kind,
            "example": example or {},
            "inputSchema": {"type": "object", "properties": props, "required": list(required),
                            "additionalProperties": False}}


LIVE = (" LIVE: signs in to G-MES (read-only there); the browser stays open for the next call. "
        "One live call at a time.")
LEVELS = " Like every command it first levels recordings with the GMES Automation window (nothing deleted)."

TOOLS = [
    _tool("status", "Recorded reports",
          "Every screen recorded on this PC: status, last run, last record check. Offline - start here." + LEVELS,
          lambda a: ("gmes_report.py", ["status"])),
    _tool("batch_list", "Recorded screens, numbered",
          "The recorded screens with the numbers a batch selection uses (1,3,5-7). Offline." + LEVELS,
          lambda a: ("gmes_batch.py", ["list"])),
    _tool("batch_plan", "Plan a batch (what WOULD run)",
          "For a selection or a saved batch: what would run, for which dates, what is skipped and why. "
          "No browser, nothing run." + LEVELS, _build_plan,
          {"selection": dict(LIST, description="all | 1,3,5-7 | screen codes | !3 to exclude | @savedname"),
           "batch": dict(S, description="a saved batch name"),
           "date": dict(S, description="yesterday (default) | today | -N | keep | YYYYMMDD | YYYYMMDD:YYYYMMDD")},
          example={"selection": ["all"], "date": "yesterday"}),
    _tool("batches", "Saved batches", "The saved batch lists and their date policies. Offline." + LEVELS,
          lambda a: ("gmes_batch.py", ["batches"])),
    _tool("schedules", "Schedules",
          "This tool's Windows scheduled tasks: next run, last result, health. Offline, reads only." + LEVELS,
          lambda a: ("gmes_batch.py", ["schedules"])),
    _tool("recent_batch_report", "Latest batch report",
          "The report of the most recent batch run on this PC: what was delivered, what was not and why. "
          "Offline; reads logs/batches.", None),
    _tool("twin_status", "Level with GMES Automation?",
          "Whether the command line and the GMES Automation window hold the same recordings, batches and "
          "checks. Changes nothing.", lambda a: ("gmes_twin.py", ["status"])),
    _tool("preflight", "Can this PC run the tool?",
          "Python, websocket-client, a supported browser, a writable folder, a saved sign-in. Read-only. "
          "A missing sign-in is the person's to add (python gmes_credentials.py set, as themselves).",
          lambda a: ("gmes_preflight.py", [])),
    _tool("find_screen", "Find a screen",
          "Search the G-MES catalogue by code prefix or words; one search resolves many codes - prefer a "
          "prefix (\"R322\")." + LIVE, _build_find, {"query": dict(S, description="e.g. \"R322\" or \"production plan\"")},
          ("query",), kind="live", example={"query": "P1112"}),
    _tool("describe_screen", "Describe a screen",
          "What a screen offers, writing nothing: result grids (and which one a run would use), filters "
          "('<- date' marks a date), category trees (divisions), left-panel options. Read it before any "
          "run that is not a plain replay: which grid is the report, day or month, which division, which "
          "column verifies the date, is it a live monitor." + LIVE, _build_describe,
          {"codes": CODES, "close_tabs": RUN_PROPS["close_tabs"]}, ("codes",), kind="live",
          example={"codes": ["P1112UM00"]}),
    _tool("run_report", "Run a report",
          "Open each screen, apply the scope, Inquiry, verify, download G-MES's Excel. With only codes: "
          "replay each screen exactly as recorded. A date needs verify. The result lists per screen: ok, "
          "rows, files (checked on disk) and warnings - read every warning. A successful run is remembered "
          "for that screen; anything that would change a RECORDED screen's later replays needs confirm "
          "(the tool says which)." + LIVE, _build_run, RUN_PROPS, ("codes",), kind="live",
          example={"codes": ["P1112UM00"], "division": "VD", "date": "20261009", "verify": "planYmd"}),
    _tool("close_browser", "Close the automation browser",
          "Close the automation browser through its own endpoint (never the person's own browser). Refused "
          "while another run holds it. Call it when your series of live calls is done.", None, kind="local"),
]
BY_NAME = {t["name"]: t for t in TOOLS}

SCREEN_SCHEMA = {"type": "object", "properties": {
    "screen": S, "ok": B, "rows": {"type": ["integer", "null"]},
    "files": {"type": "array", "items": {"type": "object", "properties": {
        "path": S, "exists": B, "bytes": {"type": ["integer", "null"]}}}},
    "error": {"type": ["string", "null"]}, "warnings": LIST}}
OUTPUT_SCHEMA = {"type": "object", "required": ["ok", "summary"], "properties": {
    "ok": dict(B, description="true only when the command succeeded AND its result was checked"),
    "summary": dict(S, description="one line: what happened, or what to do next"),
    "exit_code": {"type": ["integer", "null"]}, "command": S,
    "problems": dict(LIST, description="why ok is false, or what was not proven"),
    "output": dict(S, description="the command's own answer, as a person would read it"),
    "screens": dict({"type": "array", "items": SCREEN_SCHEMA},
                    description="run_report only: each screen's result, files checked on disk"),
    "full_output_file": {"type": ["string", "null"]}}}


def annotations(tool):
    return {"title": tool["title"], "readOnlyHint": tool["kind"] == "offline",
            "destructiveHint": False, "idempotentHint": tool["kind"] != "live",
            "openWorldHint": tool["kind"] == "live"}


def tool_list():
    out = []
    for t in TOOLS:
        example = (f" Example arguments: {json.dumps(t['example'])}." if t["example"] else "")
        out.append({"name": t["name"], "title": t["title"], "description": t["description"] + example,
                    "inputSchema": t["inputSchema"], "outputSchema": OUTPUT_SCHEMA,
                    "annotations": annotations(t)})
    return out


# --------------------------------------------------------------------------
# Running one tool: the command line, as a child process this server controls
# --------------------------------------------------------------------------
SIGN_IN_FAILED = re.compile(r"Sign-in failed|SSO window never opened|outcome is unclear|cannot decrypt|"
                            r"no saved (G-MES )?(sign-in|credentials)", re.I)
LOCKED = re.compile(r"another (G-MES )?run|using the automation browser|holds the browser", re.I)
EXIT_WORDS = {"gmes_batch.py": {2: "the arguments were refused", 3: "another run has the browser",
                                4: "sign-in failed"},
              "gmes_report.py": {2: "the arguments were refused"}}


def next_step(text, code):
    """The two answers an agent must never retry through."""
    if code and SIGN_IN_FAILED.search(text):
        return ("STOP: sign-in did not complete. Call no further live tool; tell the person and wait at "
                "least 30 minutes (the corporate SSO stops opening after many sign-ins).")
    if code and LOCKED.search(text):
        return ("Another run holds the automation browser (a schedule, the GMES Automation window or a "
                "person). Do not close it - tell the person and try later.")
    return ""


def shape_output(text, tool_name, now=None):
    """Too long for an agent -> both ends here, the whole of it in a file the answer names.
    Never a silent cut (CLAUDE.md 4.6)."""
    lines = text.splitlines()
    if len(lines) <= HEAD_LINES + TAIL_LINES:
        return text, None
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{(now or datetime.now()):%Y%m%d_%H%M%S}_{tool_name}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    left_out = len(lines) - HEAD_LINES - TAIL_LINES
    return ("\n".join(lines[:HEAD_LINES])
            + f"\n\n[... {left_out} of {len(lines)} lines left out here; the full output is in {path} ...]\n\n"
            + "\n".join(lines[-TAIL_LINES:])), path


def child_env():
    env = dict(os.environ)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1", GMES_MCP="1")
    return env


def browser_is_up():
    try:
        import cdp_common
        return cdp_common.cdp_is_up(cdp_common.active_port(), timeout=1)
    except Exception:                                     # noqa: BLE001 - only a hint
        return False


CLOSE_SNIPPET = r"""
import sys, gmes_core as core, cdp_common
try:
    token = core.acquire_run_lock()
except core.RunLocked as e:
    print(f"Not closed: {e}"); sys.exit(3)
try:
    if not cdp_common.cdp_is_up(cdp_common.active_port()):
        print("The automation browser is not running - nothing to close."); sys.exit(0)
    ok = cdp_common.close_browser()
    print("The automation browser was closed." if ok else "Asked the browser to close; it did not confirm.")
    sys.exit(0 if ok else 1)
finally:
    core.release_run_lock(token)
"""


class Busy(RuntimeError):
    pass


class Runner:
    """Runs the command line, one call at a time, and owns what it starts."""

    def __init__(self, python=None, cwd=HERE):
        self.python = python or sys.executable
        self.cwd = cwd
        self.lock = threading.Lock()
        self.current = None                 # the tool name now running
        self.started_browser = False        # True once a live call found no browser running

    def note_live_call(self):
        """Before each live call: if no automation browser is running, the one this call
        starts is ours to close later. One that was already running is never ours."""
        if not browser_is_up():
            self.started_browser = True

    def run(self, script, argv, name, minutes, on_line=None, cancelled=None, wait=None):
        """(exit code or None if stopped, output, why it stopped).

        One command at a time (they share one browser, one run lock and the twin sync). A
        call that arrives while another runs waits up to BUSY_WAIT seconds for it - clients
        such as Claude Code send independent calls in parallel - then is refused as Busy.
        A cancelled waiting call gives up at once."""
        cancelled = cancelled or threading.Event()
        deadline = time.monotonic() + (BUSY_WAIT if wait is None else wait)
        while not self.lock.acquire(timeout=0.5):
            if cancelled.is_set():
                return None, "", "the request was cancelled before it started"
            if time.monotonic() > deadline:
                raise Busy(self.current)
        self.current = name
        try:
            return self._run(script, argv, minutes, on_line, cancelled)
        finally:
            self.current = None
            self.lock.release()

    def _run(self, script, argv, minutes, on_line, cancelled):
        command = [self.python, "-u", script, *argv]
        proc = subprocess.Popen(command, cwd=self.cwd, env=child_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        diag(f"started pid {proc.pid}: {script} {' '.join(argv)[:160]}")
        stopped = {"why": ""}

        def stop(why):
            if proc.poll() is None:
                stopped["why"] = why
                diag(f"stopping pid {proc.pid}: {why}")
                proc.terminate()

        deadline = time.monotonic() + minutes * 60

        def watch():                        # polls the process; never a fixed wait (CLAUDE.md 3.1)
            while proc.poll() is None:
                if cancelled.wait(0.5):
                    stop("the request was cancelled")
                    return
                if time.monotonic() > deadline:
                    stop(f"it ran past its {minutes}-minute limit")
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        lines = []
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                lines.append(line)
                if on_line:
                    on_line(line)
        finally:
            proc.stdout.close()
            try:
                code = proc.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = proc.wait(timeout=STOP_GRACE)
            watcher.join(timeout=5)
        diag(f"pid {proc.pid} ended with {code}{' (' + stopped['why'] + ')' if stopped['why'] else ''}")
        return (None if stopped["why"] else code), "\n".join(lines), stopped["why"]

    def close_if_ours(self, reason):
        """After a stopped live call or at shutdown: the browser this server started is
        closed through its own endpoint; one that was already running is left alone."""
        if not self.started_browser or not browser_is_up():
            return ""
        with self.lock:
            code, text, _ = self._run("-c", [CLOSE_SNIPPET], 2, None, threading.Event())
        diag(f"closing the automation browser ({reason}): {text.strip()}")
        if code == 0:
            self.started_browser = False
        return text.strip() if code == 0 else ""


def latest_batch_report(root=HERE):
    folder = os.path.join(root, "logs", "batches")
    try:
        names = sorted(n for n in os.listdir(folder) if re.fullmatch(r"batch_.+\.txt", n))
    except OSError:
        names = []
    if not names:
        return None, "No batch has run on this PC yet (logs/batches is empty)."
    path = os.path.join(folder, names[-1])
    with open(path, encoding="utf-8", errors="replace") as fh:
        return path, fh.read()


def check_manifest(path, dry_run):
    """The run's own per-screen result, and each file it names checked on disk."""
    try:
        with open(path, encoding="utf-8") as fh:
            results = json.load(fh).get("results") or []
    except (OSError, ValueError) as e:
        return [], [f"the run's result file could not be read ({e}) - nothing is proven"]
    screens, problems = [], []
    for r in results:
        files = []
        for f in r.get("files") or []:
            f = str(f)
            size = os.path.getsize(f) if os.path.isfile(f) else None
            files.append({"path": f, "exists": size is not None, "bytes": size})
            if not size:
                problems.append(f"{r.get('screen')}: the file {f} is {'empty' if size == 0 else 'not there'}")
        ok = bool(r.get("ok"))
        if not ok:
            problems.append(f"{r.get('screen')}: {r.get('error') or 'failed'}")
        elif not dry_run and (r.get("rows") or 0) > 0 and not files and r.get("export") != "none":
            problems.append(f"{r.get('screen')}: reported ok with {r.get('rows')} rows but no file")
        screens.append({"screen": str(r.get("screen", "?")), "ok": ok, "rows": r.get("rows"),
                        "files": files, "error": r.get("error"),
                        "warnings": [str(w) for w in (r.get("warnings") or [])]})
    if not results:
        problems.append("the run's result file lists no screen")
    return screens, problems


def call_tool(name, arguments, runner, on_line=None, cancelled=None):
    """One tool call -> the MCP tool result (content, structuredContent, isError)."""
    tool = BY_NAME[name]
    args = arguments if arguments is not None else {}
    if not isinstance(args, dict):
        return result(False, "refused: the arguments must be an object. Nothing was run.")
    unknown = sorted(set(args) - set(tool["inputSchema"]["properties"]))
    if unknown:
        return result(False, f"refused: unknown argument(s) {', '.join(unknown)}. Nothing was run. "
                             f"Allowed: {', '.join(tool['inputSchema']['properties'])}")
    missing = [k for k in tool["inputSchema"]["required"] if k not in args]
    if missing:
        return result(False, f"refused: missing {', '.join(missing)}. Nothing was run.")
    minutes = args.get("timeout_minutes", MINUTES["live" if tool["kind"] == "live" else "offline"])
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 600:
        return result(False, "refused: timeout_minutes must be a whole number from 1 to 600.")
    if name == "recent_batch_report":
        path, text = latest_batch_report()
        return result(path is not None, f"latest batch report: {path}" if path else text,
                      text=shape_output(redact(text), name)[0] if path else None)
    manifest = None
    try:
        if name == "close_browser":
            script, argv = "-c", [CLOSE_SNIPPET]
        else:
            script, argv = tool["build"](Argv({k: v for k, v in args.items() if k != "timeout_minutes"}))
        if tool["kind"] == "live":
            argv = list(argv) + ["--keep-open"]
        if name == "run_report":
            os.makedirs(LOG_DIR, exist_ok=True)
            fd, manifest = tempfile.mkstemp(prefix="run_", suffix=".json", dir=LOG_DIR)
            os.close(fd)
            os.unlink(manifest)             # the command line writes it only when it finishes
            argv.append(f"--manifest={manifest}")
    except BadInput as e:
        return result(False, f"refused: {e}")
    if tool["kind"] == "live":
        runner.note_live_call()
    try:
        code, text, why = runner.run(script, argv, name, minutes, on_line, cancelled)
    except Busy as e:
        return result(False, f"busy: the tool call '{e}' is still running after {BUSY_WAIT}s. One call at "
                             "a time - wait for its answer, then call again. Nothing was run.")
    command = "close the automation browser" if name == "close_browser" else \
        " ".join(["python", script, *[w for w in argv if not w.startswith("--manifest=")]])
    text = redact(text)
    problems, screens = [], []
    if why:
        problems.append(f"stopped: {why}")
        if tool["kind"] == "live":
            closed = runner.close_if_ours(why)
            problems.append("the automation browser was closed so no half-done screen carries on"
                            if closed else "the automation browser was left as it was (this server did not start it)")
    elif code != 0:
        said = next((l.strip() for l in text.splitlines() if l.strip().startswith(("ERROR", "FAIL"))), "")
        if said:                            # the command line's own reason comes first
            problems.append(said)
        problems.append(EXIT_WORDS.get(script, {}).get(code) or f"the command failed (exit {code})")
    if manifest and not why:
        if os.path.isfile(manifest) or code == 0:
            screens, more = check_manifest(manifest, args.get("dry_run") is True)
            problems.extend(p for p in more if p not in problems)
        try:
            os.unlink(manifest)
        except OSError:
            pass
    ok = not problems
    hint = next_step(text, code)
    if hint:
        problems.append(hint)
    if name == "close_browser":
        last = (text.strip().splitlines() or ["(no answer)"])[-1]
        problems = [] if code == 0 else [last]
        ok = code == 0
        if ok:
            runner.started_browser = False
    shaped, full = shape_output(text, name)
    summary = ("ok" if ok else problems[0])
    if name == "close_browser" and ok:
        summary = (text.strip().splitlines() or ["closed"])[-1]
    if ok and screens:
        summary = "; ".join(f"{s['screen']} ok, {s['rows']} rows, {len(s['files'])} file(s)"
                            + (f", {len(s['warnings'])} warning(s) - read them" if s["warnings"] else "")
                            for s in screens)
    if ok and not screens and name != "close_browser":
        summary = "ok - the command's answer is in output"
    return result(ok, summary, code, command, problems, screens if name == "run_report" else None,
                  full, shaped)


def result(ok, summary, code=None, command="", problems=None, screens=None, full=None, text=None):
    """Some clients hand the model only structuredContent, others only the text - so both
    carry everything: the verdict, the problems AND the command's own answer (`output`).
    Found with Claude Code (HISTORY.md 129): without `output` an agent read an empty list
    as "nothing is recorded" while 37 screens were."""
    structured = {"ok": ok, "summary": summary, "exit_code": code, "command": command,
                  "problems": list(problems or ([] if ok else [summary])),
                  "output": text or "", "full_output_file": full}
    if screens is not None:
        structured["screens"] = list(screens)
    head = ("OK: " if ok else "NOT OK: ") + summary
    if problems and not ok:
        head += "\n" + "\n".join(f"- {p}" for p in structured["problems"][1:])
    body = f"$ {command}\nexit {code}\n\n{text}" if command and text else (text or "")
    return {"content": [{"type": "text", "text": head + ("\n\n" + body if body else "")}],
            "structuredContent": structured, "isError": not ok}


# --------------------------------------------------------------------------
# Resources and prompts: the procedure, so the agent needs nothing else
# --------------------------------------------------------------------------
def resource_list():
    return [{"uri": f"gmes://docs/{key}", "name": key, "title": title, "description": title,
             "mimeType": "text/markdown"} for key, filename, title in DOCS
            if os.path.isfile(os.path.join(HERE, filename))]


def resource_read(uri):
    for key, filename, _t in DOCS:
        if uri == f"gmes://docs/{key}":
            with open(os.path.join(HERE, filename), encoding="utf-8") as fh:
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": fh.read()}]}
    raise KeyError(uri)


PROMPTS = {
    "run_screen": {
        "description": "Run a G-MES UI number the project's way and report what was proven",
        "arguments": [{"name": "code", "description": "the UI number, e.g. P1112UM00", "required": True},
                      {"name": "request", "description": "what the person asked for (division, day ...)",
                       "required": False}],
        "text": ("Run the G-MES screen {code}. The person's request: {request}.\n"
                 "1. status - is it recorded here? A recorded screen with no other request: run_report "
                 "with only codes (its bare replay).\n"
                 "2. Otherwise describe_screen and answer from evidence: which grid is the report, day or "
                 "month, which division, which column verifies the date, is it a live monitor. Anything you "
                 "cannot answer, or VD missing: stop and ask.\n"
                 "3. run_report with the scope and verify. If it asks for confirm, ask the person.\n"
                 "4. close_browser. Report: screen, scope, rows, files, proven / not proven, needs you.")},
    "morning_check": {
        "description": "What ran overnight, what failed, and why - without a browser",
        "arguments": [],
        "text": ("Check last night's G-MES runs without starting a browser: schedules (health, last result), "
                 "recent_batch_report (delivered / not delivered and why), status (record checks). Report "
                 "plainly, failures first, with what the person should do about each.")},
}


def prompt_list():
    return [{"name": k, "description": p["description"], "arguments": p["arguments"]} for k, p in PROMPTS.items()]


def prompt_get(name, arguments):
    p = PROMPTS[name]
    values = {a["name"]: str((arguments or {}).get(a["name"]) or "(not given)") for a in p["arguments"]}
    missing = [a["name"] for a in p["arguments"] if a["required"] and not (arguments or {}).get(a["name"])]
    if missing:
        raise ValueError(f"missing argument(s): {', '.join(missing)}")
    return {"description": p["description"],
            "messages": [{"role": "user", "content": {"type": "text", "text": p["text"].format(**values)}}]}


# --------------------------------------------------------------------------
# The MCP server (JSON-RPC 2.0, one message per line)
# --------------------------------------------------------------------------
CAPABILITIES = {"tools": {"listChanged": False}, "resources": {"listChanged": False},
                "prompts": {"listChanged": False}}
SERVER_INFO = {"name": SERVER_NAME, "title": "G-MES automation", "version": SERVER_VERSION}
CACHEABLE = ("server/discover", "tools/list", "resources/list", "resources/templates/list",
             "resources/read", "prompts/list")


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class Server:
    def __init__(self, write, runner=None):
        self._write = write
        self.write_lock = threading.Lock()
        self.runner = runner or Runner()
        self.running = {}                   # request id -> cancel event
        self.threads = []
        self.legacy_version = None          # set by initialize (a legacy-era client)

    def send(self, message):
        with self.write_lock:
            self._write(message)

    def reply(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        self.send(msg)

    def handle(self, msg):
        if isinstance(msg, list):           # a JSON-RPC batch (2025-03-26 only)
            if not msg:
                self.reply(None, error={"code": -32600, "message": "empty batch"})
            for m in msg:
                self.handle(m)
            return
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            self.reply(None, error={"code": -32600, "message": "not a JSON-RPC 2.0 message"})
            return
        method, rid = msg.get("method"), msg.get("id")
        if not isinstance(method, str):
            return                          # a response: this server never sends requests
        params = msg.get("params") or {}
        if "id" not in msg:                 # a notification - never answered
            if method == "notifications/cancelled" and isinstance(params, dict):
                self.cancel(params.get("requestId"))
            return
        try:
            if not isinstance(params, dict):
                raise RpcError(-32602, "params must be an object")
            modern = self.era(method, params)
            out = self.dispatch(rid, method, params, modern)
            if out is not None:
                self.reply(rid, self.finish(out, modern, method))
        except RpcError as e:
            error = {"code": e.code, "message": e.message}
            if e.data is not None:
                error["data"] = e.data
            self.reply(rid, error=error)
        except Exception as e:                            # noqa: BLE001 - the server must answer
            diag(f"internal error in {method}: {e!r}")
            self.reply(rid, error={"code": -32603, "message": f"internal error: {e}"})

    def era(self, method, params):
        """True for a modern (2026-07-28, per-request _meta) request."""
        meta = params.get("_meta") or {}
        version = meta.get(META_VERSION) if isinstance(meta, dict) else None
        if version is None:
            return False
        if method == "initialize":
            return False
        if version not in MODERN_VERSIONS:
            raise RpcError(-32022, "Unsupported protocol version",
                           {"supported": list(MODERN_VERSIONS + LEGACY_VERSIONS), "requested": version})
        if not isinstance(meta.get(META_CAPS), dict):
            raise RpcError(-32602, f"_meta[{META_CAPS!r}] is required")
        return True

    @staticmethod
    def finish(result, modern, method=""):
        """A modern (2026-07-28) result carries resultType and the server's identity; a
        cacheable one also ttlMs/cacheScope - 0/private: what this tool knows changes as
        screens are recorded, and nothing here is shared between users."""
        if modern:
            result = dict(result, resultType="complete")
            result["_meta"] = dict(result.get("_meta") or {}, **{"io.modelcontextprotocol/serverInfo": SERVER_INFO})
            if method in CACHEABLE:
                result.setdefault("ttlMs", 0)
                result.setdefault("cacheScope", "private")
        return result

    def dispatch(self, rid, method, params, modern):
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
            self.legacy_version = version
            diag(f"initialize: client asked {asked}, serving {version}")
            return {"protocolVersion": version, "capabilities": CAPABILITIES, "serverInfo": SERVER_INFO,
                    "instructions": INSTRUCTIONS}
        if method == "server/discover":
            return {"supportedVersions": list(MODERN_VERSIONS + LEGACY_VERSIONS), "capabilities": CAPABILITIES,
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tool_list()}
        if method == "tools/call":
            name = params.get("name")
            if name not in BY_NAME:
                raise RpcError(-32602, f"Unknown tool: {name!r}")
            self.start_call(rid, name, params, modern)
            return None
        if method == "resources/list":
            return {"resources": resource_list()}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "resources/read":
            try:
                return resource_read(params.get("uri"))
            except (KeyError, OSError):
                raise RpcError(-32602 if modern else -32002, f"Resource not found: {params.get('uri')!r}")
        if method == "prompts/list":
            return {"prompts": prompt_list()}
        if method == "prompts/get":
            try:
                return prompt_get(params.get("name"), params.get("arguments"))
            except KeyError:
                raise RpcError(-32602, f"Unknown prompt: {params.get('name')!r}")
            except ValueError as e:
                raise RpcError(-32602, str(e))
        if method == "logging/setLevel":
            return {}
        raise RpcError(-32601, f"Method not found: {method}")

    def start_call(self, rid, name, params, modern):
        token = (params.get("_meta") or {}).get("progressToken")
        cancelled = threading.Event()
        self.running[rid] = cancelled
        state = {"n": 0, "last": 0.0}

        def on_line(line):
            state["n"] += 1
            now = time.monotonic()
            if token is not None and line.strip() and now - state["last"] >= PROGRESS_EVERY \
                    and not cancelled.is_set():
                state["last"] = now
                self.send({"jsonrpc": "2.0", "method": "notifications/progress",
                           "params": {"progressToken": token, "progress": state["n"],
                                      "message": redact(line.strip())[:200]}})

        def work():
            try:
                out = call_tool(name, params.get("arguments"), self.runner, on_line, cancelled)
                if not self.was_cancelled(rid):  # a cancelled request gets no answer (spec)
                    self.reply(rid, self.finish(out, modern))
            except Exception as e:                        # noqa: BLE001
                diag(f"internal error in {name}: {e!r}")
                if not self.was_cancelled(rid):
                    self.reply(rid, error={"code": -32603, "message": f"internal error: {e}"})
            finally:
                self.running.pop(rid, None)

        t = threading.Thread(target=work, daemon=True, name=f"tool-{name}")
        self.threads.append(t)
        t.start()

    cancelled_ids = None

    def was_cancelled(self, rid):
        return rid in (self.cancelled_ids or set())

    def cancel(self, rid):
        event = self.running.get(rid)
        if event is not None:
            self.cancelled_ids = (self.cancelled_ids or set()) | {rid}
            diag(f"request {rid!r} cancelled by the client")
            event.set()

    def shutdown(self):
        """stdin closed - the client is gone: stop what runs, wait for it, and close the
        browser only if this server started it."""
        for rid in list(self.running):
            self.cancel(rid)
        for t in self.threads:
            t.join(timeout=STOP_GRACE * 2 + 30)
        self.runner.close_if_ours("the client disconnected")


def serve(stdin=None, stdout=None):
    out = stdout or sys.stdout.buffer
    inp = stdin or sys.stdin.buffer
    sys.stdout = sys.stderr                 # a stray print can never corrupt the protocol

    def write(message):
        out.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        out.flush()

    server = Server(write)
    diag(f"serving {len(TOOLS)} tools from {HERE} (python {sys.version.split()[0]})")
    for raw in iter(inp.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            server.reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        server.handle(message)
    diag("stdin closed - shutting down")
    server.shutdown()
    return 0


# --------------------------------------------------------------------------
# From a shell, for an agent without MCP: the same tools, JSON in and out
# --------------------------------------------------------------------------
def config_text(python=None, here=HERE):
    python = python or sys.executable
    script = os.path.join(here, "gmes_mcp.py")
    entry = {"command": python, "args": [script]}
    esc = lambda p: p.replace("\\", "\\\\")               # noqa: E731
    return f"""Connect an AI agent to the G-MES tool (MCP over stdio). The server command is:
    "{python}" "{script}"

Claude Code - this project carries .mcp.json; start claude in this folder and approve "gmes"
once (/mcp shows it). For every folder instead:
    claude mcp add --scope user gmes -- "{python}" "{script}"

Codex CLI:
    codex mcp add gmes -- "{python}" "{script}"
  then, in %USERPROFILE%\\.codex\\config.toml under [mcp_servers.gmes], give reports time:
    tool_timeout_sec = 5400

Claude Desktop, Cursor, Gemini CLI, Windsurf ... - in their MCP JSON under "mcpServers":
    "gmes": {json.dumps(entry)}
VS Code (GitHub Copilot), .vscode\\mcp.json under "servers":
    "gmes": {json.dumps(dict(entry, type="stdio"))}

TOML form (Codex):
    [mcp_servers.gmes]
    command = "{esc(python)}"
    args = ["{esc(script)}"]
    tool_timeout_sec = 5400

An agent with only a shell (no MCP) - same tools, same checks, JSON out:
    python gmes_mcp.py tools
    python gmes_mcp.py call status
    python gmes_mcp.py call batch_plan --args-file plan.json      (plan.json: {{"selection": ["all"]}})
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].lower() == "mcp":                 # GMES_Workflow.bat mcp ...
        argv = argv[1:]
    command = argv[0].lower() if argv else "serve"
    if command == "serve":
        return serve()
    if command in ("help", "-h", "--help", "/?"):
        print(__doc__)
        return 0
    if command == "tools":
        print(json.dumps({"instructions": INSTRUCTIONS, "tools": tool_list()}, indent=2, ensure_ascii=False))
        return 0
    if command == "config":
        print(config_text())
        return 0
    if command == "call":
        if len(argv) < 2 or argv[1] not in BY_NAME:
            print(json.dumps({"ok": False, "summary": "usage: python gmes_mcp.py call TOOL [JSON | --args-file FILE]",
                              "tools": list(BY_NAME)}, indent=2))
            return 2
        name, rest = argv[1], argv[2:]
        try:
            if rest[:1] == ["--args-file"] and len(rest) == 2:
                with open(rest[1], encoding="utf-8-sig") as fh:
                    arguments = json.load(fh)
            else:
                arguments = json.loads(" ".join(rest)) if rest else {}
        except (OSError, ValueError) as e:
            print(json.dumps({"ok": False, "summary": f"the arguments are not JSON: {e}"}, indent=2))
            return 2
        res = call_tool(name, arguments, Runner())
        out = dict(res["structuredContent"], text=res["content"][0]["text"])
        if BY_NAME[name]["kind"] == "live":
            # each shell call is its own process: the browser stays open so the next call does
            # not sign in again (AGENT_PLAYBOOK.md rule 3) - the agent closes it at the end
            out["browser"] = "left open for the next call - call close_browser when the series is done"
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if res["structuredContent"]["ok"] else 1
    print(f"Unknown command '{command}'. Use: serve (default), tools, call, config, help")
    return 2


if __name__ == "__main__":
    sys.exit(main())

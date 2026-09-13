# Capability Rescue Map

**Step 4.5 of the restoration plan. Documentation only — nothing ported,
nothing deleted, no runtime code touched.**

`src/gmes` is being removed because the architecture became too large, not
because the ideas inside it were wrong. Several of those ideas were paid for
with real incidents. This map exists so none of them is lost by accident.

> ## The rule
>
> **No `src/gmes` capability may be deleted until it appears in this map with
> a classification of KEEP / REBUILD SMALL / DISCARD, a reason, and the
> regression evidence that must survive the deletion.**

## Architectural direction (binding on every entry below)

- The restored **legacy engine stays the core**. Nothing here authorises
  porting the new architecture into it.
- **No contracts layer, no facade, no application layer.** Prefer small
  independent specialist tools that wrap the legacy engine with the smallest
  possible interface.
- **RESTART and RESUME are different concepts and must stay separate.**
  - **RESTART** — after a genuine hang, restart the whole legacy workflow.
    The **watchdog** decides *when*.
    - **RESUME** — optionally skip already-completed work. The **checkpoint**
    decides *where*.
  - Neither may be allowed to imply the other.

## Honest status of the evidence

Every resilience capability listed here is **offline-proof only**. Per
`CURRENT_STATE.md` items 13–22, not one of them has ever been exercised
against a real hang, a real crash, a real chronically-broken screen, a real
corrupted profile, or a real mail server. The offline tests are good tests —
184 of them across these areas — but they prove the logic, not the premise.

Two exceptions, both discovered live in Phase 56 **during this session**, and
both currently living **only inside the frozen package**:

| Live-proven fix | Where it lives now | State of the legacy core |
|---|---|---|
| `--disable-popup-blocking` | `src/gmes/browser/chrome.py` | **ABSENT** — legacy cannot open the AD SSO popup at all |
| Screenshot targets the G-MES tab, not `pages[0]` | `src/gmes/browser/screenshots.py` | **BUG PRESENT** — `cdp_common.capture_screenshot` still calls `get_page_tab(prefer_url_substring=None)` |

These are the only two items that make the production core *worse* if
`src/gmes` is deleted without action. They are Tier 0.

---

## Summary

| # | Capability | Files | Tests | Live proof | Coupling | Class |
|---|---|---|---|---|---|---|
| 0a | Popup-blocking launch flag | `browser/chrome.py` | 1 | **YES (frozen engine)** | one flag | **KEEP — PORTED to `cdp_common.py` (E1)** |
| 0b | Screenshot targets G-MES tab | `browser/screenshots.py` | 1 | **YES (bug found live)** | one arg | **KEEP** |
| 1 | External supervisor / watchdog | `application/supervisor_uc.py` | 20 | no | very low | **KEEP** (external tool) |
| 2 | Per-process heartbeat | `application/heartbeat.py` | (in 20) | no | very low | **REBUILD SMALL** |
| 3 | Checkpoint / resume | `application/checkpoint.py` | 22 | no | low | **REBUILD SMALL** |
| 4 | Fault-vs-refusal classifier | `application/recovery.py::is_a_decision` | (in 18) | no | none | **REBUILD SMALL** |
| 5 | Recovery ladder (rungs) | `application/recovery.py`, `session_uc.py` | 18 | no | **very high** | **DISCARD** (superseded) |
| 6 | Circuit breaker | `application/circuit.py` | 16 | no | low | **REBUILD SMALL** (optional) |
| 7 | Failure alerts | `application/alerts.py` | 19 | no | low | **REBUILD SMALL** (optional) |
| 8 | Popup close verification | `nexacro/popups.py` | 12 | no | medium | **REBUILD SMALL** (technique) |
| 9 | Export retry | `export/excel.py` | 15 | no | medium | **REBUILD SMALL** (technique) |
| 10 | Record/replay drift fix | `discovery/fingerprint.py` | 13 | no | none | **REBUILD SMALL** (technique) |
| 11 | Browser/profile launch ladder | `browser/chrome.py` | (in 29) | no | medium | **DISCARD** |
| 12 | Onboarding / install identity | `auth/install.py`, `onboarding_uc.py` | (in 29) | no | low | **DISCARD** |
| 13 | Guided screen preview | `application/workflow_uc.py` | 20 | no | **very high** | **DISCARD** (legacy equivalent exists) |

---

# Tier 0 — must be ported BEFORE any deletion

## 0a. Popup-blocking launch flag — **KEEP** — **PORTED (E1, not yet live-tested on legacy)**

1. **Problem** G-MES's "AD SSO Login" opens ADFS with `window.open()`. This
   machine's Chrome GPO (`PopupsAllowedForUrls`) does not whitelist the G-MES
   or SSO hosts, so Chrome silently swallows the popup — no error, nothing for
   `Runtime.evaluate` to see, and the sign-in waits out its full 45s against a
   window that never existed (HISTORY.md 56.1).
2. **Implemented in** `src/gmes/browser/chrome.py`, one argument in
   `launch_chrome_with_user_profile()`.
3. **Offline tests** `tests/unit/test_new_machine.py::
   test_popup_blocking_is_disabled_so_the_ad_sso_window_can_open`.
4. **Live proof** **Yes.** Proven live in Phase 56: before the flag no SSO
   target ever appeared; after it, the popup opens and reaches
   `stseu.secsso.net/adfs/ls/`, captured by `gmes_sso_diagnose.py`.
5. **Dependencies on the new architecture** None. It is a string in a list.
6. **Smallest reproduction around legacy** Add `--disable-popup-blocking` to
   the argument list in `cdp_common.launch_chrome_with_user_profile()`.
   One line.
7. **Classification** **KEEP** — port to `cdp_common.py`.
8. **Evidence that must survive** A test asserting the legacy launcher passes
   `--disable-popup-blocking`. **Caution:** `cdp_common.py` is shared with
   N-ERP, so the N-ERP offline suite must be re-run after the change.

## 0b. Screenshot targets the G-MES tab — **KEEP**

1. **Problem** `capture_screenshot()` asks `get_page_tab()` for `pages[0]` —
   whichever page target the browser lists first. With a leftover popup open,
   the "diagnostic screenshot" silently shows the wrong page. It reads as
   evidence and is not; it nearly produced a wrong diagnosis in Phase 56.4.
2. **Implemented in** `src/gmes/browser/screenshots.py` (fixed);
   **`cdp_common.py` still has the bug.**
3. **Offline tests** `tests/unit/test_screenshots.py` (1 test).
4. **Live proof** **Yes** — the bug was found by being misled by it live.
5. **Dependencies on the new architecture** None; it is one argument.
6. **Smallest reproduction around legacy** Pass the G-MES host as
   `prefer_url_substring` on the G-MES screenshot path in `cdp_common.py`.
   **Constraint:** `get_page_tab()`'s default there is `"nerps"` for N-ERP —
   do not change the default, pass the value at the G-MES call site only.
7. **Classification** **KEEP** — port, carefully, without touching N-ERP's
   default.
8. **Evidence that must survive** A test proving the G-MES screenshot path
   prefers the G-MES host; N-ERP suite green afterwards.

---

# Tier 1 — external tools (highest value, lowest coupling)

## 1. External supervisor / watchdog — **KEEP as an independent tool**

1. **Problem** A genuine hang raises nothing and returns nothing. Every other
   recovery mechanism runs *inside* the process that might be stuck, so none
   of them can act. An unattended job stuck at 02:00 looks identical to one
   still working, and is discovered at 08:00 (HISTORY.md 52.1).
2. **Implemented in** `src/gmes/application/supervisor_uc.py` (110 lines).
3. **Offline tests** `tests/unit/test_supervisor.py`, 20 tests — including
   the Phase 54.1/54.2 case (a process that never beats at all) and 54.3
   (the killed child cannot send its own alert).
4. **Live proof** **None.** Never run against a real hang.
5. **Dependencies on the new architecture** **Almost none.** It already runs
   its target as a **child process** (`spawn=subprocess.Popen`) and kills by
   PID/tree. The only coupling is `_command(argv)`, which builds a
   `gmes <command>` line, plus `alerts` and `heartbeat`.
6. **Smallest reproduction around legacy** A standalone `GMES_Watchdog.bat` /
   `gmes_watchdog.py` that spawns **`GMES_Workflow.bat`** instead of
   `python -m gmes`, polls a liveness signal, and on total silence kills the
   process tree and restarts it. **It never imports the legacy engine at
   all** — it only launches it. This is the single cleanest extraction in the
   whole package.
7. **Classification** **KEEP** — as `GMES_Watchdog`, external, wrapping the
   `.bat`. Not part of `gmes_core.py`.
8. **Evidence that must survive** The 20 supervisor tests, re-pointed at the
   legacy command. Two must survive by name because they pin real defects:
   the never-beat case (54.1) and "a killed process cannot alert for itself"
   (54.3). **Also carry over CLAUDE.md 2.6:** kill by PID/tree, never
   `taskkill /IM chrome.exe`.
   **Known debt:** the flaky `...never_beats_even_once...` test uses a real
   0.05s wall-clock threshold. Fix the timing when re-pointing it; do not
   copy the flake.

## 2. Per-process heartbeat — **REBUILD SMALL**

1. **Problem** The watchdog needs to tell "slow but working" from "stuck",
   from outside the process.
2. **Implemented in** `src/gmes/application/heartbeat.py` (68 lines:
   `beat`/`read`/`age_seconds`/`clear`).
3. **Offline tests** Covered inside the 20 supervisor tests.
4. **Live proof** None.
5. **Dependencies on the new architecture** One: `paths.heartbeat_path`.
6. **Smallest reproduction around legacy** Two options, smallest first:
   - **Option A (zero legacy edits, preferred to start):** the watchdog
     watches the **mtime of the legacy log file** that `gmes_log.py` already
     writes. No heartbeat file, no calls inside legacy, nothing to port.
   - **Option B (if A proves too coarse):** a `gmes_heartbeat.py` that *only*
     reports progress, with `beat()` called at a handful of legacy points.
7. **Classification** **REBUILD SMALL** — try Option A first; it may make
   this capability unnecessary.
8. **Evidence that must survive** Phase 55.2: the liveness file must be
   **scoped per process id**, never one shared path, or two runs read and
   clear each other's signal. If Option A is used, the equivalent rule is:
   watch the log file belonging to *that* run.

## 3. Checkpoint / resume — **REBUILD SMALL**

1. **Problem** A power cut or a killed process loses the record of screens
   that already exported a real file, and the next launch redoes them.
2. **Implemented in** `src/gmes/application/checkpoint.py` (119 lines).
3. **Offline tests** `tests/unit/test_checkpoint_resume.py`, 22 tests.
4. **Live proof** None — never exercised against a real interrupted process.
5. **Dependencies on the new architecture** Two: `contracts.RunResult` and
   `paths.batches_dir`. `RunResult` is a plain dataclass; a tuple or dict
   replaces it.
6. **Smallest reproduction around legacy** `gmes_checkpoint.py` that *only*
   persists and verifies completed workflow steps, keyed by a digest of the
   request. It must not know how to run anything.
7. **Classification** **REBUILD SMALL** — independent module, used by the
   watchdog wrapper, never by `gmes_core.py`.
8. **Evidence that must survive** Three hard-won rules, each with its test:
   - keyed by **what the batch ASKS FOR**, never what it proved (51.1);
   - **re-verify the files still exist on disk** before skipping a screen —
     a checkpoint is never a promise stronger than the filesystem (54.7);
   - **expire after 6 hours**, so a command re-run a week later cannot
     silently skip work.

---

# Tier 2 — techniques to fold into legacy (small, surgical)

## 4. Fault-vs-refusal classifier — **REBUILD SMALL**

1. **Problem** This project's deliberate refusals ("no filter matches X",
   "which grid?", "the query returned no rows") are all `RuntimeError`, so an
   exception handler cannot tell a fault from a decision. Retrying a refusal
   restarts the browser three times to reach the same answer (46.2), and
   counting one toward a breaker quarantines a healthy screen (54.6).
2. **Implemented in** `recovery.py::is_a_decision()`.
3. **Offline tests** Inside the 18 recovery tests.
4. **Live proof** None.
5. **Dependencies on the new architecture** None — it matches phrases and
   argument-error types.
6. **Smallest reproduction around legacy** A ~20-line helper function next to
   whatever retries.
7. **Classification** **REBUILD SMALL** — this is the most reusable idea in
   the package and the cheapest to keep.
8. **Evidence that must survive** Tests proving a refusal is never retried
   and never counted as a fault.

## 5. Recovery ladder (the rungs themselves) — **DISCARD**

1. **Problem it solved** One transient failure ended a whole night's batch.
2. **Implemented in** `recovery.py` (115 lines) + `session_uc.py` (127 lines).
3. **Offline tests** 18.
4. **Live proof** None.
5. **Dependencies on the new architecture** **Very high.** `session_uc.py`
   imports from `browser.cdp`, `browser.chrome`, `contracts`, `nexacro`,
   `nexacro.app_state`, `connect_uc`, `sign_in_uc` and `auth.session` — eight
   dependencies. Rebuilding it means rebuilding the layer being deleted.
6. **Smallest reproduction around legacy** There isn't a small one, and it is
   **largely superseded**: an external watchdog that restarts the whole
   legacy workflow achieves the outcome (a fresh browser, a fresh session)
   without an in-process ladder. That is the RESTART/RESUME split.
7. **Classification** **DISCARD** — but keep `is_a_decision()` (#4) and keep
   the two safety rules below in whatever restarts things.
8. **Evidence that must survive** Two rules, as tests on the watchdog:
   - a **cold start must never pass `refresh_profile`** — restarting a
     process and destroying its state are different actions, and the profile
     copy holds the working session (46.4, CLAUDE.md 2.1a);
   - a repair must be **bounded** — a wall-clock budget and a restart cap, or
     a ladder with no top is a loop.

## 6. Circuit breaker — **REBUILD SMALL (optional, lowest priority)**

1. **Problem** A screen broken for days burns the full recovery budget every
   night for an answer that has not changed.
2. **Implemented in** `application/circuit.py` (98 lines).
3. **Offline tests** `tests/unit/test_circuit_breaker.py`, 16 tests.
4. **Live proof** None.
5. **Dependencies** One: `paths.circuit_dir`.
6. **Smallest reproduction around legacy** A small per-screen counter file
   read by the batch wrapper, not by the engine.
7. **Classification** **REBUILD SMALL, optional.** Defer until the watchdog
   and checkpoint are proven live; it is the least urgent.
8. **Evidence that must survive** Phase 54.6 — **a deliberate refusal must
   never trip the breaker** (three bad filter values must not quarantine a
   healthy screen); and Phase 50.2 — a skipped screen must not abort the rest
   of the batch, while a genuinely attempted failure still does.

## 7. Failure alerts — **REBUILD SMALL (optional)**

1. **Problem** A failed nightly run was only discovered by opening a log the
   next morning.
2. **Implemented in** `application/alerts.py` (94 lines), stdlib `smtplib`.
3. **Offline tests** `tests/unit/test_alerts.py`, 19 tests.
4. **Live proof** None — never sent through a real mail server.
5. **Dependencies** `auth.credentials` (DPAPI) and `paths`.
6. **Smallest reproduction around legacy** `gmes_alert.py`, called by the
   watchdog wrapper on failure. The engine should not know it exists.
7. **Classification** **REBUILD SMALL, optional** — pairs naturally with the
   watchdog, which is also the only thing that can report a killed run.
8. **Evidence that must survive** — these are security fixes, not features:
   - `ehlo()` **before** `has_extn("STARTTLS")`, and again after `starttls()`
     — `has_extn` reads a cache, not the server (54.4);
   - the SMTP password lives in **its own DPAPI file**, never an environment
     variable (54.5);
   - **refuse to send at all** if a saved credential would travel over an
     unencrypted channel (55.1);
   - never alert on success.

## 8. Popup close verification — **REBUILD SMALL (technique)**

1. **Problem** Clicking a popup's `.closebutton` can silently not land. The
   notice then sits on top of the next control, and the run fails on
   something unrelated-looking (45.1). A notice raised *during* a run
   swallowed the Inquiry click (45.2).
2. **Implemented in** `src/gmes/nexacro/popups.py` (267 lines).
3. **Offline tests** `tests/unit/test_notice_popups.py`, 12 tests.
4. **Live proof** None.
5. **Dependencies** `browser.cdp`, `browser.interaction`, `js_snippets`.
6. **Smallest reproduction around legacy** **Legacy already has
   `gmes_common.close_child_popups()` / `find_child_popups()` — and it uses
   the single `.closebutton` mechanism the incident was about.** Port the
   *technique*, not the module: (a) confirm the popup actually disappeared
   rather than counting the click, (b) fall back to Nexacro's own
   `ChildFrame.close()` resolved from the title-bar id, (c) close only what
   can be positively identified.
7. **Classification** **REBUILD SMALL** — a surgical improvement to
   `gmes_common.py`.
8. **Evidence that must survive** Gotchas #48/#49: a popup that survives both
   mechanisms is reported as "would not close", never counted as closed; and
   never close an unidentifiable window (the Excel dialog is also a child
   popup) — sweep only at screen open, before Inquiry, before the Excel icon.

## 9. Export retry — **REBUILD SMALL (technique)**

1. **Problem** One missed Excel download lost a whole unattended night, and
   the confirm button was matched against the single label "OK" (45.5).
2. **Implemented in** `src/gmes/export/excel.py` (111 lines).
3. **Offline tests** `tests/unit/test_exports.py`, 15 tests.
4. **Live proof** None.
5. **Dependencies** `browser.cdp`, `browser.interaction`, `nexacro.dom`.
6. **Smallest reproduction around legacy** Port three behaviours into
   legacy's export path: retry up to 3 times; **re-establish what the attempt
   depends on** each time (bring the screen forward, clear what covers it) so
   a retry is a different attempt rather than a repeat; accept any of the
   known confirm labels.
7. **Classification** **REBUILD SMALL** — technique, not module.
8. **Evidence that must survive** Gotcha #50 (the confirm button is not
   always "OK": try OK / 확인 / Ok / Yes / 예 / Save / 저장 and name every
   label looked for on failure), and Phase 45.6 — **before a retry, dismiss
   the dialog the failed attempt itself left open**, or the second click
   fires into an open dialog, which CLAUDE.md 3.9 forbids.

## 10. Record/replay drift fix — **REBUILD SMALL (technique)**

1. **Problem** A screen recorded *with* a left-panel option could never be
   replayed: the shape was recorded at the END of a run (after `set_option()`
   had rebuilt the panel) but compared at the START of the next one, so a
   screen never matched itself (48.1).
2. **Implemented in** `src/gmes/discovery/fingerprint.py` (87 lines).
3. **Offline tests** `tests/unit/test_record_replay.py`, 13 tests.
4. **Live proof** None.
5. **Dependencies on the new architecture** **None — zero intra-package
   imports.** It was ported *from* legacy `gmes_profile.py` in the first
   place.
6. **Smallest reproduction around legacy** Apply the fix to
   `gmes_profile.py`: record the shape from the screen **as opened**, and
   split the drift check — shape verified before anything is clicked,
   saved references verified after the saved options have rebuilt the panel.
7. **Classification** **REBUILD SMALL** — port the fix back to its origin.
8. **Evidence that must survive** A round-trip test: a screen recorded with a
   left-panel option replays without being refused. Plus `--relearn` (48.2):
   a refusal must have an exit, or a drifted screen stops working until
   somebody deletes a file by hand.

---

# Tier 3 — discard

## 11. Browser/profile launch ladder — **DISCARD** (except 0a)
Ordered launch attempts, clean-profile strategy, Edge fallback
(`browser/chrome.py`, Phases 47/49). Never live-proven; the failure modes it
covers (corrupted profile, missing Chrome) have never occurred here. **The
one piece with live proof, `--disable-popup-blocking`, is rescued separately
as 0a.** Keep the *rule* from 49.1 in mind if this is ever rebuilt: an
explicit profile refresh must never be silently substituted with a different
combination. **Evidence to survive:** none beyond 0a.

## 12. Onboarding / install identity — **DISCARD**
`auth/install.py`, `onboarding_uc.py` (Phase 47.3/47.4). Only matters on a
second machine; never exercised on one. **Two ideas worth remembering if a
second machine ever happens**, though neither needs code today: a DPAPI store
cannot be decrypted by another Windows account, so "no credentials" must
distinguish *nobody set this up* from *somebody else did*; and a password
prompt must only appear when a console is attached, or the nightly job hangs
at a modal window until morning. **Evidence to survive:** none.

## 13. Guided screen preview — **DISCARD**
`application/workflow_uc.py` (Phase 45.3/45.4) — open the screen before
asking, list filters/options/divisions with current state. Genuinely good,
but **very highly coupled** (contracts, discovery, run_many, cli_inputs) and
**legacy already has its own guided workflow** with an equivalent
(`run_gmes_workflow.show_screen_offer` lists every screen-filled input with
`--set` guidance — the restored `tests/test_gmes_workflow.py` covers it).
Rebuilding it would mean rebuilding the layer being deleted, to replace
something that already exists. **Evidence to survive:** the restored legacy
workflow tests, already in place from Step 4.

---

# Recommended extraction order

Each step is independently committable and independently revertible.

| Order | What | Why this position |
|---|---|---|
| **E1** | Port `--disable-popup-blocking` to `cdp_common.py` (0a) | The legacy core **cannot do AD SSO without it** and it is live-proven. Re-run the N-ERP suite: `cdp_common.py` is shared. |
| **E2** | Port the screenshot-target fix to the G-MES path (0b) | A live bug in the production core today. Do not change `get_page_tab`'s `"nerps"` default; pass the host at the G-MES call site. |
| **E3** | Extract `GMES_Watchdog` as an external tool (1) + liveness via log mtime (2, Option A) | Highest value, lowest coupling, **zero legacy edits** — it only launches `GMES_Workflow.bat`. Delivers RESTART on its own. |
| **E4** | Extract `gmes_checkpoint.py` (3) | Delivers RESUME, kept strictly separate from RESTART. Depends on nothing in E3. |
| **E5** | Port `is_a_decision()` (4) | ~20 lines; makes E3/E4 and any future retry honest about faults vs refusals. |
| **E6** | Port the popup-close technique into `gmes_common.py` (8) | Surgical fix to a mechanism legacy genuinely has and that genuinely fails. |
| **E7** | Port the export-retry technique (9) | Same shape as E6; unattended value. |
| **E8** | Port the record/replay drift fix to `gmes_profile.py` (10) | Returning a fix to the file it came from; zero coupling. |
| **E9** | *Optional:* circuit breaker (6), alerts (7) | Defer until E3/E4 are live-proven. Alerts carry security fixes that must be copied exactly. |
| **E10** | Only now begin Step 5+ deletion of `src/gmes` | Everything classified KEEP or REBUILD SMALL has landed or been consciously deferred. |

**E1 and E2 are not optional and should not wait for Step 5.** Everything
else may be deferred, but must not be *forgotten* — which is what this map is
for.

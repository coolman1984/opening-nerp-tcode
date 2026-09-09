# PROJECT_EYE.md — Living Project Map

Last structural baseline reviewed: `main` at `a125edad5970c2445d92087b19369bb3931bc8da` before this governance branch.

## Product promise

Build reliable unattended enterprise browser automation that can open internal business systems, reach the intended business screen, apply required criteria, wait for real readiness, execute, verify the result, and deliver trustworthy output without fragile coordinate clicking or timing guesses.

Current systems:

- NERP / SAP GUI for HTML
- GMES / Nexacro

## Current remote truth

At the reviewed remote baseline, `main` contains the original NERP automation only:

- `cdp_common.py`
- `search_tcode.py`
- `execute_filters.py`
- `export_to_excel.py`
- `run_nerp_workflow.py`
- `NERP_Workflow.bat`
- `SKILL.md`

The GMES implementation described in `GMES_SKILL.md` was validated in a local working session but was not yet present in remote `main` at that baseline. Any agent merging the GMES implementation must first compare its local working tree with current remote `main`; do not reconstruct or overwrite validated local code from documentation alone.

## Critical user journeys

### J1 — NERP report automation

`start Chrome/CDP -> open NERP -> search T-code -> wait for WebGUI target -> fill filters -> Execute -> wait for real result readiness -> export -> verify output`

### J2 — GMES unattended login

`cold start -> launch Chrome with dedicated profile -> detect login/session state -> load encrypted credentials -> sign in -> wait for Nexacro semantic readiness -> observe delayed Notice popup(s) -> close blockers -> prove application is stable`

### J3 — GMES Production Plan by Order(Line)

`authenticated stable GMES -> reach screen by stable screen code/direct search -> set plan date -> set Division VD -> run Inquiry -> wait for non-zero/stable result dataset -> reconcile visible total vs underlying rows -> export GMES official Excel -> copy to Data Hub -> optionally create machine-readable CSV -> verify row count/output`

## Core

The core is the smallest trusted behavior that makes these automations reliable:

1. **CDP session/target control** — discover and connect to the correct live browser/page/frame target.
2. **Semantic element discovery** — find controls by stable meaning rather than position or generated identity.
3. **Readiness/completion gates** — advance only on meaningful runtime evidence.
4. **Workflow state/orchestration** — explicit prerequisites, outputs, waiting, failure, retry, and terminal states.
5. **Data/result verification** — prove that extracted/exported data matches business-visible truth.
6. **Safe credentials/session handling** — never place secrets in source/logs/docs.
7. **Evidence and recovery** — screenshots/logs/status only where they prove or diagnose behavior safely.

## Branches around the core

### NERP adapters

- SAP Fiori shell target discovery
- SAP WebGUI iframe target discovery
- selection-screen label mapping
- multiple SAP export-dialog flows

### GMES adapters

Expected local implementation names from the validated session:

- `gmes_common.py`
- `gmes_login.py`
- `gmes_credentials.py`
- `gmes_find.py`
- `gmes_data.py`
- `gmes_probe_excel.py`
- `gmes_daily_prodplan.py`

These names are historical evidence, not permission to assume the files exist remotely. Verify first.

## State and data ownership

Important concepts must have one authority:

- browser/CDP target identity -> session/target discovery layer
- login/session state -> login/session logic
- credentials -> encrypted Windows-bound credential store, never source files
- GMES screen identity -> stable screen/form codes, not generated window IDs
- workflow step state -> orchestrator/state machine
- query result truth -> result dataset + verified business count rules
- final file delivery -> export/delivery component
- project learning -> `SKILL.md`, `GMES_SKILL.md`, `HISTORY.md`, `CHANGELOG.md`

If two components independently decide the same truth, treat it as an ownership conflict.

## Stable identity hierarchy

Prefer, in order:

1. business/screen code or semantic label;
2. stable component/form name;
3. relationship to stable anchors;
4. stable attributes/title/type;
5. generated ID only if proven stable enough for that boundary;
6. visible geometry as fallback;
7. raw coordinates only as last resort.

## Runtime readiness law

Never equate:

- document loaded;
- element count above threshold;
- previous command returned;
- first success marker appeared;

with true readiness.

A critical step is complete only when:

`action succeeded + required semantic state exists + delayed side effects settled + next-step prerequisites are ready`

Examples already observed:

- Nexacro reports DOM complete before named controls exist.
- GMES Notice popup appears after login initially looks successful.
- a dataset can sit at zero while server work is still in flight.
- a visible grid can contain only rendered rows while the full dataset is larger.

## Data trust gate

No data extraction/export is trusted until the agent records and reconciles:

- source screen/report;
- business filters;
- date/range;
- visible business total;
- underlying dataset total;
- exclusion/filler-row rule if any;
- delivered file row count where readable;
- output path/name;
- DRM/encryption status;
- verification evidence.

Unexplained count differences are blockers, not cosmetic warnings.

## Known GMES business landmarks

Validated during the Production Plan by Order(Line) investigation:

- report path: `PPM > Production Plan > Prod. Plan Inquiry > Detail Schedule > Production Plan by Order(Line)`
- breadcrumb screen codes observed: `P1112UM00 > P1112WM00`
- filter panel observed: `P1112WF00`
- result screen observed: `P1112WM00`
- Division `VD` is mandatory for the intended report workflow
- GMES search can jump directly by ScreenID, reducing menu traversal
- official Excel export opens a `Save to Excel` popup before download
- official exported workbook is NASCA DRM-protected in the observed environment

Treat screen codes as strong evidence from the validated session, but reverify if GMES is upgraded.

## Main red zones

1. **Timing assumptions** — fixed sleeps and one-shot checks.
2. **Generated IDs** — window IDs can change between opens.
3. **Nested frames/forms** — top-level inspection can miss real controls/popups.
4. **Virtualized grids** — visible rows are not guaranteed to equal the full dataset.
5. **Async zero-state** — temporary empty data can mean “still loading,” not “no data.”
6. **Delayed blockers** — popups can arrive after apparent login success.
7. **DRM outputs** — a file can exist and open manually while remaining unreadable to downstream programs.
8. **Unexplained count gaps** — must be explained before production trust.
9. **Local-vs-remote drift** — validated GMES work may exist only in a local worktree until deliberately merged.

## Problem discovery radar

When the project grows, inspect:

- dependency cycles;
- high fan-in/high fan-out modules;
- files that repeatedly change together;
- repeated reverts/incidents;
- duplicate business rules;
- duplicate state writers;
- hidden globals/config coupling;
- runtime paths missing from the map;
- components used by many critical journeys with weak proof;
- tests that assert implementation trivia rather than business behavior.

Prioritize roughly by:

`change frequency x complexity x journey criticality x blast radius`

## Isolation and repair sequence

For a tangled area:

`map -> characterize -> find seam -> wrap/isolate -> stop new spread -> extract one responsibility -> prove -> migrate one consumer -> observe -> repeat -> cut over -> remove old path`

Do not rewrite a large working subsystem from documentation alone.

## Test strategy

Prefer a proof matrix over raw test count:

- core invariant -> focused unit/component test
- cross-component assumption -> contract/integration test
- async sequencing -> state-machine/timing test
- failure/retry -> recovery/idempotency test
- critical business journey -> small number of strong end-to-end tests
- browser/system-specific behavior -> controlled real-environment proof

A test is valuable only if a meaningful defect would make it fail.

## Mandatory learning loop

After a meaningful new discovery:

`problem/discovery -> root cause -> reusable rule -> regression proof -> skill update -> history entry -> map update if structural -> changelog/version link`

If the lesson exists only in chat, the repository has not learned it.

## Release gate

Before calling a version production-ready:

- cold-start journey passes;
- expired/no-session path passes;
- delayed popup behavior is handled;
- readiness uses semantic conditions;
- result count/data is reconciled;
- official export path is proven;
- downstream-readable path is proven if required;
- errors leave useful evidence without secrets;
- docs/skills/history match code;
- remote `main` contains the validated implementation;
- final main commit is recorded.
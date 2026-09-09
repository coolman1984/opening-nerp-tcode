# Enterprise Browser Automation — NERP + GMES

This repository contains browser automation work for Samsung internal systems, currently covering:

- NERP / SAP GUI for HTML
- GMES / Nexacro

The project is designed around semantic browser/runtime inspection, explicit readiness conditions, trustworthy data verification, and unattended execution rather than fragile coordinate clicking or fixed timing assumptions.

## For AI coding agents

Read these files before changing code:

1. `AGENTS.md` — mandatory operating contract
2. `PROJECT_EYE.md` — architecture, core, journeys, state, risks
3. `GMES_SKILL.md` — GMES/Nexacro runtime knowledge
4. `SKILL.md` — NERP/SAP runtime knowledge
5. `HISTORY.md` — issue/root-cause/solution history
6. `CHANGELOG.md` — version lineage

Claude Code also gets the same routing through `CLAUDE.md`.

## Current remote baseline note

At the reviewed remote baseline before the governance update, `main` contained the NERP implementation only. The GMES implementation described in `GMES_SKILL.md` had been validated in a local development session but was not yet present on remote `main`.

Do not rebuild those local GMES files from documentation if the validated working tree still exists. Compare the local working tree with remote first, then merge deliberately.

## NERP flow

`Chrome/CDP -> NERP -> T-code search -> SAP WebGUI target -> filters -> Execute -> wait for result -> export -> verify`

Primary files currently on remote baseline:

- `cdp_common.py`
- `search_tcode.py`
- `execute_filters.py`
- `export_to_excel.py`
- `run_nerp_workflow.py`
- `NERP_Workflow.bat`

See `SKILL.md` for detailed behavior and solved environment gotchas.

## GMES proven target flow

Validated locally during the GMES investigation:

`cold start -> protected login -> semantic Nexacro readiness -> delayed-popup stabilization -> direct report navigation -> set date -> Division VD -> Inquiry -> wait for real data -> reconcile row counts -> official Excel export -> Data Hub delivery -> optional clean CSV`

The exact implementation files must be verified against the local working tree before remote integration. See `GMES_SKILL.md` and `HISTORY.md` for the proven behavior and issue history.

## Engineering principles

- Observe real runtime behavior before generalizing.
- Prefer stable semantic identity over generated IDs or coordinates.
- Wait on meaningful readiness/completion conditions, not arbitrary sleeps.
- Treat delayed side effects as part of step completion.
- Separate automation success from data correctness.
- Reconcile visible totals vs underlying data before trust.
- Keep credentials out of source/logs/docs.
- Update the project skill/history after meaningful discoveries.
- Keep the project map current as architecture grows.

## Project memory

If a hard problem is solved but the lesson exists only in a chat transcript, the repository has not learned it. The mandatory learning loop is:

`discovery/problem -> root cause -> reusable rule -> regression evidence -> skill update -> history entry -> project map update when structural -> changelog/version link`

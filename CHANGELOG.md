# CHANGELOG.md

This file records why meaningful repository versions exist. Exact code identity comes from Git commits/tags; this file explains the human reason and behavior change.

## Unreleased / governance + GMES knowledge integration — 2026-09-09

Based on remote `main` baseline `a125edad5970c2445d92087b19369bb3931bc8da`.

### Why this version exists

The project expanded from the original NERP automation into a second enterprise automation track for GMES/Nexacro. The local GMES investigation produced substantial reusable runtime knowledge, including semantic control discovery, cold-start login, encrypted credential handling, delayed-popup stabilization, dataset-level extraction, direct screen addressing, result-count reconciliation, official GMES Excel export, DRM detection, and a machine-readable companion output.

The repository also needed durable controls so future AI agents do not lose those lessons, repeat the same failures, or expand the project without understanding the core/journeys/state.

### Added

- `AGENTS.md` — mandatory operating contract for any AI coding agent.
- `PROJECT_EYE.md` — living project/core/journey/state/risk map.
- `GMES_SKILL.md` — mandatory living GMES/Nexacro skill and proven runtime rules.
- `HISTORY.md` — problem/root-cause/solution/evidence history.
- `CHANGELOG.md` — version lineage and release reasoning.

### Important remote-state note

At the reviewed baseline, the validated GMES implementation files existed in the local development session but were not yet present in remote `main`. This governance change intentionally does not reconstruct unseen local code from documentation. The validated local GMES working tree must be compared and merged separately/safely.

### Verification required before calling GMES production-ready on remote main

- validated GMES files are actually present remotely;
- cold-start login passes;
- delayed Notice popup stabilization passes;
- Production Plan by Order(Line) direct navigation/filters pass;
- Division VD is verified;
- query does not falsely settle at temporary zero;
- business total and clean-data rows reconcile;
- official Excel reaches the intended Data Hub folder;
- NASCA DRM status is correctly reported;
- machine-readable companion data matches the verified business rows;
- skills/history/project map match the final code.

---

## 0.1.0 — Initial NERP automation — 2026-09-09

Commit: `a125edad5970c2445d92087b19369bb3931bc8da`

Reason: initial repository baseline for NERP T-code automation.

Included:

- Chrome/CDP helper layer;
- NERP T-code search;
- SAP selection-screen filter automation;
- report Execute flow;
- multiple Excel export strategies;
- standalone workflow launcher;
- detailed NERP reusable skill/history in `SKILL.md`.

The existing `SKILL.md` is the detailed source for solved NERP/SAP environment and runtime gotchas.
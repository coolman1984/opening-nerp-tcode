# AGENTS.md — Mandatory Operating Contract

This repository contains enterprise browser automation for Samsung NERP and GMES. Any AI coding agent must read this file before changing code.

## Mandatory read order

1. `AGENTS.md`
2. `PROJECT_EYE.md`
3. `GMES_SKILL.md` when touching GMES/Nexacro work
4. `SKILL.md` when touching NERP/SAP work
5. `HISTORY.md`
6. `CHANGELOG.md`
7. The exact code, tests, scripts, and contracts in the affected subgraph

Do not start by blindly editing files.

## Core rule

Treat the repository as a system of user journeys, state, contracts, runtime timing, browser targets, datasets, files, and verification evidence. A change is complete only when the affected journey is proven end to end.

## Before every meaningful change

Record or determine:

- user/business goal;
- affected journey;
- target component;
- callers and dependencies;
- state/data owner;
- external system boundary;
- expected side effects;
- readiness condition before the step;
- success condition after the step;
- possible delayed effects after apparent success;
- failure and retry behavior;
- output/data integrity check;
- blast radius.

## Mandatory engineering behavior

- Observe real runtime behavior before generalizing.
- Prefer stable semantic identity over generated IDs, screen position, timing guesses, or DOM order.
- Never use fixed sleeps when a meaningful readiness/completion signal exists.
- Never assume the previous step finishing means the next step is ready.
- Model waiting explicitly.
- After apparent success, watch for delayed popups, navigation, queued UI changes, network work, or data refresh before advancing.
- For multi-step workflows, define inputs, outputs, prerequisites, success/failure predicates, timeout, retry, checkpoint, idempotency, and evidence.
- Do not read another step's private state. Exchange named results/contracts.
- Do not announce success because a command returned zero. Prove the business result.
- Data correctness is independent from automation correctness. Reconcile counts/filters/output before trusting extraction.
- If visual data is virtualized, investigate the system's real data source before scraping only visible rows.
- Keep at least one safe fallback path for critical extraction or navigation where practical.
- Never store passwords, tokens, cookies, or sensitive data in source, logs, screenshots, docs, history, or skills.

## Failure workflow

Use:

`symptom -> reproduce -> evidence -> first divergence -> real owner -> smallest safe fix -> regression proof -> journey proof`

Do not patch only the final visible symptom.

## Large/tangled areas

Before refactoring:

1. map callers/dependencies/state/contracts/journeys;
2. capture current important behavior;
3. find the narrowest safe seam;
4. wrap or isolate the tangled area;
5. block new direct dependencies into its internals;
6. extract one responsibility at a time;
7. prove old vs new behavior;
8. migrate one consumer/journey at a time;
9. cut over ownership only after proof;
10. remove the old path only after verified non-use.

## Tests

Test count is not evidence quality. Every important test must state what risk, invariant, contract, or failure class it protects.

Prioritize:

- core invariants;
- state transitions;
- cross-component contracts;
- failure/recovery;
- idempotency;
- critical end-to-end journeys;
- real-environment checks where mocks cannot prove the behavior.

Do not create shallow tests merely to increase counts or coverage. Do not weaken tests to make a build green.

## Mandatory project learning update

After every meaningful discovery, hard bug, new runtime trick, changed integration rule, new failure mode, or architecture change, update the repository knowledge before declaring the task complete:

- `GMES_SKILL.md` or `SKILL.md`: reusable procedure/trick/constraint;
- `HISTORY.md`: problem -> root cause -> fix -> proof -> lesson;
- `PROJECT_EYE.md`: architecture/journey/state map when materially changed;
- `CHANGELOG.md`: notable version/release behavior changes.

If a related skill already exists, update it. Do not create a second competing source of truth.

If the implementation changes a documented skill and the skill is not revalidated, mark that skill section `NEEDS REVALIDATION`.

## Version discipline

Every new version must answer:

- based on which previous version/commit;
- why the new version exists;
- what changed;
- which problems it resolves;
- whether contracts/data formats changed;
- what evidence justified release;
- rollback path.

Never create unexplained `final2`, `v3-new`, copied-project folders, or silent released-file replacement.

## Git discipline

- Check branch/base before changes.
- Protect unrelated user changes.
- Prefer a dedicated branch for meaningful work.
- Do not force-push unless explicitly authorized.
- Review the diff before merge.
- Merge only after required verification.
- After merge, verify `main` points at the intended merge result.

## Completion report

An agent finishing meaningful work must report:

- outcome;
- changed files/components;
- affected journey;
- core/state/contract impact;
- verification evidence;
- unresolved risks;
- documentation/skill/history updates;
- final branch/commit/merge state.

Activity is not achievement. Report evidence.
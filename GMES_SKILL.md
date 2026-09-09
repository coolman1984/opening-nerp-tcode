# GMES_SKILL.md — Living GMES/Nexacro Automation Skill

Status: **LIVING SKILL — mandatory update after every meaningful GMES discovery or behavior change.**

This file captures reusable knowledge proven while automating Samsung GMES with Chrome DevTools Protocol and Nexacro. It is not a chat transcript. It is a compact engineering memory of what failed, why, what worked, and how to verify it.

## Mandatory freshness rule

Any agent that changes GMES behavior, selectors, login, screen navigation, datasets, export, waiting, credentials, file delivery, or verification must update this file before declaring the task complete.

For every changed rule, record:

- what changed;
- why;
- evidence;
- affected files/components;
- whether the rule is still verified or needs revalidation.

If code changes make a section uncertain, mark it `NEEDS REVALIDATION` instead of silently leaving stale guidance.

## Proven platform model

GMES uses Nexacro, but the observed application is not a blind canvas. It exposes meaningful page/form/control structures that can be reached through browser runtime inspection. Therefore the default strategy is:

`semantic system identity -> Nexacro/form/dataset inspection -> DOM/runtime control -> geometry-based click if needed -> coordinates only as last resort`

Do not start with screenshot coordinates.

## Proven unattended journey

Validated local workflow during the 2026-09-09 session:

1. start Chrome with the intended profile/CDP access;
2. detect whether GMES is already signed in or showing the login screen;
3. retrieve credentials from a Windows-account-bound encrypted store;
4. sign in;
5. wait for a named semantic control/session marker, not document readyState or raw element count;
6. observe for delayed Notice popup(s);
7. close blocking popup(s), including queued/repeated notices;
8. reach Production Plan by Order(Line);
9. set the required plan date;
10. select Division `VD`;
11. run Inquiry;
12. wait for a meaningful result dataset to arrive and settle;
13. reconcile real rows against the business-visible total;
14. open GMES `Save to Excel` flow and download the official workbook;
15. deliver it to the Data Hub folder;
16. optionally write a clean machine-readable CSV from the internal dataset because the official workbook is DRM protected;
17. verify final counts and files.

## Expected local GMES files from the validated session

The local working session created/used names including:

- `gmes_common.py`
- `gmes_login.py`
- `gmes_credentials.py`
- `gmes_find.py`
- `gmes_data.py`
- `gmes_probe_excel.py`
- `gmes_daily_prodplan.py`

Important: these names document the validated local work. At the reviewed remote baseline, they were not yet on `main`. Verify repository reality before editing or reconstructing anything.

# Core lessons and solved traps

## 1. GMES semantic controls are real and preferable to coordinates

Observed: Nexacro renders real reachable controls with meaningful identities. Buttons/forms can be targeted semantically.

Rule:

- prefer screen/form/control identity and label;
- avoid window position and fixed coordinates;
- use geometry only to dispatch a real browser click when a framework-level click is ineffective.

Why: screen position, resolution, and window size are environmental noise.

## 2. Generated window/screen IDs are unstable

Observed: inquiry window IDs changed between opens, for example suffixes changed while the business screen remained the same.

Rule:

- do not bind production logic to ephemeral generated window IDs;
- target stable screen codes, form names, component labels, or business breadcrumb identifiers.

Known useful screen identity from the validated report:

- breadcrumb: `P1112UM00 > P1112WM00`
- filter panel: `P1112WF00`
- result screen: `P1112WM00`

Reverify after material GMES upgrades.

## 3. Breadcrumb/screen code is an address

Observed: the page breadcrumb exposes exact screen codes. GMES also provides a search box that accepts ScreenID.

Rule:

- prefer direct ScreenID navigation when proven rather than replaying a long menu path;
- retain the human breadcrumb in documentation as the semantic meaning of the code.

Validated report path:

`PPM > Production Plan > Prod. Plan Inquiry > Detail Schedule > Production Plan by Order(Line)`

## 4. Nested forms/frames hide important controls

Observed: a Notice popup was not found by a top-level-only inspection. It lived deeper in the Nexacro structure.

Rule:

- inspection/search tools must walk relevant inner forms/frames/components;
- a failed top-level search is not proof that the control does not exist.

Reusable investigation pattern:

`top level -> nested forms/frames -> popup windows -> named control/dataset -> screenshot only if still unclear`

## 5. Popups are windows, not normal pages

Observed: GMES Notice messages behave as floating child windows and can be identified/closed by popup type and their close control.

Rule:

- treat blocking popups as a class of runtime state, not one hardcoded popup name;
- close the intended close control by type/relationship;
- do not close business work screens accidentally.

## 6. A single popup check races the application

Observed: login appeared successful, then the Notice popup arrived several seconds later and blocked all later actions. One immediate popup check found nothing.

Fix proven locally: watch for popup appearance, close it, then continue observing until several consecutive quiet rounds occur.

Rule:

A critical transition is:

`apparent success -> observation window -> delayed side effects handled -> quiet/stable rounds -> final success`

Never assume “none open right now” means “none are coming.”

## 7. Document readyState is not Nexacro readiness

Observed: the browser document reported complete while Nexacro was still downloading/building the actual application UI.

A raw element-count heuristic also failed: the count crossed the threshold while the page was still effectively blank for the next business action.

Fix: wait for a known semantic condition:

- already signed-in session marker, or
- known login control such as the AD SSO button.

Rule:

Do not use `readyState == complete`, arbitrary DOM size, or fixed sleeps as proof of application readiness.

## 8. Readiness belongs to the next business action

The useful definition of readiness is not “page loaded.” It is:

`the exact prerequisite needed by the next step exists and is actionable`

Examples:

- login step ready -> login control/session marker exists;
- report step ready -> filter/report controls exist;
- post-query ready -> real result data is present and settled;
- post-login stable -> delayed blockers are gone.

## 9. Saved credentials must be encrypted and user-bound

Validated local behavior: credentials were stored encrypted using the Windows account context, in the user's local application data area, and were not printed or written in plaintext.

Rule:

- never hardcode credentials;
- never put them in Git, logs, docs, command history, screenshots, or generated test data;
- use an OS-protected credential mechanism;
- when interactive terminal input is unavailable, a small local dialog is acceptable if it masks the password and saves only through the protected store.

## 10. Cold-start testing is mandatory for unattended automation

A realistic unattended test was performed by clearing the useful session state, shutting down the browser, and running the login path as if nobody were present at night.

Rule:

Do not call a login workflow production-ready until it passes a true cold start without accidental help from an already-open session, existing window, or human timing gaps.

## 11. Manual step-by-step success can hide automation races

The human pause between commands can accidentally give the application enough time to settle. A fully chained script removes that accidental delay and exposes real synchronization bugs.

Rule:

Test both:

- focused steps during development;
- full end-to-end chained unattended execution before release.

## 12. Division VD is a business prerequisite, not cosmetic UI state

Observed: Production Plan by Order(Line) produced a search-criteria error without the required Division selection. With `VD` selected, the intended report populated.

Validated org-tree evidence included a row representing `VD` with an internal path key observed as `^V^C712A^T001`.

Rule:

- encode required business criteria explicitly in the workflow contract;
- never assume defaults visible from a previous user session;
- verify the UI/business header reflects the intended selection before running the query.

## 13. Direct model/dataset manipulation can be stronger than clicking a tree

Observed: the org tree's underlying Nexacro dataset exposed the selection state, including a `_checked`-style field, and programmatically updating the relevant row caused the UI to reflect Division VD.

Rule:

If internal model manipulation is used:

1. prove the model is authoritative for the UI;
2. verify the visible UI followed the change;
3. revalidate after upgrades;
4. retain a safer UI-level fallback when practical.

Do not silently mutate internal state merely because it is reachable.

## 14. Visible grids can lie about total accessible data

Observed: GMES virtualizes the grid and builds only visible rows. Reading rendered row elements would return only a small portion of a large report.

Rule:

Never equate rendered grid rows with report completeness until virtualization behavior is understood.

Investigate, in order:

`authoritative Nexacro dataset/model -> network/result object -> complete in-memory table -> visible grid`

## 15. The real result data is reachable from named datasets

Observed: the application kept complete result data in named in-memory datasets, including live filter values and many result columns.

This enabled machine-readable extraction without relying on Excel dialogs.

Rule:

Use direct dataset extraction only after proving:

- dataset identity;
- business filter identity;
- row semantics;
- filler/hidden row behavior;
- relationship to the visible business count.

## 16. “Query finished” cannot be inferred from temporary zero rows

Observed failure: GMES clears the result dataset immediately after Inquiry, then refills it when the server responds. A first implementation saw a stable zero and incorrectly declared the query complete while hundreds of rows were still on the way.

Fix:

- do not settle on zero immediately;
- give all-zero runs a generous grace period;
- when rows become positive, require a stable count for several checks;
- also detect blocking/error dialogs;
- prefer a semantic server/query-completion signal if one is later discovered.

Rule:

Temporary empty state during an asynchronous refresh means `UNKNOWN/WAITING`, not automatically `NO DATA`.

## 17. Avoid fixed sleeps for queries

Report size varies. A small day and a large day can have very different server times.

Rule:

Use condition polling with a generous safety cap. Exit as soon as the real condition is satisfied. A large timeout cap does not make fast successful operations slower.

## 18. One “busy” hypothesis was wrong and was corrected

During investigation, a field was initially mistaken for a busy/query signal because of a misleading name containing `MaskEdit`. It was actually a date field.

Rule:

Every runtime discovery must pass:

`hypothesis -> attempt to falsify -> evidence -> confidence -> adoption`

Do not promote a plausible-looking internal field to production logic without proof.

Recommended confidence labels:

- VERIFIED
- STRONG OBSERVATION
- INFERRED
- UNKNOWN

## 19. Strong completion can require combined evidence

When no single trusted “query complete” flag exists, combine independent signals such as:

- expected dataset becomes non-empty;
- count stops changing over several rounds;
- no error popup is present;
- network/activity signal is quiet if available;
- visible total matches expected business interpretation.

Rule:

Critical success may be a predicate over several facts, not one boolean.

## 20. Underlying row count can legitimately exceed visible business total

Observed: the internal dataset contained extra filler rows with blank business keys such as PO/master-line fields. The visible grid excluded them.

A validated example showed that removing filler rows brought the machine-readable data count into agreement with the GMES visible Total.

Rule:

Do not “fix” a count difference by arbitrary trimming. Identify the business rule that separates real rows from framework/filler rows, then prove the reconciliation.

## 21. Data trust gate is independent from automation success

A workflow can click every button correctly and still deliver wrong data.

Before trusting output, reconcile:

- requested date;
- Division/filters;
- visible business total;
- underlying dataset rows;
- filler/exclusion rule;
- delivered file/readable rows where possible.

If the difference is unexplained, stop release.

## 22. GMES official Excel export is a dialog flow

Observed: the Excel toolbar icon opens a `Save to Excel` popup rather than immediately downloading a file.

Observed flow:

`click Excel icon -> Save to Excel popup -> target grid already selected -> single-file option -> OK -> browser download`

Rule:

Model export as a small workflow with its own readiness, confirmation, download wait, and file-delivery verification.

## 23. Official GMES export naming can be captured and normalized

Observed official naming resembled:

`Production Plan by Order(Line)_YYYYMMDDHHMMSS.xlsx`

The automation may normalize separators while preserving report/date/time semantics if the user requires a custom naming convention.

Never rename before confirming the download has fully completed.

## 24. Browser download behavior can be connection-scoped

Observed during local testing: a download redirect/configuration applied through one CDP connection did not remain effective after that connection closed, causing a file to land in the default Downloads folder instead of the target Data Hub path.

Rule:

Treat browser download policy as runtime/session state. Keep or reapply it for the connection/target lifecycle that performs the download, then verify the actual delivered path.

## 25. Official exported workbook is NASCA DRM-protected

Observed: the downloaded GMES workbook began with a NASCA DRM marker and could open in the corporate Excel environment but was not a normal readable XLSX byte stream for Python/openpyxl/pandas or generic downstream processing.

Rule:

File existence + `.xlsx` extension does not prove machine readability.

For Data Hub scenarios, distinguish:

- **official GMES file** — authoritative manual-equivalent export, DRM protected;
- **machine-readable data copy** — generated directly from the verified dataset, e.g. CSV.

Do not remove the official file if the business requires it.

## 26. Dual-output strategy is useful when official output is DRM protected

Validated approach:

1. download the official GMES workbook for human/audit/manual equivalence;
2. create a separate machine-readable CSV from the verified in-memory dataset;
3. apply the proven filler-row exclusion rule so the CSV count matches the visible business total;
4. name both with the same run timestamp/lineage.

Rule:

Make the relationship between official and machine-readable output explicit. Never pretend the generated CSV is literally the same file as the official workbook.

## 27. Full direct data extraction can eliminate fragile UI export steps, but keep the official path when required

Reading the trusted dataset can be faster and more reliable than driving Excel dialogs, especially for downstream automation. However, the user may require the exact GMES workbook.

Rule:

Choose output path by business need:

- manual-equivalent evidence/format -> official GMES export;
- downstream machine processing -> verified direct dataset output;
- high-value workflow -> often deliver both.

## 28. Screen search can eliminate long menu traversal

Observed: GMES provides a search box that can jump to a screen by ScreenID.

Rule:

Once proven, direct screen navigation should be preferred over replaying every menu click. Fewer transitions mean fewer failure surfaces.

Keep the human menu path documented for explainability and fallback.

## 29. Discovery should escalate, not repeat the same failed assumption

When a control is not found:

`top-level inspection failed -> inspect nested form/frame -> inspect Nexacro component model -> inspect dataset -> inspect network/runtime -> screenshot/visual fallback`

Rule:

Do not repeat the same selector with different guesses. Move to a deeper evidence layer and record why the previous layer failed.

## 30. Generalize only after one real case is proven

The best reusable helpers in the session emerged after observing a concrete failure, for example generic child-popup handling after a real Notice popup was found.

Rule:

`real case -> evidence -> minimal solution -> prove -> extract reusable helper -> prove again`

Avoid premature framework building.

# Production Plan by Order(Line) validated profile

Business target:

- Report: Production Plan by Order(Line)
- Division: `VD`
- Typical unattended date behavior: yesterday, unless explicitly overridden
- Destination used in the local session: a GMES folder under the project's Data Hub area
- Official output: GMES Excel workbook
- Optional output: clean CSV from verified dataset

Validated behavior from one completed run:

- query returned a visible business total that matched the cleaned real-row count after filler rows were excluded;
- official GMES Excel downloaded successfully;
- machine-readable CSV contained the reconciled real rows and broad result columns;
- official Excel was DRM protected.

Numbers observed during investigation varied by date/session and must never be hardcoded as expectations. Count matching logic is the invariant, not a specific row number.

# Recommended execution-state model

For any unattended GMES step:

- `PENDING`
- `READY`
- `RUNNING`
- `WAITING`
- `STABILIZING`
- `SUCCEEDED`
- `FAILED`
- `CANCELED`

Each step should define:

- prerequisites;
- named inputs;
- named outputs;
- start condition;
- semantic readiness condition;
- success predicate;
- delayed-effect/stability predicate;
- failure predicate;
- timeout/safety cap;
- retry policy;
- idempotency/duplicate-side-effect protection;
- evidence.

# Verification matrix

## Login

Prove:

- cold browser/session path;
- saved credential retrieval without plaintext disclosure;
- successful sign-in marker;
- semantic app readiness;
- delayed popup handling;
- stable post-login state.

## Report navigation

Prove:

- intended screen code/business title;
- no stale/wrong screen;
- required filters present.

## Query

Prove:

- date actually changed in UI/model;
- Division VD reflected in business state;
- query did not terminate on transient zero;
- result count stabilizes;
- no error dialog remains.

## Data

Prove:

- full dataset, not only virtualized visible rows;
- business-row rule;
- visible total reconciliation;
- expected columns/schema sanity.

## Export

Prove:

- correct Save to Excel popup;
- correct target grid/single-file option;
- completed download;
- actual final destination;
- official file size/non-empty;
- DRM status;
- optional machine-readable copy count.

# Failure handling principles

If a GMES step fails:

1. capture safe evidence;
2. locate first divergence, not final symptom;
3. inspect actual current screen/form/dataset state;
4. distinguish timeout from wrong-screen from missing-business-criteria from blocker-popup from data mismatch;
5. fix the smallest responsible layer;
6. rerun focused reproduction;
7. rerun full cold-start journey if the change affects sequencing/readiness;
8. update this skill and `HISTORY.md`.

# Never do these

- hardcode passwords;
- log credentials;
- depend on fixed window coordinates;
- trust generated screen suffixes without proof;
- use raw DOM row count as report row count on a virtualized grid;
- use `readyState` as Nexacro readiness;
- use a stable zero dataset as immediate “no data” proof;
- check for delayed popups only once;
- declare data correct because export completed;
- trust an `.xlsx` extension as proof of readable workbook content;
- silently drop rows to make counts match;
- rebuild validated local GMES code from this document if the real local files still exist elsewhere;
- leave a new discovery only in chat.

# Mandatory update template

Append or revise the relevant section whenever new knowledge is proven:

```text
DATE:
AREA:
OBSERVED FAILURE/DISCOVERY:
ROOT CAUSE:
SOLUTION:
WHY IT WORKS:
EVIDENCE:
AFFECTED FILES:
REUSABLE RULE:
REGRESSION PROOF:
STATUS: VERIFIED / NEEDS REVALIDATION
RELATED HISTORY ENTRY:
```

The skill is part of the product. Keeping it fresh is part of completing the code change.
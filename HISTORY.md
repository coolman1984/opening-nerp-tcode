# HISTORY.md — Engineering Problem / Solution History

Purpose: preserve hard-earned runtime knowledge so future agents do not solve the same failures from zero.

Rules:

- append meaningful incidents/discoveries;
- never delete an old entry because the implementation changed;
- if a later fix supersedes an old one, link it;
- never store credentials, tokens, private data, or sensitive screenshots;
- every serious issue should end in a reusable rule and, where practical, a regression check.

---

## NERP baseline history

The root `SKILL.md` contains the detailed NERP/SAP gotcha history and remains the authoritative reusable NERP skill. Important families already learned include:

- corporate proxy blocking localhost CDP unless `NO_PROXY` is set;
- Chrome single-instance/debug-port problems;
- CDP websocket origin rejection;
- stale websocket connections during long waits;
- synthetic DOM `click()` not triggering real SAP behavior;
- WebGUI living in a separate cross-origin CDP target;
- unstable SAP field IDs and stable semantic labels;
- top-level-only screenshot limitations;
- text lookup selecting hidden/ancestor elements;
- multiple different SAP Excel export flows;
- stale iframe/tab targets;
- dialog rendering delays;
- focus-only synthetic clicks;
- stale session restoration after force-killing Chrome;
- fixed sleeps failing on variable server/network time;
- automated chaining exposing races hidden by human pauses.

Future NERP changes must update `SKILL.md` and add a history entry here when the lesson is significant.

---

# GMES / Nexacro discovery and stabilization history — 2026-09-09

## GMES-001 — Prove whether GMES is automatable semantically

**Symptom / question**

Unknown whether Nexacro would require blind coordinate/image automation.

**Evidence**

Runtime inspection showed real page/form/control structures and stable meaningful component names.

**Conclusion**

GMES can be automated primarily through semantic runtime inspection rather than coordinate clicking.

**Reusable rule**

Prefer semantic screen/form/control identity first; coordinates are last resort.

**Skill link**

`GMES_SKILL.md` sections 1-3.

---

## GMES-002 — Login automation must handle actual SSO behavior

**Symptom**

AD SSO was initially treated as if Windows sign-on would always be automatic.

**Observed reality**

The environment could still present a credentials flow requiring the user's Knox/GMES identity.

**Solution**

Support saved protected credentials and explicit login-state detection rather than assuming seamless SSO.

**Reusable rule**

Authentication behavior must be observed in the target environment; never infer it from the button label.

---

## GMES-003 — Secure unattended credential storage

**Need**

Night automation must log in when the user is absent.

**Risk**

Plaintext credentials in scripts/config/logs are unacceptable.

**Solution proven locally**

A Windows-account-bound encrypted credential store was created under the user's local application data. Password input was masked. A small dialog fallback was added when terminal keyboard input was unavailable.

**Verification**

Credentials could be saved and loaded only through the local protected mechanism; plaintext was not written to source/log output.

**Reusable rule**

Secrets are runtime protected data, never repository content.

---

## GMES-004 — Top-level inspection missed a Notice popup

**Symptom**

The user could see the popup, but the first inspection tool did not find it.

**Root cause**

The Notice lived in a nested Nexacro form/frame/window rather than the top-level structure being searched.

**Solution**

Build a deeper search tool that walks inner forms/frames/components and identifies popup windows and close controls.

**Reusable rule**

“Not found at top level” is not “does not exist.” Escalate discovery layers.

---

## GMES-005 — Popup handling generalized beyond one message

**Symptom**

Hardcoding one popup name would fail on future notices.

**Solution**

Identify floating child windows by type/structure and close the appropriate X/close control. Keep the logic generic enough to handle new notices while avoiding business work screens.

**Reusable rule**

Generalize only after a real case is understood and proven.

---

## GMES-006 — False readiness from document state / element count

**Symptom**

Cold-start login failed because the automation searched for the login control while the Nexacro UI was still effectively blank.

**First implementation flaw**

Readiness used document completion / a raw number-of-elements threshold.

**Root cause**

Nexacro finishes building the meaningful UI well after the browser document says complete. Raw element count crossed the threshold before the intended controls existed.

**Fix**

Wait for one of two semantic states:

- known signed-in session marker; or
- known login control.

**Proof**

Cold-start login proceeded only when a meaningful control/session state existed.

**Reusable rule**

Readiness must be defined by the next business action, not generic browser state.

---

## GMES-007 — Login appeared complete before delayed Notice popup arrived

**Symptom**

Full unattended login succeeded, but the Notice popup later blocked subsequent steps.

**First implementation flaw**

Popup detection ran once immediately after sign-in.

**Root cause**

The application creates the Notice asynchronously several seconds after the username/session marker appears.

**Fix**

Add a popup observation loop:

- wait for first popup within an appearance window;
- close it;
- extend observation briefly for queued popups;
- require several consecutive quiet rounds before advancing.

**Reusable rule**

Critical success requires a post-success stabilization window when delayed side effects are possible.

---

## GMES-008 — Stable business screen identity vs changing window IDs

**Symptom**

Generated inquiry/window identifiers changed between opens.

**Risk**

Hardcoded IDs would work once and silently fail later.

**Discovery**

The business breadcrumb exposes stable screen codes. For Production Plan by Order(Line), observed codes included:

- `P1112UM00`
- `P1112WF00`
- `P1112WM00`

**Fix**

Target semantic screen/form codes and labels, not ephemeral generated window IDs.

**Reusable rule**

Stable meaning beats generated identity.

---

## GMES-009 — Direct ScreenID navigation is available

**Discovery**

The GMES search box can jump to a screen by ScreenID.

**Benefit**

Eliminates long menu replay and reduces transition failure surfaces.

**Reusable rule**

When the system exposes a stable direct-address mechanism, prefer it over recreating human menu traversal, while retaining the breadcrumb/menu path as fallback/documentation.

---

## GMES-010 — Missing Division VD caused the business query failure

**Symptom**

Production Plan by Order(Line) produced “Select Search Criteria” / no intended result.

**User correction**

Division VD had not been selected.

**Discovery**

The org tree dataset exposed VD and selection state. Selecting it made the business header reflect `Org VD` and allowed the intended query.

**Reusable rule**

Business prerequisites are part of the workflow contract. Do not assume UI defaults from a previous session.

---

## GMES-011 — Internal dataset state can drive the UI

**Discovery**

The org tree's Nexacro dataset exposed the VD row and a selection/check state. Programmatic selection updated the UI.

**Engineering consequence**

Some reliable operations can be performed through the application model instead of fragile tree clicking.

**Guardrail**

Use internal model mutation only after proving it is authoritative and verifying the visible business state follows it.

---

## GMES-012 — Virtualized grid would silently truncate extraction

**Symptom / risk**

Only currently rendered rows exist as visible grid elements. A large report could appear to contain only ~screenful data if scraped visually.

**Root cause**

Nexacro virtualizes grid rendering.

**Discovery**

The complete result set exists in named in-memory datasets.

**Fix**

Read the verified dataset/model instead of rendered row elements when full machine-readable extraction is required.

**Reusable rule**

Never equate visible rows with total dataset rows until virtualization is understood.

---

## GMES-013 — Wrong “busy” signal hypothesis

**Symptom**

An internal field was initially interpreted as a query busy/completion signal.

**Root cause**

A misleading name caused a false interpretation; it was actually related to a date/mask control.

**Resolution**

The hypothesis was explicitly withdrawn rather than buried.

**Reusable rule**

Use `hypothesis -> falsification attempt -> evidence -> confidence -> adoption`. A plausible name is not proof.

---

## GMES-014 — Query falsely completed at zero rows

**Symptom**

A report was declared complete with zero rows while hundreds of rows were still on the way.

**Root cause**

When Inquiry starts, Nexacro clears the existing result dataset to zero and refills it only after the server round trip. Several stable zero readings were mistaken for completion.

**Fix**

- treat early zero as `WAITING/UNKNOWN`;
- give all-zero state a generous grace period;
- once rows are positive, require count stability across multiple checks;
- detect dialogs/errors separately;
- keep a generous overall safety cap.

**Reusable rule**

A temporary empty state during async refresh is not “no data.”

---

## GMES-015 — Dataset row total did not equal visible business total

**Symptom**

Internal row count exceeded the GMES screen Total.

**Risk**

Direct extraction could silently inflate data.

**Investigation**

The difference was traced to filler rows with blank key business fields such as PO/master-line values that the visible grid excludes.

**Proof**

Dropping rows according to the validated business-key rule reconciled the clean data count to the visible GMES Total in the tested run.

**Reusable rule**

Do not trim data merely to make counts match. Explain the semantic difference and prove the exclusion rule.

---

## GMES-016 — Automation success and data correctness are separate gates

**Discovery**

It was possible for navigation/query/export mechanics to succeed while row-count interpretation remained uncertain.

**Decision**

Do not trust production output until visible business total, filters, underlying data, and cleaned output are reconciled.

**Reusable rule**

`workflow success != data trust`.

---

## GMES-017 — Official Excel icon opens a Save to Excel dialog

**Unknown**

Whether clicking the Excel icon downloaded directly or opened another flow.

**Probe result**

The icon opened a `Save to Excel` dialog with the target grid already selected and a single-file option.

**Fix / workflow**

Model export explicitly as:

`Excel icon -> Save to Excel popup -> confirm options -> OK -> wait for download -> verify destination`

**Reusable rule**

Probe unknown export behavior before embedding it in the nightly job.

---

## GMES-018 — Download initially landed in the wrong folder

**Symptom**

The browser download landed in the default Downloads folder instead of the Data Hub target.

**Root cause**

The tested browser download override/redirect was tied to the relevant CDP connection/session lifecycle and was not effective after the configuring connection ended.

**Fix**

Maintain or reapply download behavior through the actual export lifecycle, then verify the final path instead of assuming it.

**Reusable rule**

Browser policy is runtime state. Verify the side effect where it actually lands.

---

## GMES-019 — Official XLSX is NASCA DRM protected

**Symptom**

The downloaded `.xlsx` existed and could open in corporate Excel, but programmatic readers could not parse it as a normal workbook.

**Evidence**

The file bytes contained a NASCA DRM marker.

**Consequence**

The official file is suitable for human/manual-equivalent use in the protected environment but not generic downstream parsing.

**Reusable rule**

File extension and successful download do not prove machine readability.

---

## GMES-020 — Dual-output Data Hub strategy

**Need**

Preserve the official GMES export while also enabling downstream processing.

**Solution**

Deliver:

1. official GMES Excel export, DRM protected;
2. separate machine-readable CSV from the verified in-memory dataset.

Apply the proven filler-row rule to the CSV so its row count reconciles with the visible business total.

**Reusable rule**

When official output is protected, provide a clearly labeled machine-readable companion rather than pretending to decrypt or modify the official file.

---

## GMES-021 — Full cold-start Production Plan job proven locally

**Scenario**

Production Plan by Order(Line), Division VD, prior-day plan, unattended-style execution.

**Validated chain**

`start -> login -> semantic readiness -> delayed-popup stabilization -> set date -> set VD -> Inquiry -> wait for real rows/stability -> reconcile -> official Excel export -> Data Hub delivery -> clean CSV companion`

**Observed result**

The cleaned data count matched the screen's visible business Total in the tested run. Exact row numbers are date-dependent and must not be hardcoded.

**Reusable rule**

Release the behavior, not one day's numbers.

---

# Mandatory future history template

```text
## <ID> — <short title>
DATE:
AFFECTED VERSION/COMMIT:
JOURNEY:
SYMPTOM:
FIRST DIVERGENCE:
ROOT CAUSE:
AFFECTED COMPONENTS/STATE:
SOLUTION:
WHY IT WORKS:
VERIFICATION:
REGRESSION PROOF:
REUSABLE RULE:
SKILL UPDATED:
GUARDRAIL ADDED:
SUPERSEDES / SUPERSEDED BY:
```

If an incident changes architecture, state ownership, external contracts, or core sequencing, update `PROJECT_EYE.md` too.
# The MR.Park weekly reports: what the manager asked for, how it changed, how the tool delivers it

The knowledge behind two weekly benchmark reports, and the pipeline that feeds them. Read it before you change
a recording, a batch, or either dashboard. It is written from the manager's three e-mails, his workbooks, and
what was proven against them (HISTORY.md Phase 130). It ships inside GMES Automation: the "Weekly reports
guide" link in the window, and `WEEKLY_REPORTS.md` beside the .exe in the server package.

| | |
|---|---|
| Asked by | the manager, Business Management, SEEG-P ("MR.Park" in the project names) |
| For | the project owner (AX), and the production / management mailing lists |
| Reports | **Tact Time Comparison** (SEEG-P vs other subsidiaries) and **In-house Weekly Operation** (SEEG-P vs SEDA-P(M)) |
| Dashboards | `MR.Park\Tact Time Comparation\SubsidiaryComparison` (both reports) and `MR.Park\Inhouse Weekly Operation\InhouseOperation` (In-house only) |
| Data hub | `\\106.139.71.19\DataHub Shared Folder\Management\AX` - the dashboards watch it |
| G-MES | **HQ G-MES** (`--site hq`, gmes4, "MES HQ"): it lists every factory (SEEG-P, SEH-P, SEHC, SEDA-P(M)) |
| Weekly batch | `weekly_hq` on HQ: Monday 10:00, `lastweek`, CSV, pinned to the AX share |

---

## 1. The e-mails, in order

| Date | E-mail | What it established |
|---|---|---|
| 2026-09-27 11:20 | "Comparsion with Other Subsidiaries" (to the owner and the AX team) | "Let's try to make through AI." Two reports: (1) In-house operation vs SEDA-P(M); (2) Tact time: **Main vs SEHC, SMD vs SEH, Press / Press Coat / EPS vs SEDA-P(M)**. Attached: `Tact Time Comparsion_W39.xlsx`, `Inhouse Operation Comparsion_W39.xlsx`, a W38 AI report (`Tact_Time_Comparison_Report_W38.md`) and its HTML dashboard. Rule set 1. |
| 2026-10-06 10:04 | "[W40] Inhouse Weekly Operation Status (Comparsion with SEDA)" | The In-house report as sent to management: three tables (On Qty Prod. Rate, Operation Efficiency by W/C, Loss Detail by Line), months Jan-Aug then W36-W40. Headline: Press operation efficiency recovered to its target; the EPS early production rate is still high. Attached `Inhouse Operation Comparsion_W40.xlsx`. |
| 2026-10-06 10:12 | "[W40] Tact Time Comparation with Other Subsidiary" | The tact report: Main SEHC (Basic & Inch), SMD SEH (Project & Inch), in-house SEDA (Material Code); W40 plan, models of 100 units or more. Insight numbers: the Disadvantage share over three weeks, the volume-weighted index, MAIN and SMD indexes. |
| 2026-10-06 14:20 | "FW: [W40] Tact Time Comparation ..." to the owner | **"I changed source screen (widget screen) and rule a little."** Attached `Tact Time Comparsion_W40_F.xlsx` (the final), `SEEG-P_Tact_Time_Dashboard_W40.html` and `SEEG-P_Tact_Time_Dashboard_Prompt.md` (his exact rules). Rule set 2. |

The e-mails live in the Knox Portal web mail. Saved copies are NASCA-DRM files: only Outlook (a DRM-approved
program) can open them - `MR.Park\Tact Time Comparation\.claude\skills\subsidiary-comparison\scripts\extract_email.ps1`.
Saved under each project's `Reference Material\`.

**The 10:12 text and the 14:20 workbook disagree.** The 10:12 numbers were made with rule set 1 ("Basic & Inch");
the 14:20 workbook `_F` and his own W40 dashboard use rule set 2 and give different values for every one of those
insight numbers (no tested definition reproduces the 10:12 text from `_F`). The dashboards follow the final workbook. Ask him which one is final if anyone quotes the e-mail.

---

## 2. Tact Time Comparison

### 2.1 Source: P1112 "Production Plan by Order(Line)"

| | Rule set 1 (W38, W39 workbooks) | Rule set 2 (W40 `_F`, current) |
|---|---|---|
| G-MES screen | P1112UM00 Master Prod. Plan, 112 columns | **P1112WM01 Detail Prod. Plan** (the "widget screen"), 111 columns, with Work Center and **Shift** |
| Factories / groups | SEEG Prod.1 + Prod.2, SEH SMD/PBA, SEHC VD Main + LCM, SEDA Component | same factories; SEHC only parts **VD MAIN(1D) / VD MAIN(3D)** |
| PO type | Normal PO | **Normal P/O, picked in G-MES** (PO Type picker), one group per query |
| GBM | VD only | no GBM rule (his own SEDA rows are GBM MX and count) |
| Week | `=WEEKNUM(PlanDate-1)`: Monday to Sunday | same |
| Target lookup | by **Master Line** (Master!B:J) | by **Work Center** (Master!B:J). Lines missing in Master (SEEG-P M06, CP01, SEH-P S12, SEDA VPA01) get #N/A |
| Combine MAIN | Basic Model & Inch | **Project & Inch & Shift** (one PO on two shifts = two rows, the orange cells) |
| Combine SMD | Project & Inch | Project & Inch |
| Combine PRESS / PRESS COAT / EPS | Model Code | Model Code |
| Peer | MAIN -> SEHC, SMD -> SEH-P, PRESS / PRESS COAT / EPS -> SEDA-P(M); base always SEEG-P | same |

### 2.2 Calculation (rule set 2)

1. **1st Sum**: Plan Q'ty by process x combine x factory over **Target = Yes** rows of the week.
2. **2nd Target** = `IF(AND(COUNT(C:F)=2, C>=100, MIN(C:F)>=100),"Yes","No")`: exactly two factories, SEEG-P one of
   them, both at least 100 units.
3. **2nd Sum**: Fixed TT(sec) by process x combine x inch x factory over **every row of a 2nd-Target combine** -
   Target is NOT filtered again (a #N/A-Target row of a qualifying combine still counts).
   - **TT average** (default, = Excel) and **TT minimum** (his dashboard's second view).
4. **TT Index** (Comparsion) = SEEG-P TT / peer TT. **Lower is better.**
5. **Range**, 6 bands, upper bound inclusive, ratio rounded to 9 decimals first:

   | Range | Verdict | Key |
   |---|---|---|
   | <= 75% (75%↓) | Advantage (우위) | good |
   | <= 90% (75~90%) | Advantage | good |
   | <= 100% (90~100%) | Slight advantage (소폭 우위) | sgood |
   | <= 110% (100~110%) | Slight disadvantage (소폭 열세) | srisk |
   | <= 125% (110~125%) | Disadvantage (열세) | risk |
   | above (125%↑) | Disadvantage | risk |

   Rule set 1 had 5 bands (70 / 90 / 110 / 130%) and 3 verdicts (Advantage <= 90%, Parity <= 110%, Disadvantage).
6. **Dashboard measures**: top-volume line (the Master Line with the most Plan Q'ty), previous-week index and
   Δ WoW (%p; NEW when the combine was not compared last week), **volume-weighted index** = Σ(index x SEEG-P qty) /
   Σ SEEG-P qty, 3-week verdict trend (the "Disadvantage share" counts Disadvantage only), **Gap index** =
   (index - 1) x SEEG-P qty for the improvement priority.

**Proven:** the Tact app reproduces the W40 `_F` workbook (43/43 combines, ratio and Range) and his dashboard on
both TT bases. Our HQ downloads of W38, W39 and W40 equal his raw data row for row (several thousand rows a week, Fixed
TT identical); only SEDA rows (no access yet) and the SEHC parts he leaves out differ.

---

## 3. In-house Weekly Operation (SEEG-P vs SEDA-P(M))

### 3.1 Sources

| Sheet | G-MES | Our recording (HQ) | What is used |
|---|---|---|---|
| Plan Progress | **P1122UM00** | Production 2, Weekly, Line, week typed `2026-W40` (dashed), grid `grdProd`, CSV | Plan Q'ty, Plan Result, Result Total, Pre-Build Result, ACO/SL, Defect per line / process |
| Operation Analysis | **R3220UM00** Line view + **R3225WM00** Part view | `rdoSearchType=Line` / `=Part`, week typed `2026W40` (no dash), `--period-column` | **Time Operation Rate(New)(%)** = his "operation efficiency"; lines PB01-PB04 from the Line view, process totals from the Part view (PRESS BARE, INJ BARE Part, EPS Part) |
| Loss Analysis | **R2400UM00** | Production 2, typed days, `--verify lossYmd`, CSV (the grid shown in Detail mode) | one row per loss event; minutes by line / process / loss item |

Subsidiary: P1122 Team/Group "VD / Production 2" = SEEG-P, "Production Team / Component" = SEDA-P(M); R3220
Division "Production 2" / "Component"; R2400 Plant prefix `[SEEG]` / `[SEDA]`.

**A process total cannot be computed from its lines** (a share of operating time the lines do not show; mean and
production-weighted mean both differ from his) - that is why the Part view is downloaded too.

### 3.2 Metrics and targets (his conditional formatting, Summary_1)

| Metric | Formula | Red below |
|---|---|---|
| On Qty Prod. Rate (정량 생산 지수) | Plan Result / Plan Q'ty | 90% |
| TTL Qty Prod. Rate | Result Total / Plan Q'ty | 98% |
| Operation Efficiency (라인 가동율) | R3220 Time Operation Rate(New) / 100 | Press 80%, INJ / EPS 90% |
| Early production rate (선행생산 비율) | Pre-Build Result / Plan Q'ty | alert above 20% (the dashboards' default; his W40 headline names EPS) |

Loss tables: Press by line (PB01-PB04) and INJ / EPS by process for the week, by loss item; recent 4 weeks.

### 3.3 What changed between the W39 and the W40 workbook

- Summary_1 widened (A1:P58 -> A1:U58): months Jan-Aug, then the last five weeks.
- The Operation Analysis sheet was re-laid out (his formulas moved from OA rows 2 / 19 / 22 / 26 to 3 / 10 / 16 / 19).
- **The row swap survived the re-layout** (next section).

### 3.4 Proven against his W40 e-mail (our G-MES files -> the In-house dashboard)

Every SEEG-P cell of his tables for W38 and W40 equals ours, except two, each explained and asserted by a test
(`GmesFilesGiveTheManagersEmailTables` in both apps):

| Cell | His e-mail | Ours | Why |
|---|---|---|---|
| W40 Press PB01 On-Qty | his value | 1 point higher | one PB01 order was "Planned" when he pulled and no longer exists in G-MES; it produced nothing (Plan Result equal), only Plan Q'ty differs. The Press Total moves with it |
| EPS SEEG-P operation efficiency | the same value every week | the R3220 value of each week | **his Summary_1 rows are swapped**: "INJ SEDA-P(M)" reads EPS SEEG-P's R3220 row and "EPS SEEG-P" reads INJ SEDA-P(M)'s. His e-mail's INJ SEDA-P(M) cell is the true EPS SEEG-P value |

W40 loss minutes equal his e-mail exactly (Press by line PB01-PB04, INJECTION, EPS), and his headline's EPS early
production rate comes out the same. The exact values are asserted by the dashboards' tests (local projects, not
in this public repository: the figures are the company's).

---

## 4. Defects in the manager's workbooks (found while matching; tell him)

| # | Where | What | Effect |
|---|---|---|---|
| 1 | In-house Summary_1, operation efficiency rows (W39 and W40) | INJ SEDA-P(M) and EPS SEEG-P read each other's R3220 row | the e-mail shows EPS SEEG-P with INJ SEDA-P(M)'s value every week. The dashboards read R3220 directly |
| 2 | In-house Loss Analysis (W39 and W40 workbooks) | **W38 PRESS pasted twice for 14-17 Sep**: hundreds of SEEG-P and SEDA-P(M) rows are exact copies (two downloads joined; his row numbers restart) | his W38 Press loss is overstated by about a third. G-MES lists each event once. Both dashboards now warn when a loss file holds copied rows |
| 3 | Tact Summary trend | the "Total" row is typed by hand (W39 shows 74, true 70); the third week's header says W39 for W40 | quote the dashboard, not the trend table |
| 4 | Tact e-mail 10:12 | numbers from rule set 1, workbook `_F` is rule set 2 | see section 1 |
| 5 | Tact Master | Work Centers M06, CP01, S12, VPA01 missing | #N/A Target: they don't count for the 100-unit test but do count in qualifying combines' TT |

---

## 5. The pipeline

```
Monday 10:00  Task Scheduler -> GMES_Batch_weekly_hq.hq (this PC) / GMES_App_weekly_hq.hq (the server window)
              gmes_batch.py run --batch weekly_hq --unattended --site hq   (lastweek = the Monday-Sunday before)
                P1112WM01  4 queries (Production 1 | Production 2 | SMD/PBA | VD MAIN), Normal P/O, Shift, CSV
                P1122UM00  week typed 2026-Wnn            R2400UM00  the 7 days
                R3220UM00  Line view, 2026Wnn             R3225WM00  Part view, 2026Wnn
              -> one CSV each (the 4 P1112 parts joined into *_all_data.csv) on the AX share
Dashboards    watch the AX share; recognise each file by its columns; a newer file of the same week replaces
              the older one (lines and process totals separately; losses per week and subsidiary)
```

- **Why Monday 10:00**: the Sunday night shift ends 08:00 Monday (a production day is 08:00-08:00), and loss
  events are entered in the morning.
- **Week typing**: the batch re-types the week (`=WEEKNUM(date-1)`) in each screen's own shape: `2026-W41` for
  P1122, `2026W41` for R3220/R3225 (HISTORY 130.7).
- **History**: the dashboards keep every week they imported. Months (Jan-Aug) and weeks before the first batch
  come from his workbooks - import `Inhouse Operation Comparsion_W40.xlsx` and `Tact Time Comparsion_W40_F.xlsx`
  once (they also carry the Tact **Master**, needed for the Target lookup). The weekly batch adds the weeks after.
- **Not yet downloaded**: SEDA-P(M) (access requested - until then every comparison against SEDA uses his
  workbook's SEDA data or shows SEEG-P against the target only) and month columns from September on (a monthly
  pull needs a second recording of P1122 / R3220; to be decided).
- **Losses count only KPI Apply = Y** (or blank), in both dashboards. Every event seen so far is Y.

## 6. Running it on the server (106.139.71.19)

1. On the development PC: `GMES\build_exe.bat`, then `GMES\make_package.bat server` -> `GMES_Automation_server_package.zip`
   (the program, this guide, README, and `seed\` with every recording, batch and record check of SEEG and HQ).
2. On the server: unzip, `Start_GMES.bat`, Account: save the server user's login, Test sign-in once.
3. Top switch **HQ G-MES**, Schedules: `weekly_hq` every Monday 10:00, then **Run now** once and read the report.
4. Remove the schedule from the development PC (`python gmes_batch.py --site hq unschedule weekly_hq`).
5. Both dashboards in server mode (`web-server\Start_*.bat`, ports 8790 / 8791), Data Hub path = the AX share,
   his W40 workbooks imported once for history and the Master.
6. The Windows user stays signed in (lock or disconnect, never sign out).

## 7. Open items

- SEDA-P(M) on HQ G-MES: access requested by the owner.
- Month columns from September: a monthly batch (second recordings) - owner to decide.
- Ask the manager: which W40 tact numbers are final (10:12 text vs `_F`); the swapped rows and the doubled W38
  loss block in his workbooks.

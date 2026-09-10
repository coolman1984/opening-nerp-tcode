# How to use the G-MES tool

A one-page guide. No technical knowledge needed.

---

## Start it

Double-click **`GMES_Workflow.bat`**

That is the whole tool. Everything below happens inside that one window.

---

## Answer 5 questions

```
  1. Which screen?   a UI number, or:  find <words>
     > P1112UM00

  2. Division        e.g. VD, blank = none
     > VD

  3. From date       YYYYMMDD or YYYY-MM-DD, blank = leave as-is
     > 20260909

  4. To date         YYYYMMDD or YYYY-MM-DD, blank = leave as-is
     > 20260909

  5. Any extra filter?   blank = none
     >
```

Then press **Enter** to start.

**Notes**

* Don't know the UI number? Type **`find production plan`** at question 1 and
  it lists the matching screens.
* Dates can be typed either way — `20260909` or `2026-09-09`. The tool shows
  you back what it understood.
* Leave the To date blank and it uses the From date.
* Question 5 is almost always left blank.
* Some screens have no dates at all. Leave question 3 blank; question 4 is
  then skipped automatically.

---

## Watch it work

```
  ╭────────────────────────────────────────────────────────────╮
  │ REPLAYING  ·  P1112UM00 was learned 2026-09-10             │
  ╰────────────────────────────────────────────────────────────╯

    ✓  1  Open the screen ................ Production Plan by Order(Line)
    ✓  2  Read what the screen offers .... 8 bound, 7 unbound
    ✓  3  Find the results table ......... dsMasterProdPlan
    ✓  4  Tick the division .............. VD
    ✓  5  Type the dates in .............. 20260909, 20260909
    ✓  6  Press Inquiry and wait ......... 800 rows
    ✓  7  Dates that came back ........... 20260909
    ✓  8  Download the Excel file ........ 78.9 KB
    ✓  9  Save a readable copy (CSV) ..... 800 rows
    ✓ 10  Remember this screen ........... saved
```

Every line is ticked off only after it actually happened. If something goes
wrong the tool stops there and tells you what it saw.

---

## Where your files go

```
Data Hub Folder\GMES\
```

Two files per run:

| File | What it is |
|---|---|
| `<report>_<date>_<time>.xlsx` | G-MES's own Excel file. Opens in Excel. |
| `<report>_<date>_<time>_data.csv` | The same data as plain text, for Excel formulas, Power BI, or anything else. |

**Why two?** The `.xlsx` from G-MES is protected by Samsung DRM. It opens
fine in Excel on your PC, but no other program can read it. The CSV is there
so the data is usable elsewhere.

**About the row count:** the CSV includes the grey **LINE SUM** and
**PROC SUM** total rows that G-MES adds. So the number of real production
lines is lower than the row count shown.

---

## The two modes: RECORDING and REPLAYING

The tool teaches itself. You do nothing.

**RECORDING** — the first time you use a screen:

```
  RECORDING  ·  P1112UM00 is new
  It will work the screen out as it goes, and remember it if the run succeeds.
```

**REPLAYING** — every time after:

```
  REPLAYING  ·  P1112UM00 was learned 2026-09-10
  It will check the screen still matches, then reuse what it knows.
```

It only remembers a screen if the whole run worked. A failed run teaches it
nothing.

**If G-MES changes a screen**, the tool notices and refuses to use its old
notes:

```
  [!] the screen changed: the 'to' date field 'paramEndDate' is gone
  [!] ignored - reading this screen from scratch
```

It never guesses.

---

## If something goes wrong

**You do not need to close your own Chrome.** The tool opens its own separate
browser. Leave yours alone.

| What you see | What to do |
|---|---|
| A blank white page with a spinner, and the tool waiting | The tool now fixes this itself after 20 seconds. G-MES fills up its own browser storage and then cannot start; the tool clears it and reloads. If it persists, tell me. |
| `the query returned no rows` | Check the division and the dates. A weekend or a holiday often has no plan. |
| `no filter matches ...` | Run `python gmes_report.py describe <UI number>` to see the real filter names |
| `Could not sign in` | Tell me what the window says. **Do not** run `--refresh-profile` — it throws away the saved session that makes sign-in instant. |
| Anything else | A screenshot of the moment it failed is saved in the project folder |

---

## For repeat runs, without the questions

Same thing, one line:

```
gmes run P1112UM00 --division VD --from 20260909 --to 20260909
```

Useful extras:

```
gmes run P1112UM00 --division VD --from 20260909 --to 20260909 --dry-run
        fills everything in but does NOT run the query - safe to try

gmes run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
        refuses to save the file unless the rows really carry that date

gmes run P1112UM00 ... --relearn
        forget what it learned about this screen and read it fresh

python gmes_report.py describe P1112UM00
        show everything a screen offers, and change nothing

python gmes_report.py find "production plan"
        find a UI number
```

In PowerShell type `.\gmes` instead of `gmes`.

---

## Screens already learned

| UI number | Report | Notes |
|---|---|---|
| `P1112UM00` | Production Plan by Order(Line) | division + date range |
| `P1111UM00` | Production Plan by Model | division + date range |
| `M4151UM00` | Work Calendar | division only — this screen has no dates |

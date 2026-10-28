---
name: check-quarter
description: Check one company-quarter in an NSE-pasta data folder against the company's own results announcement (the PDF on NSE) - figures, basis, period and public_at - and say whether pasta's row is right. Use when a row looks wrong (unit_suspect, a crosscheck difference, a growth figure that cannot be true), or to spot-check a sample before trusting a build.
---

# Check a quarter against the results PDF

Reference: `docs/schema.md`, `docs/parser-rules.md`, `docs/point-in-time.md`.

## Input

A data folder `D`, a `SYMBOL` and a quarter end (`YYYY-MM-DD`).

## Steps

1. Find the row(s):

   ```bash
   uv run python -c "import csv,sys; [print(r) for r in csv.DictReader(open('D/out/results.csv')) if r['symbol']=='SYMBOL' and r['period_end']=='YYYY-MM-DD']"
   ```

   Note `basis`, `format`, `version`, `revenue`, `net_profit`, `eps_basic`, `public_at`,
   `public_at_source`, `source_url`. Also read the filing's line in `D/out/filings.csv`.

2. Find the announcement. Open
   `https://www.nseindia.com/companies-listing/corporate-filings-announcements` in a browser
   for the symbol and the days around `public_at`. The results PDF is a `Financial Result
   Updates` item, or (from the March 2025 quarter) an `Outcome of Board Meeting`. Do not
   script requests to NSE outside pasta; one manual look is enough.

3. Read the PDF's statement for the same basis (standalone or consolidated) and the same
   column (the quarter, not the year to date). Convert its unit (lakh, crore, million) to
   rupees. Compare:
   - revenue: "Revenue from operations" (banks: "Interest earned");
   - net profit: consolidated "attributable to owners of the parent", else profit after tax;
   - EPS: basic and diluted, not annualised.

4. Check `public_at`: the announcement's broadcast time on NSE should equal it when
   `public_at_source = announcement`. If pasta used `xbrl` or `xbrl_date`, say whether an
   earlier announcement existed and why it was not matched (its `desc`, its text).

5. Report: the row's values, the PDF's values, each difference and its likely cause
   (unit, basis, wrong context, a restatement in a later version, screener.in rounding or
   minority interest). Quote the PDF line you read. Do not edit `out/` or `raw/`: a wrong
   parse is a code fix with a test on a trimmed fixture (`scripts/trim_fixture.py`).

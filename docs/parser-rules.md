# Parser rules

How one XBRL filing becomes a row (`xbrl.py`, `parse.py`). Pure: the parse step reads only
`raw/`, never the network.

## 1. Which filings are read

- Per company, every filing any cached copy of its two listings ever showed (a filing that
  later leaves a listing still happened), for a period ending in [`--from`, `--to`].
- Only filings with an XBRL document. Each document once, by URL (NSE lists some twice).
- A listing row whose ISIN names another company than the universe's ISIN for that symbol is
  left out.
- The basis rule (`--basis`): under `consolidated-first` a quarter's standalone filings are read
  only when the company filed no consolidated results for that quarter (the listing says so);
  their documents are not even downloaded. Under `both` every filing is read.

## 2. Format

Each document is classified from its own schemaRef and namespaces; the listing's markers agree
with it in every case seen (`New/Ind-AS New/N` is Ind AS, `New/Non-Ind-AS/B` banking,
`New/NBFC-IND/F` NBFC).

| `format` | Identified by |
|---|---|
| `reg33_indas` | schemaRef `Ind-AS_entry_point_*.xsd` |
| `reg33_banking` | `banking_entry_point_*.xsd` |
| `reg33_nbfc` | `in-bse-fin-*.xsd` (NBFCs from 2019) |
| `reg33_non_indas` | `other_than_banks_entry_point_*.xsd` (2018: NBFCs before Ind AS) |
| `integrated_indas`, `integrated_banking`, `integrated_nbfc`, `integrated_otherthanbank` | namespace `sebi.gov.in/xbrl/IntegratedFinance_<variant>/` |
| `insurance_skipped` | namespace `/xbrl/Insurance/`, or Integrated `LI`/`GI`: a metadata row, no figures |
| `other` | an XBRL in none of these: still parsed with the same tags |

A document with a `DOCTYPE` or `ENTITY` declaration is refused (`xbrl_doctype`) before parsing.

## 3. Quarter vs year to date

NSE's instances put the statement in two contexts: `OneD`, the quarter, and `FourD`, the
financial year to date. **The quarter is read from `OneD` only, never from `FourD`**: in a Q3
document `FourD` holds nine months. `FourD` gives the `ytd_*` columns.

## 4. Period from the document

The period is the document's own `DateOfStartOfReportingPeriod` / `DateOfEndOfReportingPeriod`
in each context (or the context's defined period), not the listing's. Reg 33 bank documents give
only the end, so the quarter starts three months before it. When the document's period end
differs from the listing's, the document's is kept, `period_mismatch` is true and
`listing_period_end` holds the listing's.

## 5. Tags

| Column | Tags, first found wins |
|---|---|
| `revenue` | `RevenueFromOperations`, `TotalRevenueFromOperations`, `InterestEarned`. Banks (`*_banking`): `InterestEarned` first, so **a bank's revenue is its interest earned**. NBFC templates carry both; revenue from operations wins |
| `total_income` | `Income`, `TotalIncome` |
| `net_profit` | Consolidated: `ProfitOrLossAttributableToOwnersOfParent` (or the bank template's profit after minority interest and associates), unless that field is left at 0 while the period shows a profit. Otherwise `ProfitLossForPeriod` |
| `eps_basic`, `eps_diluted` | From continuing and discontinued operations; then continuing; then (banks) after, then before, extraordinary items |
| `basis` | `NatureOfReportStandaloneConsolidated` in the document; the listing's when the document has none |

Every Reg 33 and Integrated variant maps into these same columns.

**A copied EPS is corrected.** When a document gives continuing and discontinued EPS that are
equal and non-zero, and its "continuing and discontinued" total is exactly their sum, the
discontinued figure is a copy of the continuing one (MARUTI's Mar 2024 filing: 125.71 + 125.71
= 251.42, with no discontinued operations). The continuing EPS is used, basic and diluted, and
`eps_corrected` is true.

## 6. Units

Money facts must carry the unit `iso4217:INR` and EPS `iso4217:INR / xbrli:shares`, as the
fact's own `unitRef` declares; anything else excludes the document (`unit_not_inr`,
`unit_not_inr_per_share`). Values are in rupees whatever the stated rounding level (`decimals`
or a "Level of rounding" fact says how the PDF rounds, not how the XBRL counts). A value that is
not a number is excluded (`value_not_numeric`).

The sanity flag `unit_suspect` (revenue 20x off the previous quarters' median) is computed at
build time, point in time: [point in time](point-in-time.md#unit_suspect).

## 7. Q4 from the year

Some Q4 documents carry only the year's figures in `OneD` (the context spans more than 100
days, or it starts the financial year, ends the year and equals `FourD`). Then:

- Q4 = the year minus the nine months to December, field by field;
- the nine months come from the same document when another context holds them (a 250 to 290
  day span ending about 90 days before the year end), else from the stored Q3 row's year to
  date on the same basis and financial year;
- `q4_derived` is true; when the nine months are not known the document is excluded
  (`q4_nine_month_missing`).

A Q1 document whose quarter equals its year to date is a normal quarter (Q1 does not end a
year).

## 8. Exclusions

Every filing considered is in `out/filings.csv` with `result`:

| `result` | Meaning |
|---|---|
| `stored` | A new row (`version` says which) |
| `same_figures` | Repeats the latest version's figures: no row |
| `insurance_skipped` | An insurer's metadata row |
| `excluded` | No row; `reason`: `not_fetched`, `xbrl_http_<status>`, `xbrl_malformed`, `xbrl_doctype`, `not_xbrl`, `period_missing`, `quarter_context_missing`, `unit_not_inr`, `unit_not_inr_per_share`, `value_not_numeric`, `value_out_of_range`, `basis_unknown`, `q4_nine_month_missing`, `no_time` |

`pasta parse` prints the counts by result and by reason.

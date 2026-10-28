# Schema

Everything lives under the data folder you pass with `--data`. Keep it outside any git
repository: the data belongs to its owners and must not be committed or redistributed.

## The data folder

| Path | What | Rebuilt? |
|---|---|---|
| `raw/nse/manifest.jsonl`, `raw/nse/blobs/` | Every NSE answer (listings, documents, announcement windows, lists): one manifest line per fetch (`url`, `status`, `sha256`, `bytes`, `fetched_at` UTC), each body gzipped once under its sha256 | Never rewritten, never deleted: the source of truth. **Back it up** |
| `raw/screener/` | Every screener.in page and robots.txt, the same way | The same |
| `universe.json` | The universe spec, the first period end the last fetch asked for (`from`), and every company it has held (`symbol`, `isin`, `name`, `first_seen`, `last_seen`) | Updated by each fetch |
| `pasta.toml` | Your settings ([maintaining](maintaining.md#settings-pastatoml)) | Never written but by `config init` |
| `out/` | The tables below | Rebuilt whole by `parse`, `build`, `as-of` |
| `.pasta.lock` | Held while a step runs, so two never run on one folder at once | — |

Every file in `out/` is written to a temporary name and renamed, so an interrupted run never
leaves half a file. Each table is written as CSV and Parquet with the same columns (except
`filings`, `coverage` and `crosscheck`: CSV only).

**Types.** In Parquet: money and EPS are `decimal128(24, 4)` (rupees, and rupees a share),
growth ratios `decimal128(24, 6)`, times `timestamp[s, UTC]`, dates `date32`. In CSV: decimals
written out exactly, times ISO 8601 with their IST offset (`2025-04-10T16:05:24+05:30`), dates
ISO, booleans `true`/`false`, missing values empty.

## `out/results`

One row per version of a quarter's results. Sorted by symbol, period end, basis, source,
version.

| Column | What |
|---|---|
| `id` | `SYMBOL:period_end:basis:source:vN`, stable across rebuilds |
| `symbol`, `isin`, `company` | From the universe list (current symbol) |
| `period_start`, `period_end` | The quarter, from the document ([parser rules](parser-rules.md#4-period-from-the-document)) |
| `fiscal_year`, `fiscal_quarter` | India's April-March year: `2024-12-31` is `FY2025`, `Q3` |
| `basis` | `consolidated` or `standalone` |
| `source` | `nse` or `screener` |
| `format` | `reg33_indas`, `reg33_banking`, `reg33_nbfc`, `reg33_non_indas`, `integrated_*`, `other`, `insurance_skipped` (metadata only, no figures), `screener` |
| `revenue` | Revenue from operations; banks: interest earned. Rupees |
| `total_income` | Total income (revenue plus other income). Empty on screener.in rows |
| `net_profit` | Consolidated: profit attributable to the owners of the parent; else the period's profit after tax |
| `eps_basic`, `eps_diluted` | Rupees a share. `eps_diluted` empty on screener.in rows |
| `ytd_start` | First day of the year-to-date context (the financial year's start) |
| `ytd_revenue`, `ytd_total_income`, `ytd_net_profit`, `ytd_eps_basic`, `ytd_eps_diluted` | The financial year to date as the document gives it (for a derived Q4: the year) |
| `q4_derived` | Q4 = the year less nine months ([rule 7](parser-rules.md#7-q4-from-the-year)) |
| `period_mismatch`, `listing_period_end` | The document's period end differs from the listing's (the listing's kept here) |
| `public_at` | When the figures became public ([point in time](point-in-time.md#public_at)) |
| `public_at_source` | `announcement`, `xbrl`, `xbrl_date`, `deadline`, `observed` |
| `public_at_estimated` | True when `public_at` is an upper bound, not a known moment |
| `xbrl_at`, `xbrl_at_estimated` | When the XBRL was filed, and whether that is the end of its day |
| `version` | 1, 2, ... per (symbol, period end, basis, source) |
| `revision` | Version 2 on, or NSE marked the filing a revision |
| `supersedes_id` | The `id` of the version this one revises |
| `listing`, `listing_seq` | `reg33`, `integrated`, `insurance` or `screener`, and NSE's sequence number |
| `source_url`, `sha256` | The document (or page) the row was read from, and the sha256 of its bytes, which names its blob in `raw/` |

## `out/asof=<YYYY-MM-DDTHHMM>`

`pasta as-of T`: one row per company and quarter (per basis with `--basis both`) as known at
T. Every `results` column, plus:

| Column | What |
|---|---|
| `as_of` | T |
| `unit_suspect` | The row was flagged by T |
| `growth_basis`, `prior_period_end`, `prior_id` | The basis growth was computed on, and the year-ago row |
| `sales_yoy`, `eps_yoy`, `turnaround`, `growth_reason` | As in `growth`, as known at T |

The file name's time is IST.

## `out/growth`

One row per result row (insurers left out), as known when that row became public.

| Column | What |
|---|---|
| `result_id` | The result row |
| `symbol`, `period_end`, `fiscal_year`, `fiscal_quarter`, `basis`, `source`, `version` | Copied from it |
| `as_of` | Its `public_at`: when this growth could first be computed |
| `unit_suspect` | Revenue 20x off the previous 4 quarters' median ([rule](point-in-time.md#unit_suspect)) |
| `current_id` | The row growth was computed from (under `consolidated-first`, a standalone row's quarter uses its consolidated row when one is known) |
| `growth_basis`, `prior_period_end`, `prior_id` | The common basis, and the year-ago row |
| `sales_yoy` | revenue / prior revenue - 1 |
| `eps_yoy` | basic EPS / prior basic EPS - 1, when both are positive |
| `turnaround` | Prior EPS <= 0 and EPS > 0 |
| `growth_reason` | Why a value is empty: `no_common_basis`, `revenue_missing`, `prior_revenue_not_positive`, `eps_missing`, `eps_not_positive` (`;`-joined) |

## `out/filings.csv`

Every filing `parse` considered: `symbol, listing, seq, listing_period_end, period_end, basis,
format, markers` (the listing's format markers), `url`, `result` (`stored`, `same_figures`,
`insurance_skipped`, `excluded`), `reason` ([exclusions](parser-rules.md#8-exclusions)),
`version, q4_derived, period_mismatch, public_at_source`.

## `out/coverage.csv`

Per symbol and calendar year of the period end, over the parsed range: `quarters` (ended),
`due` (results deadline passed), `nse` (with an NSE row), `nse_consolidated`, `screener` (a
screener.in row only), `insurer` (metadata row), `missing` (due, no row) and
`missing_quarters`. `pasta build` prints the totals by year.

## `out/crosscheck.csv`

Per quarter where NSE's latest version and screener.in's latest page share a basis: NSE's and
screener.in's `revenue`, `net_profit`, `eps_basic`, and whether each agrees (within 1% or 1
crore; EPS within 1% or 5 paise). Expect disagreement where screener.in shows profit including
minority interest or EPS restated for a later bonus or split ([screener.in](screener.md)).

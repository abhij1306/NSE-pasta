# Point in time

The rules that keep the data honest about time, each stated once. The code is the source of
truth (`timing.py`, `growth.py`, `build.py`); if this file and the code disagree, one of them is
wrong.

## The invariants

1. **Every row says when it became public** (`public_at`, an aware timestamp, IST in the
   source, UTC in the files) and how that was found (`public_at_source`), and whether it is an
   estimate (`public_at_estimated`: an upper bound, never early).
2. **Nothing is overwritten.** A revised filing is a new row with `version` + 1 and
   `supersedes_id` naming the row it revises; the original stays. Every downloaded answer stays
   in `raw/` under its sha256 forever, and `out/results` is rebuilt from `raw/` alone, so a
   rebuild gives the same versions plus any new ones.
3. **A read at time T uses only rows with `public_at <= T`** (`pasta as-of T`): for each
   quarter and basis, the latest version public by T.
4. **Growth never mixes bases** and is computed as it could have been at the time.

## `public_at`

| `public_at_source` | When | Estimated |
|---|---|---|
| `announcement` | The company's results announcement on NSE: a `Financial Result Updates` item, or (in the Integrated Filing era) an `Outcome of Board Meeting` whose text names the results | no |
| `xbrl` | The XBRL filing time, when it is known to the second and earlier than any announcement found | no |
| `xbrl_date` | The end of the XBRL file name's date (23:59:59 IST), when the listing's time is a later re-broadcast | yes |
| `deadline` | screener.in rows with no NSE announcement in the cache: the regulatory deadline, quarter end + 45 days (+ 60 for the March quarter), 23:59 IST | yes |
| `observed` | A later screener.in version: when the page showing the new figures was fetched | yes |

The rules, for version 1 of an NSE quarter:

- **The announcement comes first.** The results PDF goes out as an announcement 31 minutes to
  22.5 hours before the XBRL in every case sampled (18 filings, 2019 to 2026); 3 of them were
  filed the next day. Dating by the XBRL alone would date results up to a day late, past a
  whole session.
- The announcement is searched for from 2 days before to 1 day after the filing's earliest date
  (XBRL file-name date, listing time, creation time), and only after the quarter end. One that
  names a quarter end other than this one is skipped; one that names this quarter wins; else
  the earliest `Financial Result Updates`; else the earliest board outcome naming the results;
  else the earliest board outcome that names nothing at all ("Outcome of Board Meeting held on
  April 10, 2025", TCS's March 2025 results) broadcast on the filing's own day or the day
  before. That last rule is never used for screener.in rows, whose window is a whole quarter.
- `public_at` is the earlier of the announcement and `xbrl_at` (when that is known to the
  second).
- **One company's announcement clock reads 12 hours early** (05:08 for an evening board meeting
  whose XBRL went in at 20:32). An announcement before 09:15 whose XBRL was filed, at a known
  time on the same day, 12 hours or more later is read as the PM time.
- Without announcements (`--no-announcements`, or none found) `public_at` is `xbrl_at`.

**Revisions** (version 2 on) are public from their own filing (`xbrl_at`), never from the
original's announcement.

### `xbrl_at`

When the XBRL was filed:

- Integrated Filing: the listing's `creation_Date`.
- Reg 33: the listing's `broadCastDate` when it falls on the date in the XBRL file name;
  otherwise the end of that date (`xbrl_at_estimated`). For 2017 to 2021 the listing time is
  often a re-broadcast weeks later (RELIANCE Mar 2019: listed 06-May-2019, filed 19-Apr-2019,
  announced 18-Apr-2019 18:15), so it is never used past the file name's date.
- The file name's time is never read: it is a 12-hour clock without AM/PM.

## Versions

Per company, quarter end, basis and source, filings are taken in filing order:

- the first readable one is version 1;
- a later one with different figures (quarter or year to date) is version + 1, `revision`
  true; a revision of the year to date alone is a new version too, since Q4 derivation reads it;
- a later one with the same figures adds nothing (`same_figures` in `out/filings.csv`).

An Integrated Filing marked `Revision` sets `revision` even on its first stored version.

`id` is `SYMBOL:period_end:basis:source:vN`, stable across rebuilds.

## NSE first, screener.in second

- A screener.in row exists only for a quarter and basis NSE has no row for. Under
  `consolidated-first`, a screener.in standalone quarter is also dropped when NSE lists a
  consolidated filing for it (stored or not), so a failed consolidated document is never
  replaced by standalone figures.
- In a read, an NSE row of a quarter and basis always wins over a screener.in row of the same
  quarter and basis, once it is public.

## The as-of read

`pasta as-of T` writes `out/asof=<T>.parquet` and `.csv`: per company, for each (quarter,
basis) the latest version with `public_at <= T`, NSE over screener.in, insurers' metadata rows
left out, then the basis rule:

- `consolidated-first`: a quarter's standalone row only when no consolidated row of that
  quarter is known at T.
- `both`: every basis.

Each row carries its quarter's growth as known at T and `unit_suspect` as flagged by T. `T` is
`YYYY-MM-DD` (the end of that day, 23:59:59 IST) or `YYYY-MM-DDTHH:MM` (IST unless an offset is
given). A backtest deciding at 09:15 on day D reads `as-of DTHH:MM` with that time, or filters
`out/results` on `public_at` itself.

## Growth

For each result row, `out/growth` holds its quarter's growth as known when the row became
public (`as_of` = the row's `public_at`):

- against the same quarter a year earlier, on one basis: consolidated when both quarters have
  it, else standalone when both have it, else undefined (`no_common_basis`). Never mixed;
- `sales_yoy` = revenue / prior revenue - 1, when prior revenue > 0;
- `eps_yoy` = basic EPS / prior basic EPS - 1, when both are > 0;
- `turnaround` = prior EPS <= 0 and EPS > 0;
- a unit-suspect row is treated as absent; `growth_reason` says why a value is undefined.

### `unit_suspect`

A row whose quarterly revenue is more than 20 times above or below the median of the company's
previous 4 quarters on the same basis (at least 2 of them positive), as known when the row
became public, leaving out quarters already flagged. It catches a filing in lakh or thousand
where the company files in rupees elsewhere. A flagged row stays in `out/results`; it is left
out of every growth comparison from the moment it became public.

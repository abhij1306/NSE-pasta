# Command line

The command is `pasta`. Run it as `uv run pasta ...` from the repository, or as plain `pasta`
with the project's virtual environment activated or the tool installed
([getting started](getting-started.md)).

```text
pasta [--data DIR] [--interval SECONDS] [-v] {run,fetch,parse,build,as-of,status,doctor,config} ...
pasta                          (no arguments: the guided menu)
```

## Global options

These go **before** the subcommand: `pasta --data D run`, not `pasta run --data D`.

| Option | Meaning |
|---|---|
| `--data DIR` | The data folder; default `$PASTA_DATA`, required when that is not set. Keep it outside any git repository. `~` is expanded and the folder is created if needed |
| `--interval SECONDS` | Seconds between two requests to NSE. Default 2, or `[network] interval` in `pasta.toml`. Do not go lower. screener.in has its own, `[screener] interval` (default 3) |
| `-v`, `--verbose` | Log each retry and warning |

## The guided menu

`pasta` with no arguments asks for a data folder (default `$PASTA_DATA`, else `~/pasta-data`;
it refuses a folder inside a git repository), shows what it holds, and offers:

1. Run everything (`run`): asks for the universe, the first quarter end and the source
2. Fetch only (`fetch`)
3. Parse and build from what is on disk (`parse`, then `build`)
4. Point-in-time table as of a day (`as-of`)
5. Check that the sources still work (`doctor`)
6. Show what the data folder holds (`status`)
7. Quit

Each answer has a default in brackets (Enter takes it). The menu prints the equivalent command
line and asks before running it. Type `q` at any prompt to go back.

## run and fetch

`pasta --data D run [--universe U] [--from D] [--to D] [--source S] [--basis B]
[--no-announcements]`: `fetch`, then `parse`, then `build`, every step even after a failed
download (the exit code still says it failed). `fetch` takes the same options and downloads
only.

| Option | Default | Meaning |
|---|---|---|
| `--universe` | `[run] universe`, else the folder's last universe | `nifty50`, `niftynext50`, `nifty100`, `nifty200`, `nifty500`, `midcap150`, `smallcap250`, `all`, or `file:PATH` (one symbol a line, `#` comments; or a CSV with a `symbol` column) |
| `--from`, `--to` | `[run] from` (2020-03-31), today | Period ends to fetch |
| `--source` | `[run] source` (`nse`) | `nse`, `screener`, `both` |
| `--basis` | `[run] basis` (`consolidated-first`) | `consolidated-first`, `both` |
| `--no-announcements` | announcements on | Skip the announcement windows: `public_at` then comes from the XBRL filing time, up to a day late |

What `fetch` asks, in order ([sources](sources.md)):

1. the universe list (an index list or the equity list, at most once in 20 hours);
2. with `nse` or `both`: the insurers' listing; then per company its Reg 33 and Integrated
   Filing listings (again only when older than 20 hours), every XBRL document they list in the
   range under the basis rule (never asked twice, 404 included), and a 4-day announcement
   window around each filing (asked again until fetched after the window ended);
3. with `screener` or `both`: screener.in's robots.txt, then per company its consolidated page
   (and the standalone page when the rule needs it), at most once in 20 hours;
4. with `both`: for each quarter only screener.in gives, NSE's announcements from the quarter
   end to 30 days past its deadline, 4 days at a time.

A rerun asks only what is new or stale: a second `run` the same day asks nothing.

## parse

`pasta --data D parse [--from D] [--to D] [--basis B]`: reads only `raw/` and rewrites
`out/results` and `out/filings.csv` ([parser rules](parser-rules.md)). `--from` defaults to the
`from` of the folder's last fetch, `--to` to today.

## build

`pasta --data D build [--from D] [--to D] [--basis B]`: reads `out/results` (and the screener.in
pages in `raw/`) and rewrites `out/growth`, `out/coverage.csv` and `out/crosscheck.csv`.

## as-of

`pasta --data D as-of WHEN [--basis B]`: writes `out/asof=<WHEN>.parquet` and `.csv`, the table
as it could have been known at WHEN ([point in time](point-in-time.md#the-as-of-read)). WHEN is
`YYYY-MM-DD` (the end of that day, IST) or `YYYY-MM-DDTHH:MM` (IST, or with an offset).

## status, doctor, config

- `status`: the universe, the cached answers by kind, the last fetch time and each output's
  row count. No network.
- `doctor`: one live request per source (about ten), each `ok`, `not_found`, `blocked` or
  `format_changed`, then what to do ([maintaining](maintaining.md#when-a-fetch-fails-doctor)).
- `config init` writes `DATA/pasta.toml` with every default (never over an existing file);
  `config show` prints the settings in effect.

## Exit codes

| Code | When |
|---|---|
| 0 | Everything finished |
| 1 | A download failed (`listings_failed`, `documents_failed`, `announcement_windows_failed`, `screener_failed` in the `fetch` line), `doctor` found a source that is not `ok`, the folder is in use by another pasta process, no universe was chosen, or `config init` found a file |
| 2 | The command line could not be parsed, or `pasta.toml` has a mistake (the message names it) |

## What each command prints

One line per step, `title: {json}`; progress goes to stderr every 10 companies.

| Line | Keys |
|---|---|
| `universe` | `spec`, `companies` |
| `fetch` | `companies`, `listings_fetched`, `listings_failed`, `documents` (asked for), `documents_fetched` (new this run), `documents_failed`, `announcement_windows`, `..._fetched`, `..._failed`, `screener_pages`, `screener_pages_fetched`, `screener_failed`, `requests`, `statuses` (HTTP status counts) |
| `parse` | `companies`, `rows`, `screener_rows`, `outcomes` (by result), `excluded` (by reason) |
| `growth` | `rows`, `unit_suspect`, `sales_yoy_defined`, `eps_yoy_defined` |
| `coverage` | per year: `quarters`, `due`, `nse`, `nse_consolidated`, `screener`, `insurer`, `missing` |
| `crosscheck` | `quarters` compared; for revenue, net profit and EPS: `agree`, `differ`, `not_comparable` |

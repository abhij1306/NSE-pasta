# Getting started

From a fresh clone to a point-in-time results table. Each command is shown for bash (macOS,
Linux, Git Bash); PowerShell takes the same commands unless shown.

## 1. Install

You need git and [uv](https://docs.astral.sh/uv/). uv installs Python 3.12+ for the project if
you don't have it.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then clone and install:

```bash
git clone https://github.com/abhij1306/NSE-pasta
cd NSE-pasta
uv sync
uv run pasta --help
```

`uv sync` creates `.venv/` with the locked dependencies. Prefix commands with `uv run`, or
activate the environment once per shell (`source .venv/bin/activate`, or
`.venv\Scripts\Activate.ps1` in PowerShell) and type `pasta` directly.

## 2. Choose a data folder

Pick a folder **outside any git repository**, e.g. `~/pasta-data`. The data must never be
committed. `pasta` expands `~` itself, so `--data ~/pasta-data` works in PowerShell too.

## 3. A first run

The guided menu is the easiest start. It asks for each choice and shows the command it runs:

```bash
uv run pasta
```

Or, for a handful of companies of your own (a quick first run):

```bash
printf "TCS\nHDFCBANK\nRELIANCE\n" > ~/symbols.txt
uv run pasta --data ~/pasta-data run --universe file:$HOME/symbols.txt --from 2023-03-31
uv run pasta --data ~/pasta-data as-of 2025-06-30
```

Or the NIFTY 50, with screener.in filling NSE's gaps:

```bash
uv run pasta --data ~/pasta-data run --universe nifty50 --from 2023-03-31 --source both
```

`run` fetches (universe list, NSE listings, XBRL documents, announcements; screener.in pages
with `--source both`), parses everything into `out/results`, and builds `out/growth`,
`out/coverage.csv` and `out/crosscheck.csv`. `as-of` writes the table as it could have been
known at the end of 30 June 2025. Every command: [cli](cli.md). Every column:
[schema](schema.md).

**Time.** At one request every 2 seconds, NSE costs about **32 requests per company for three
and a half years** of quarters (two listings, then per quarter one document and one
announcement window under `consolidated-first`), so about a minute per company: a sample of 8
NIFTY 50 companies from the March 2023 quarter took 259 requests and about 9 minutes. That is
about an hour for the NIFTY 50 from 2023 and about half a day for the NIFTY 500 from 2020.
screener.in adds one or two pages per company at one every 3 seconds. `--basis both` reads the
standalone documents too (about 1.5x). Everything is resumable: stop it any time and run the
same command again.

**Disk.** That 8-company sample holds 2.4 MB in `raw/` (gzipped) and 0.25 MB in `out/`: about
0.3 MB per company for three and a half years, so tens of megabytes for the NIFTY 500.

## 4. Check that it worked

Read the printed counts ([what each key means](cli.md#what-each-command-prints)):

| Count | Expect | If not |
|---|---|---|
| `fetch.listings_failed`, `documents_failed`, `announcement_windows_failed`, `screener_failed` | empty / 0 | Transient: rerun. If it persists, `pasta doctor` |
| `parse.excluded` | a few at most | Each reason is in [parser rules](parser-rules.md#8-exclusions); the filings are in `out/filings.csv` |
| `coverage.<year>.missing` | 0 from 2020 | A listing gap or an excluded document: `out/coverage.csv` names the quarters. `--source both` fills recent ones |
| `growth.unit_suspect` | 0 or a few | Look at those rows: a filing in the wrong unit |
| `crosscheck.revenue.differ` | 0 or a few | Revenue should agree with screener.in; profit and EPS differ for known reasons ([screener.in](screener.md#precision-and-meaning)) |

A quick look at the result:

```bash
uv run python -c "import pyarrow.parquet as pq; print(pq.read_table('DATA/out/results.parquet').to_pandas().tail())"
```

(`to_pandas` needs pandas; `pyarrow.csv` or polars read the files too.) Replace `DATA` with
your data folder, written out in full.

## Rerun, resume, refresh

- Every step is resumable and idempotent: after an interruption, run the same command again.
  Documents are never fetched twice; a second `run` the same day asks nothing.
- To bring the data up to date, rerun `run` ([maintaining](maintaining.md)).
- `parse` and `build` read only the disk: rerun them freely (after upgrading pasta, too).
- Back up `raw/` and `universe.json`. Everything in `out/` is rebuilt from them.

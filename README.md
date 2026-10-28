# NSE-pasta

**The method, not the data:** scripts and rules to download, and keep current, a point-in-time
dataset of Indian listed companies' quarterly financial results (revenue, total income, net
profit, basic and diluted EPS, and the year-to-date figures) for a universe of stocks you
choose, from the National Stock Exchange of India (NSE) and, to fill gaps, screener.in.

> **Data notice.** All results data belongs to the companies that file it and to NSE, which
> publishes it; figures shown on screener.in are subject to screener.in's terms of use. This
> repository contains **no data**. The scripts download from NSE's public website endpoints and
> archives, and optionally from screener.in's public company pages, to a folder on your
> machine; NSE's website endpoints are not a documented public API. Respect NSE's and
> screener.in's terms of use and their robots.txt: keep the default pace (one request every 2
> seconds to NSE, every 3 seconds to screener.in), never run two pulls at once, never log in to
> screener.in or give pasta credentials, and do not redistribute what you download.
>
> **Disclaimer.** The code is provided as is, without warranty of any kind (see `LICENSE`).
> Nothing here is investment advice. The authors are not responsible for any use or misuse of
> the code or of data obtained with it, for losses arising from it, or for your compliance with
> NSE's or screener.in's terms and applicable law.

## Why

Results data is easy to get and easy to get wrong. Three silent errors ruin most home-made
earnings studies. **Look-ahead**: a quarter's figures are used from the day the quarter ended,
or from a listing date NSE re-broadcast weeks later, instead of the moment the company actually
announced them. **Overwritten history**: a restated quarter replaces the original, so a backtest
sees figures nobody had at the time. **Mixed bases**: a year-on-year growth figure compares a
consolidated quarter with a standalone one.

NSE-pasta reads each quarter from the company's own XBRL filing, dates it by the results
announcement it went out with (the PDF on the exchange, typically hours before the XBRL), keeps
every revision as a new version beside the original, and computes growth only between quarters
on the same basis, as it could have been computed at the time. Its `as-of` export is the table
as it could have been known at any past moment.

## Quick start

Install [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` on
macOS/Linux; `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
on Windows), then:

```bash
git clone https://github.com/abhij1306/NSE-pasta
cd NSE-pasta
uv sync
uv run pasta            # a guided menu: pick a data folder, a universe and a source
```

Or run everything for the NIFTY 50 since the March 2023 quarter, then export the table as it
could have been known at the end of 30 June 2025:

```bash
uv run pasta --data ~/pasta-data run --universe nifty50 --from 2023-03-31
uv run pasta --data ~/pasta-data as-of 2025-06-30
```

To keep it current, rerun `run` (it skips what is on disk) or schedule it, and run `doctor`
when NSE changes something: [maintaining](docs/maintaining.md). Or install the command once:
`uv tool install git+https://github.com/abhij1306/NSE-pasta`, then `pasta ...` anywhere.

These commands are the same in PowerShell. Keep the data folder outside any git repository.
Time and disk estimates and how to check the result: [getting started](docs/getting-started.md).

## What you get

| Output (under the data folder) | What |
|---|---|
| `out/results.parquet`, `.csv` | Every version of every quarter: figures, basis, format, `public_at` (when it became public) and how that was found, `version`, the source document and its sha256 |
| `out/asof=<time>.parquet`, `.csv` | The latest version of each quarter public by `<time>`, with year-on-year growth as known then. **Backtests read this** |
| `out/growth.parquet`, `.csv` | Each row's year-on-year growth and unit sanity flag, as known when the row became public |
| `out/coverage.csv` | Per symbol and year: quarters due, found on NSE, filled from screener.in, missing |
| `out/filings.csv` | Every filing considered and what became of it (stored, same figures, excluded with a reason) |
| `out/crosscheck.csv` | NSE against screener.in where both give a quarter |
| `raw/`, `universe.json` | Every answer downloaded, by sha256, never overwritten; the universe |

Every column: [schema](docs/schema.md).

## Choices

- **Universe** (`--universe`): `nifty50`, `niftynext50`, `nifty100`, `nifty200`, `nifty500`,
  `midcap150`, `smallcap250` (NSE's current constituent lists), `all` (every listed equity), or
  `file:PATH` (your own symbol list). A current index list is **not** point-in-time index
  membership: see [limitations](docs/limitations.md).
- **Source** (`--source`): `nse` (default; XBRL filings, exact figures, complete from 2020),
  `screener` (screener.in's public pages: the latest 13 quarters, in rounded crore), or `both`
  (NSE first; screener.in fills quarters NSE does not give, and an NSE row always wins).
- **Basis** (`--basis`): `consolidated-first` (default: consolidated figures, standalone only
  for a quarter with no consolidated filing) or `both` (each basis its own series).
- **Range** (`--from`, `--to`): period ends. Default from the March 2020 quarter, the first with
  complete XBRL ([sources](docs/sources.md#coverage-by-year)).

## Docs

- [Getting started](docs/getting-started.md): install, a first run, checking it worked.
- [Command line](docs/cli.md): every command and flag, the menu, exit codes, printed counts.
- [Maintaining](docs/maintaining.md): scheduled updates, `pasta.toml`, `doctor` when NSE
  changes something.
- [Sources](docs/sources.md): the NSE endpoints, what each gives, coverage by year.
- [Schema](docs/schema.md): every file and column.
- [Point in time](docs/point-in-time.md): `public_at`, versions, the as-of read, growth.
- [Parser rules](docs/parser-rules.md): how an XBRL filing becomes a row.
- [screener.in](docs/screener.md): what is read, the rules kept, how far back it goes.
- [Limitations](docs/limitations.md): what the data cannot tell you.

**Agent skills (optional).** Nothing here needs an AI agent. `.claude/skills/` holds skills for
Claude Code (or any agent that reads `SKILL.md`): `check-quarter` (check a row against the
company's results PDF) and `fix-source` (what to do when `doctor` reports a broken source).

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff format --check . && uv run ruff check .
```

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request:
`ruff format --check`, `ruff check` (including a complexity limit of 10 per function), and
`pytest` on Python 3.12 and 3.13 on Linux and 3.13 on Windows. The tests use no network: they
read small fixtures in `tests/fixtures/`: NSE and screener.in answers in their real shape
(keys, XBRL taxonomies, contexts, units), trimmed, with every name, code and figure invented.
The repository holds no company's data.

## License

Code: MIT (see `LICENSE`). The data you download stays its owners'.

# Keeping the data up to date

Once a data folder is built, three things keep it current and working when NSE changes
something: a scheduled `run`, `doctor` when a fetch fails, and the settings in `pasta.toml`.

## Update on a schedule

`run` skips what is on disk, so rerunning it is the update: listings older than 20 hours are
asked again (new filings appear in them), new documents and announcement windows are fetched,
and `out/` is rebuilt. Write your universe and the start of your history in the settings once:

```bash
pasta --data ~/pasta-data config init           # writes ~/pasta-data/pasta.toml
# edit [run]: universe = "nifty500", from = 2020-03-31, source = "both"
pasta --data ~/pasta-data run                   # from [run] from to today
```

Results season is the six weeks after each quarter end (to mid-May for March). Schedule a
daily run in the evening, after the day's board meetings (IST):

```bash
# cron (Linux, macOS): every day at 22:30
30 22 * * *  PASTA_DATA=$HOME/pasta-data  $HOME/.local/bin/pasta run >> $HOME/pasta-data/run.log 2>&1
```

```powershell
# Windows Task Scheduler: every day at 22:30
schtasks /Create /TN pasta /SC DAILY /ST 22:30 `
  /TR "cmd /c pasta --data %USERPROFILE%\pasta-data run >> %USERPROFILE%\pasta-data\run.log 2>&1"
```

`pasta` on the path means an installed tool: `uv tool install git+https://github.com/abhij1306/NSE-pasta`.
From a clone, use `uv run --directory PATH_TO_CLONE pasta` instead. The exit code is 1 when a
download failed ([exit codes](cli.md#exit-codes)), so a scheduler can alert on it. Never
schedule two runs on one folder: the second stops at once (`in use by another pasta process`).

A universe from an index list is fetched again each run (at most once in 20 hours): companies
that join are added, companies that leave stay (`universe.json`).

## When a fetch fails: `doctor`

Failures in the `fetch` line (`listings_failed`, `documents_failed`, ...) are usually
transient: nothing failed is cached, so the next run asks again. When they keep coming, ask
each source once:

```bash
pasta --data ~/pasta-data doctor
```

```text
sources (default settings, no pasta.toml):
  index list           ok              https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv
  equity list          ok              https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
  reg33 listing        ok              https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=RELIANCE&period=Quarterly
  integrated listing   ok              https://www.nseindia.com/api/integrated-filing-results?...
  insurance listing    ok              ...
  announcements        ok              ...
  xbrl document        ok              https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_..._WEB.xml
  screener robots.txt  ok              https://www.screener.in/robots.txt
  screener page        ok              https://www.screener.in/company/RELIANCE/consolidated/
```

| Status | Meaning | What to do |
|---|---|---|
| `ok` | Answered in the format pasta reads | Nothing |
| `not_found` | 404: the endpoint or file moved | Find the new address on nseindia.com and set it under `[sources]` (below) |
| `blocked` | No answer after retries, an HTTP error, or a web page instead of data | Try later, or raise `[network] interval` (`[screener] interval`) |
| `format_changed` | Data, but not in a format pasta reads | The parser needs a code change: open an issue with the URL. Until then `parse` keeps working on what is cached |

The exit code is 1 when any source is not `ok`. When the screener.in robots.txt stops allowing
company pages, pasta stops asking for them: that is by design.

## Settings: `pasta.toml`

`pasta --data D config init` writes the file with every default; `config show` prints what is
in effect. Delete a key to get its default back. A flag on the command line wins over the
file. A mistake (an unknown key, a bad value) stops every command with exit code 2 and names
the key.

```toml
[network]
interval = 2.0          # seconds between requests to NSE; do not go lower
tries = 4
timeout = 60.0
user_agent = "Mozilla/5.0 ..."

[screener]
interval = 3.0          # seconds between requests to screener.in
base = "https://www.screener.in"

[run]
universe = ""           # nifty50 ... nifty500, all, file:PATH; "" = the folder's last one
from = 2020-03-31       # first period end fetched
source = "nse"          # nse | screener | both
basis = "consolidated-first"   # or both
announcements = true

[sources]
results_page = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
announcements_page = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
results_api = "https://www.nseindia.com/api/corporates-financial-results"
integrated_api = "https://www.nseindia.com/api/integrated-filing-results"
announcements_api = "https://www.nseindia.com/api/corporate-announcements"
index_list = "https://nsearchives.nseindia.com/content/indices/{name}"
equity_list = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
```

The `*_page` URLs are the pages loaded for cookies and sent as Referer. Cached answers are
keyed by URL, so after changing an endpoint its answers are fetched afresh; the old ones stay in
`raw/`.

## What settings cannot fix

A moved endpoint is a settings change. A **new answer shape** needs code: in 2025 NSE moved
quarterly results from the Reg 33 listing to Integrated Filing, a new endpoint and a new XBRL
taxonomy, which needed a new parser path. pasta reads a document's format from its own
schemaRef and namespaces; a document in no known format is still parsed with the same tags
(`format = other`), and one whose figures cannot be read is excluded with its reason in
`out/filings.csv`. Nothing is guessed.

## Upgrading pasta

`raw/` is all that matters: after upgrading, `pasta --data D parse` and `build` rebuild `out/`
from it under the new rules. Versions are rebuilt the same way, so nothing is lost.

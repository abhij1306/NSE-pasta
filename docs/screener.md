# screener.in

The secondary source, read with `--source screener` or `--source both`: for quarters NSE does
not give (a listing gap, a document that cannot be read) and to cross-check the quarters it
does (`out/crosscheck.csv`).

## Rules pasta keeps

- **Public pages only.** pasta never logs in, never sends, asks for or stores credentials or
  cookies of an account, and reads only the two public company pages below.
- **robots.txt first.** Before any page, pasta reads `https://www.screener.in/robots.txt` and
  asks only for URLs it allows. Without a robots.txt that says yes, nothing is asked. At the
  time of writing it disallows, among others, `/company/source/quarter/*` (never asked) and
  query strings such as `?q=`, `?sort=`, `?page=` (never sent).
- **Slow.** One request every 3 seconds by default (`[screener] interval`), slower than NSE.
  Two pages per company at most; a page is asked again only after 20 hours.
- Every page is kept in `raw/screener/` by sha256, like NSE's answers.

## What is read

| Page | URL | Basis |
|---|---|---|
| Consolidated | `https://www.screener.in/company/<SYMBOL>/consolidated/` | consolidated, or standalone when the company has no consolidated accounts (the page says which above the table) |
| Standalone | `https://www.screener.in/company/<SYMBOL>/` | standalone; read only with `--basis both`, or when the consolidated page shows no quarters |

From the page's **Quarterly Results** table (`<section id="quarters">`): the column dates
(`data-date-key`), the basis named above the table, and three rows:

| Row | Column | Scale |
|---|---|---|
| `Sales` (companies) or `Revenue` (banks, NBFCs) | `revenue` | crore rupees, as displayed: × 10^7 |
| `Net Profit` | `net_profit` | crore rupees: × 10^7 |
| `EPS in Rs` | `eps_basic` | rupees a share |

Total income and diluted EPS are not shown: those columns stay empty on screener.in rows.

## How far back the public pages go

**The latest 13 quarters.** Checked on 28 Oct 2026 on a company's and a bank's consolidated
pages: both showed the quarters ending 2023-09-30 to 2026-09-30. The annual table goes back about
12 years, but pasta reads quarters only. So screener.in can fill gaps only in roughly the last
three years, never backfill 2020 to 2022: for older quarters NSE is the only source.

## Precision and meaning

- Figures are rounded to the crore as displayed (to 0.01 crore for small companies). pasta
  stores them exactly as shown, scaled to rupees; they are not exact rupee figures.
- screener.in's consolidated `Net Profit` is profit after tax including minority interest
  (non-controlling interests) for some companies, where pasta's NSE rows take the profit
  attributable to the owners of the parent. Expect differences for groups with large minority
  interests; `out/crosscheck.csv` shows them.
- A bank's `Revenue` on screener.in is its interest earned, like pasta's NSE rows.
- **EPS is restated for later bonuses and splits** on screener.in (after a 1:1 bonus, earlier
  quarters show half the EPS the company filed). pasta's NSE rows keep EPS as filed.

## Rows

- `source = screener`, `format = screener`, `listing = screener`, `source_url` the page,
  `sha256` the page's.
- A row exists only for a quarter and basis NSE has no row for ([point in
  time](point-in-time.md#nse-first-screenerin-second)).
- `public_at`: the quarter's NSE results announcement when the cache holds one (`--source both`
  fetches NSE's announcements for each such quarter, from the quarter end to 30 days past its
  deadline, 4 days at a time), else the regulatory deadline (quarter end + 45 days, + 60 for
  the March quarter, 23:59 IST), `public_at_estimated` true.
- A later page showing other figures for the quarter is version + 1, public when that page was
  fetched (`observed`).

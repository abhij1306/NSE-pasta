# Sources

Every figure comes from a public source, asked politely: NSE's website endpoints and archives,
and optionally screener.in's public company pages. The URLs are settings
(`[sources]` in `pasta.toml`, [maintaining](maintaining.md#settings-pastatoml)).

## NSE

All GET. The JSON endpoints answer only a session that first loaded the page they belong to
(it sets cookies) and sends that page as `Referer` and a browser User-Agent. NSE's
`robots.txt` allows `/api/` (it reads `User-agent: * Allow: /` and disallows only
`/market-data-test`).

| What | Endpoint | Params pasta sends | Fields read |
|---|---|---|---|
| Reg 33 results listing (quarters to Dec 2024) | `www.nseindia.com/api/corporates-financial-results` (page `companies-listing/corporate-filings-financial-results`) | `index=equities`, `symbol`, `period=Quarterly` | `toDate`, `consolidated`, `broadCastDate`, `xbrl` (ends `/-` when there is none), `seqNumber`, `isin`, `format`/`indAs`/`bank` |
| Insurers' listing (Reg 33) | the same endpoint | `index=insurance`, `period=Quarterly`, `from_date`, `to_date` | as above, `periodEnd` for the period end |
| Integrated Filing listing (quarters from Mar 2025) | `www.nseindia.com/api/integrated-filing-results` | `index=equities`, `symbol`, `type=Integrated Filing- Financials`, `size=500` | `qe_Date`, `consolidated`, `broadcast_Date`, `creation_Date`, `xbrl`, `type_Sub` (Original/Revision), `seq_Id` |
| Announcements (for `public_at`) | `www.nseindia.com/api/corporate-announcements` (page `companies-listing/corporate-filings-announcements`) | `index=equities`, `symbol`, `from_date`, `to_date` (`dd-mm-yyyy`), 4 days at a time | `an_dt` (broadcast time), `desc`, `attchmntText` |
| The filing itself | `nsearchives.nseindia.com/corporate/xbrl/<file>.xml` | none | the XBRL instance ([parser rules](parser-rules.md)) |
| Index constituents | `nsearchives.nseindia.com/content/indices/ind_<index>list.csv` | none | `Symbol`, `ISIN Code`, `Company Name` |
| Every listed equity | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | none | `SYMBOL`, `ISIN NUMBER`, `NAME OF COMPANY` |

Notes that matter:

- **The two results listings share no quarter.** Dec 2024 is the last Reg 33 quarter and Mar
  2025 the first Integrated Filing one. Without `type`, the integrated endpoint also returns
  Governance filings, which pasta does not read.
- **The listing's broadcast time is not the filing time before 2022.** For 2017 to 2021 it is
  often a later re-broadcast, up to 115 days late (372 in one 2021 case). The XBRL file name's
  date stamp is the filing date. See [point in time](point-in-time.md#xbrl_at).
- **The XBRL file-name time is a 12-hour clock without AM/PM** (`..._17072026075004_WEB.xml`
  was broadcast at 19:50:04). Only its date is used.
- **The same XBRL can be listed twice** under different `seqNumber`s (16 to 38 times a year in
  2018 to 2024). pasta reads each document once, by URL.
- **Announcements answer `[]` for long windows.** A 21-day window came back empty where a 4-day
  window inside it held the items, so pasta asks 4 days at a time.
- **Insurers** file in their own listing (`index=insurance`, from mid-2024 in the equities
  sense) and in Integrated Filing from 2025, in an insurance taxonomy. pasta keeps a metadata
  row for each (`format=insurance_skipped`) and no figures.
- One request every 2 seconds, sessions with cookies, back-off on 401/403/429: a probe of 1,631
  requests at one a second saw no 401, 403 or 429, and one page load's cookies lasted the whole
  35-minute run.

## Coverage by year

From a probe of 20 companies (large, mid and small; corporates, banks, NBFCs and an insurer),
October 2026. "Symbol-quarters with XBRL" counts quarters with at least one readable document.

| Year | Symbol-quarters with XBRL / due | Every symbol complete |
|---|---|---|
| 2016 | 0 / 76 | no (HTML results pages only) |
| 2017 | 2 / 76 | no |
| 2018 | 60 / 76 | no (partial) |
| 2019 | 62 / 76 | no (partial; NBFCs worst in mid-2019) |
| 2020 | 76 / 76 | yes |
| 2021 | 75 / 76 | one listing gap |
| 2022 | 70 / 76 | listing gaps: Jun 2022 for 5 symbols, one more in Sep 2022 |
| 2023 | 76 / 76 | yes |
| 2024 | 79 / 80 | the insurer's first quarter |
| 2025 | 80 / 80 | yes |
| 2026 | 50 / 40 | yes (some had already filed the Sep 2026 quarter) |

- **XBRL is complete from the March 2020 quarter**, so `--from` defaults to 2020-03-31.
- **2018 to 2019 are partial** (about 80% of symbol-quarters). Ask for them with `--from
  2018-03-31`; the gaps show in `out/coverage.csv`.
- **Before 2018 there is no XBRL**: only HTML results pages (`resultDetailedDataLink`), which
  version 1 does not read ([limitations](limitations.md)).
- **Listing gaps** exist (Jun 2022 above): the results were announced, but NSE's listing has no
  row. `--source both` fills such a quarter from screener.in when it is within screener.in's
  13 quarters; otherwise it stays missing and shows in `out/coverage.csv`.

Your own numbers for your universe are printed by `pasta build` (`coverage`) and written per
symbol and year to `out/coverage.csv`.

## screener.in

Public company pages only, as its robots.txt allows: [screener.in](screener.md).

# Limitations

What the data cannot tell you, so a backtest does not assume it.

- **A current index list is not point-in-time membership.** `--universe nifty50` takes NSE's
  constituent list as it is on the day you fetch. A company that joined the index last year is
  in it for every past quarter; one that left before your first fetch is not in it at all. A
  folder keeps every company its universe ever listed (`universe.json` `first_seen`,
  `last_seen`), so a folder updated over years accumulates the leavers from then on, but not
  before. For survivorship-free index work, supply your own historical membership as
  `--universe file:PATH` (every symbol that was ever a member) and filter by membership dates
  yourself.
- **Symbols, not companies.** Listings are asked for by the current symbol. NSE answers a
  renamed company's history under its current symbol in the cases seen, but a symbol that
  was reused by another company, or a merger, is not traced. Rows whose ISIN differs from the
  universe's are left out.
- **Before 2018 there is no XBRL**, and 2018 to 2019 are partial ([sources](sources.md#coverage-by-year)).
  The HTML results pages of 2016 to 2017 carry the core figures but are not read in version 1.
- **Listing gaps.** NSE's listing misses some quarters that were announced (Jun 2022 for
  several companies). Within the last 13 quarters `--source both` fills them from screener.in;
  older ones stay missing (`out/coverage.csv`).
- **screener.in is approximate**: figures rounded to the crore, the latest 13 quarters only, EPS
  restated for later bonuses and splits, consolidated profit sometimes including minority
  interest ([screener.in](screener.md#precision-and-meaning)). Its rows are dated by NSE's
  announcement when known, else by the regulatory deadline (an upper bound).
- **`public_at` is as good as NSE's announcement feed.** It is the broadcast time of the
  results announcement, to the second; a company that announced on its website or to the
  press first is not seen. When no announcement is found, the XBRL filing time (or the end of
  its day) is used: late, never early.
- **Insurers carry no figures**: their statements use a different taxonomy (premiums, not
  revenue). They get metadata rows (`insurance_skipped`) only.
- **EPS as filed.** NSE rows keep EPS as the company reported it at the time: a later bonus or
  split is not adjusted for, so `eps_yoy` across a split compares unadjusted figures.
- **Five fields.** Revenue, total income, net profit, basic and diluted EPS, and their year to
  date. Nothing from the balance sheet or cash flow, segments, or analyst estimates.
- **No audit of the companies' own errors.** A filing in the wrong unit is flagged
  (`unit_suspect`) only when it is 20x off the company's recent quarters; smaller errors pass.

"""The fetch step: everything the parse step reads, downloaded once into the raw cache.

NSE, per company of the universe: its Reg 33 and Integrated Filing listings, every XBRL document
they list for a period ending in [start, end] (under the basis rule), and the company's
announcements in a 4-day window around each filing (for `public_at`); once per run, the insurers'
listing. screener.in, per company: its consolidated page, and its standalone page when the basis
rule needs it; then, for a quarter only screener.in gives (`--source both`), NSE's announcements
from the quarter end to its deadline, in 4-day windows.

Incremental and resumable: a document is never fetched again once cached (any final status, 404
included); a listing or a screener.in page is fetched again only when older than `MAX_AGE` (new
filings appear in it); an announcement window only until it was fetched after it ended.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

from . import nse, screener
from .config import Config
from .growth import CONSOLIDATED_FIRST, by_rule
from .http import Client
from .nse import IST, LISTING_INSURANCE, LISTING_INTEGRATED, LISTING_REG33, Filing
from .raw import RawCache, Reuse, always, cached_get
from .timing import anchor_date, quarter_window, search_window
from .universe import Company

MAX_AGE = timedelta(hours=20)
WINDOW_DAYS = 4  # NSE answers [] for long announcement windows; 4 days worked every time
FINAL_AFTER = timedelta(hours=1)  # an announcement window is final once fetched this long after


def fresh(now: datetime, max_age: timedelta = MAX_AGE) -> Reuse:
    return lambda entry: entry.fetched_at >= now - max_age


def window_final(last: date) -> Reuse:
    """A window's announcements are final once fetched after its last day ended (IST)."""
    end = datetime.combine(last + timedelta(days=1), dtime(), tzinfo=IST) + FINAL_AFTER
    return lambda entry: entry.fetched_at >= end


def listing_urls(cfg: Config, symbol: str) -> list[tuple[str, str]]:
    src = cfg.sources
    return [
        (LISTING_REG33, nse.results_url(src, symbol)),
        (LISTING_INTEGRATED, nse.integrated_url(src, symbol)),
    ]


# --- reading what is cached -----------------------------------------------------------------


def _filing_order(filing: Filing) -> tuple[bool, datetime, str]:
    when = filing.created_at or filing.broadcast_at
    return (when is None, when or datetime.min.replace(tzinfo=UTC), filing.seq)


def company_filings(cache: RawCache, cfg: Config, company: Company) -> list[Filing]:
    """Every filing any cached answer of the company's listings ever showed (a filing that
    later leaves a listing still happened), one per XBRL URL, earliest first; filings without an
    XBRL are kept once per (listing, seq). A row whose ISIN names another company is left out."""
    filings: list[Filing] = []
    for listing, url in listing_urls(cfg, company.symbol):
        for entry in cache.history(url):
            if entry.status == 200:
                filings += nse.parse_listing(listing, cache.body(entry))
    out: dict[str, Filing] = {}
    for filing in sorted(filings, key=_filing_order):
        if filing.isin and company.isin and filing.isin != company.isin:
            continue
        key = filing.xbrl_url or f"{filing.listing}:{filing.seq}:{filing.period_end}"
        out.setdefault(key, filing)
    return list(out.values())


def insurance_filings(cache: RawCache, cfg: Config) -> list[Filing]:
    """The insurers' filings of every cached insurance listing."""
    found: dict[str, Filing] = {}
    prefix = cfg.sources.results_api + "?index=insurance"
    for url in cache.entries():
        if not url.startswith(prefix):
            continue
        for entry in cache.history(url):
            if entry.status == 200:
                for f in nse.parse_listing(LISTING_INSURANCE, cache.body(entry)):
                    found.setdefault(f.xbrl_url or f"{f.symbol}:{f.seq}", f)
    return sorted(found.values(), key=_filing_order)


def in_scope(filing: Filing, start: date, end: date) -> bool:
    return filing.xbrl_url is not None and start <= filing.period_end <= end


def wanted(filings: Iterable[Filing], start: date, end: date, rule: str) -> list[Filing]:
    """The filings whose documents the parse step reads."""
    return by_rule([f for f in filings if in_scope(f, start, end)], rule)


# --- the step -------------------------------------------------------------------------------


@dataclass
class FetchReport:
    companies: int = 0
    listings_fetched: int = 0
    listings_failed: list[str] = field(default_factory=list)
    documents: int = 0
    documents_fetched: int = 0
    documents_failed: int = 0
    announcement_windows: int = 0
    announcement_windows_fetched: int = 0
    announcement_windows_failed: int = 0
    screener_pages: int = 0
    screener_pages_fetched: int = 0
    screener_failed: list[str] = field(default_factory=list)
    requests: int = 0
    statuses: dict[int, int] = field(default_factory=dict)

    def ok(self) -> bool:
        return not (
            self.listings_failed
            or self.documents_failed
            or self.announcement_windows_failed
            or self.screener_failed
        )


Progress = Callable[[str], None]


def _say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


@dataclass
class NseFetch:
    cache: RawCache
    client: Client
    cfg: Config
    report: FetchReport
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def listings(self, company: Company) -> None:
        for listing, url in listing_urls(self.cfg, company.symbol):
            answer = cached_get(
                self.cache,
                self.client,
                url,
                referer=self.cfg.sources.results_page,
                reuse=fresh(self.now),
                valid=lambda body, kind=listing: nse.listing_ok(kind, body),
            )
            self.report.listings_fetched += answer.fetched
            if answer.status != 200:
                self.report.listings_failed.append(f"{company.symbol} {listing}")

    def insurance(self, start: date, today: date) -> None:
        url = nse.insurance_url(self.cfg.sources, start, today)
        answer = cached_get(
            self.cache,
            self.client,
            url,
            referer=self.cfg.sources.results_page,
            reuse=fresh(self.now),
            valid=lambda body: nse.listing_ok(LISTING_INSURANCE, body),
        )
        if answer.status != 200:
            self.report.listings_failed.append("insurance listing")

    def documents(self, filings: Sequence[Filing]) -> None:
        for filing in filings:
            assert filing.xbrl_url is not None
            self.report.documents += 1
            answer = cached_get(self.cache, self.client, filing.xbrl_url, reuse=always)
            self.report.documents_fetched += answer.fetched
            self.report.documents_failed += answer.status == 0

    def window(self, symbol: str, first: date, last: date, today: date) -> None:
        if first > today:
            return
        url = nse.announcements_url(self.cfg.sources, symbol, first, min(last, today))
        answer = cached_get(
            self.cache,
            self.client,
            url,
            referer=self.cfg.sources.announcements_page,
            reuse=window_final(last),
            valid=lambda body: nse.listing_ok(LISTING_REG33, body),  # a JSON list
        )
        self.report.announcement_windows += 1
        self.report.announcement_windows_fetched += answer.fetched
        self.report.announcement_windows_failed += answer.status != 200

    def announcements(self, symbol: str, filings: Iterable[Filing], today: date) -> None:
        anchors = sorted({a for a in (anchor_date(f) for f in filings) if a is not None})
        for anchor in anchors:
            first, last = search_window(anchor)
            self.window(symbol, first, last, today)

    def quarter_announcements(self, symbol: str, period_end: date, today: date) -> None:
        first, last = quarter_window(period_end)
        for a, b in chunks(first, last, WINDOW_DAYS):
            self.window(symbol, a, b, today)


def chunks(first: date, last: date, days: int) -> list[tuple[date, date]]:
    out, day = [], first
    while day <= last:
        stop = min(day + timedelta(days=days - 1), last)
        out.append((day, stop))
        day = stop + timedelta(days=1)
    return out


def fetch_nse(
    fetcher: NseFetch,
    companies: Sequence[Company],
    start: date,
    end: date,
    today: date,
    *,
    rule: str = CONSOLIDATED_FIRST,
    announcements: bool = True,
    say: Progress = _say,
) -> None:
    fetcher.insurance(start, today)
    insurers = insurance_filings(fetcher.cache, fetcher.cfg)
    for n, company in enumerate(companies, 1):
        fetcher.listings(company)
        filings = company_filings(fetcher.cache, fetcher.cfg, company)
        filings += [f for f in insurers if f.symbol == company.symbol]
        chosen = wanted(filings, start, end, rule)
        fetcher.documents(chosen)
        if announcements:
            fetcher.announcements(company.symbol, chosen, today)
        fetcher.report.companies = n
        if n % 10 == 0 or n == len(companies):
            say(f"nse {n}/{len(companies)} companies, {fetcher.client.requests} requests")


@dataclass
class ScreenerFetch:
    cache: RawCache
    client: Client
    cfg: Config
    report: FetchReport
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def robots(self) -> bytes:
        answer = cached_get(
            self.cache,
            self.client,
            screener.robots_url(self.cfg.screener.base),
            reuse=fresh(self.now),
        )
        return answer.body if answer.status == 200 else b""

    def page(self, robots: bytes, symbol: str, basis: str) -> list[screener.Quarter] | None:
        url = screener.page_url(self.cfg.screener.base, symbol, basis)
        if not screener.allowed(robots, url):
            self.report.screener_failed.append(f"{symbol} {basis}: robots.txt disallows")
            return None
        answer = cached_get(self.cache, self.client, url, reuse=fresh(self.now))
        self.report.screener_pages += 1
        self.report.screener_pages_fetched += answer.fetched
        if answer.status == 404:
            return []  # screener.in does not know the symbol: nothing to fill
        if answer.status != 200:
            self.report.screener_failed.append(f"{symbol} {basis}: HTTP {answer.status}")
            return None
        return screener.parse_page(answer.body)


def read_standalone(rule: str, consolidated: list[screener.Quarter] | None) -> bool:
    """Whether to read the standalone page too: always under `both`; under
    `consolidated-first` only when the consolidated page has no quarters."""
    return rule != CONSOLIDATED_FIRST or not consolidated


def fetch_screener(
    fetcher: ScreenerFetch,
    companies: Sequence[Company],
    *,
    rule: str = CONSOLIDATED_FIRST,
    say: Progress = _say,
) -> None:
    robots = fetcher.robots()
    if not robots:
        fetcher.report.screener_failed.append("robots.txt unavailable: nothing asked")
        return
    for n, company in enumerate(companies, 1):
        consolidated = fetcher.page(robots, company.symbol, "consolidated")
        if read_standalone(rule, consolidated):
            fetcher.page(robots, company.symbol, "standalone")
        if n % 10 == 0 or n == len(companies):
            say(f"screener {n}/{len(companies)} companies, {fetcher.client.requests} requests")


@dataclass(frozen=True)
class PageQuarter:
    """A quarter as one screener.in page showed it, and that answer's provenance."""

    quarter: screener.Quarter
    url: str
    sha256: str
    fetched_at: datetime


def screener_quarters(cache: RawCache, cfg: Config, company: Company) -> list[PageQuarter]:
    """Every quarter every cached answer of the company's pages showed, oldest answer first."""
    out = []
    for basis in ("consolidated", "standalone"):
        url = screener.page_url(cfg.screener.base, company.symbol, basis)
        for entry in cache.history(url):
            if entry.status == 200:
                quarters = screener.parse_page(cache.body(entry))
                out += [PageQuarter(q, url, entry.sha256, entry.fetched_at) for q in quarters]
    return sorted(out, key=lambda p: p.fetched_at)


def gap_quarters(
    filings: Sequence[Filing],
    quarters: Sequence[PageQuarter],
    start: date,
    end: date,
) -> list[date]:
    """The period ends in [start, end] that screener.in shows and NSE lists no XBRL for."""
    listed = {f.period_end for f in filings if f.xbrl_url}
    shown = {q.quarter.period_end for q in quarters}
    return sorted(e for e in shown if start <= e <= end and e not in listed)


def fetch_gap_announcements(
    fetcher: NseFetch,
    screener_cache: RawCache,
    companies: Sequence[Company],
    start: date,
    end: date,
    today: date,
) -> int:
    """NSE's announcements for each quarter only screener.in gives; the number of quarters."""
    count = 0
    insurers = {f.symbol for f in insurance_filings(fetcher.cache, fetcher.cfg)}
    for company in companies:
        if company.symbol in insurers:
            continue  # insurers get metadata rows only: nothing to date
        filings = company_filings(fetcher.cache, fetcher.cfg, company)
        shown = screener_quarters(screener_cache, fetcher.cfg, company)
        for period_end in gap_quarters(filings, shown, start, end):
            fetcher.quarter_announcements(company.symbol, period_end, today)
            count += 1
    return count

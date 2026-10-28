"""The parse step: the raw cache into `out/results` (every version of every quarter) and
`out/filings.csv` (every filing considered, with its outcome). It reads only the cache and
rebuilds both files whole, so a rerun gives the same versions plus any new ones: the cache never
loses an answer, so no version is ever lost. The rules are in docs/parser-rules.md and
docs/point-in-time.md.

Per company, every XBRL its listings give for a period ending in [start, end] under the basis
rule (one document once, by URL):

- a document not fetched, not a 200, or unreadable is excluded with its reason;
- the period and basis are the document's (the listing's basis where the document states none);
  a period that differs from the listing's is kept and flagged (`period_mismatch`);
- an insurer (the insurance listing, or an insurance taxonomy) is a metadata row,
  `format=insurance_skipped`, without figures;
- a Q4 document with only the year's figures gets Q4 = year - nine months (the document's nine
  months, else the Q3 row's year to date on the same basis), `q4_derived`;
- per (period_end, basis), filings take versions in filing order; a filing whose figures equal
  the latest version's adds none (`same_figures`); a later version is a revision;
- `public_at` and `xbrl_at` follow `timing.py`.

Then each quarter screener.in shows on a basis for which NSE has no row becomes a
`source=screener` row (`public_at`: the quarter's NSE results announcement when the cache holds
it, else the regulatory deadline, flagged estimated); a later page showing other figures for it
is a new version, public when that page was fetched.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from . import nse, tables
from .config import Config
from .fetch import (
    PageQuarter,
    company_filings,
    insurance_filings,
    screener_quarters,
    wanted,
)
from .growth import CONSOLIDATED, CONSOLIDATED_FIRST, by_rule, quarter_ends_before
from .nse import LISTING_INSURANCE, Announcement, Filing
from .raw import RawCache
from .timing import (
    FiledAt,
    PublicAt,
    anchor_date,
    deadline,
    match_announcement,
    public_at,
    quarter_announcement,
    results_announcements,
    xbrl_at,
)
from .universe import Company
from .xbrl import INSURANCE, Figures, Parsed, XbrlError, quarter_start
from .xbrl import parse as parse_xbrl

SOURCE_NSE = "nse"
SOURCE_SCREENER = "screener"
FORMAT_SCREENER = "screener"
FIGURES = ("revenue", "total_income", "net_profit", "eps_basic", "eps_diluted")

T, D, TS, M, N, B = tables.TEXT, tables.DAY, tables.TIME, tables.MONEY, tables.INT, tables.BOOL
RESULTS_SCHEMA: tables.Schema = [
    ("id", T), ("symbol", T), ("isin", T), ("company", T),
    ("period_start", D), ("period_end", D), ("fiscal_year", T), ("fiscal_quarter", T),
    ("basis", T), ("source", T), ("format", T),
    ("revenue", M), ("total_income", M), ("net_profit", M), ("eps_basic", M), ("eps_diluted", M),
    ("ytd_start", D), ("ytd_revenue", M), ("ytd_total_income", M), ("ytd_net_profit", M),
    ("ytd_eps_basic", M), ("ytd_eps_diluted", M),
    ("q4_derived", B), ("eps_corrected", B), ("period_mismatch", B), ("listing_period_end", D),
    ("public_at", TS), ("public_at_source", T), ("public_at_estimated", B),
    ("xbrl_at", TS), ("xbrl_at_estimated", B),
    ("version", N), ("revision", B), ("supersedes_id", T),
    ("listing", T), ("listing_seq", T), ("source_url", T), ("sha256", T),
]  # fmt: skip
FILINGS_SCHEMA: tables.Schema = [
    ("symbol", T), ("listing", T), ("seq", T), ("listing_period_end", D), ("period_end", D),
    ("basis", T), ("format", T), ("markers", T), ("url", T), ("result", T), ("reason", T),
    ("version", N), ("q4_derived", B), ("period_mismatch", B), ("public_at_source", T),
]  # fmt: skip


def fiscal(period_end: date) -> tuple[str, str]:
    """India's financial year (April to March) and quarter of a quarter end: 2024-12-31 is
    FY2025 Q3."""
    year = period_end.year + 1 if period_end.month >= 4 else period_end.year
    quarter = {6: "Q1", 9: "Q2", 12: "Q3", 3: "Q4"}.get(period_end.month, "")
    return f"FY{year}", quarter


@dataclass
class Outcome:
    symbol: str
    listing: str
    seq: str
    listing_period_end: date | None
    period_end: date | None
    basis: str
    format: str
    markers: str
    url: str
    result: str  # stored | same_figures | insurance_skipped | excluded
    reason: str = ""
    version: int = 0
    q4_derived: bool = False
    period_mismatch: bool = False
    public_at_source: str = ""


@dataclass(frozen=True)
class Candidate:
    filing: Filing
    parsed: Parsed | None  # None for an insurance-listing row
    basis: str
    period_end: date
    sha256: str
    filed: FiledAt | None


@dataclass
class Held:
    """The latest version of one (period_end, basis, source)."""

    id: str
    version: int
    quarter: tuple[Any, ...]
    ytd: tuple[Any, ...]
    ytd_start: date | None
    ytd_figures: Figures | None
    public_at: datetime
    public_at_source: str


@dataclass
class ParseReport:
    companies: int = 0
    rows: int = 0
    screener_rows: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)


def announcement_index(cache: RawCache, cfg: Config) -> dict[str, list[Announcement]]:
    """Every cached announcement window's results announcements, by symbol, earliest first."""
    items: list[Announcement] = []
    for url, entry in cache.entries().items():
        if url.startswith(cfg.sources.announcements_api) and entry.status == 200:
            items += nse.parse_announcements(cache.body(entry))
    by_symbol: dict[str, list[Announcement]] = {}
    for item in results_announcements(items):
        by_symbol.setdefault(item.symbol, []).append(item)
    return by_symbol


def _figures_dict(prefix: str, figures: Figures | None) -> dict[str, Any]:
    values = asdict(figures) if figures is not None else dict.fromkeys(FIGURES)
    return {f"{prefix}{k}": v for k, v in values.items()}


def _key(figures: Figures | None) -> tuple[Any, ...]:
    return figures.key() if figures is not None else (None,) * len(FIGURES)


class CompanyParse:
    """One company's rows: its NSE filings in order, then what screener.in fills."""

    def __init__(
        self, cache: RawCache, company: Company, announced: Sequence[Announcement]
    ) -> None:
        self.cache = cache
        self.company = company
        self.items = list(announced)
        self.latest: dict[tuple[date, str, str], Held] = {}
        self.rows: list[dict[str, Any]] = []
        self.outcomes: list[Outcome] = []
        self.seen_sha: set[str] = set()

    # --- NSE --------------------------------------------------------------------------------

    def nse(self, filings: Sequence[Filing]) -> None:
        candidates: list[Candidate] = []
        for filing in filings:
            got = self._candidate(filing)
            if isinstance(got, Outcome):
                self.outcomes.append(got)
            elif got is not None:
                candidates.append(got)
        candidates.sort(key=lambda c: (c.period_end, c.basis, _filed_order(c), c.filing.seq))
        for candidate in candidates:
            self.outcomes.append(self._store(candidate))

    def _outcome(self, filing: Filing, **values: Any) -> Outcome:
        return Outcome(
            symbol=self.company.symbol,
            listing=filing.listing,
            seq=filing.seq,
            listing_period_end=filing.period_end,
            period_end=values.pop("period_end", None),
            basis=values.pop("basis", filing.basis),
            format=values.pop("format", ""),
            markers=filing.markers,
            url=filing.xbrl_url or "",
            **values,
        )

    def _candidate(self, filing: Filing) -> Candidate | Outcome | None:
        assert filing.xbrl_url is not None
        entry = self.cache.entry(filing.xbrl_url)
        if entry is None:
            return self._outcome(filing, result="excluded", reason="not_fetched")
        if entry.status != 200:
            return self._outcome(filing, result="excluded", reason=f"xbrl_http_{entry.status}")
        if entry.sha256 in self.seen_sha:  # the same document under another URL
            return None
        self.seen_sha.add(entry.sha256)
        parsed: Parsed | None = None
        if filing.listing != LISTING_INSURANCE:
            try:
                parsed = parse_xbrl(self.cache.body(entry))
            except XbrlError as exc:
                return self._outcome(filing, result="excluded", reason=str(exc))
        basis = (parsed.basis if parsed else "") or filing.basis
        if not basis:
            return self._outcome(filing, result="excluded", reason="basis_unknown")
        period_end = (parsed.period_end if parsed else None) or filing.period_end
        return Candidate(filing, parsed, basis, period_end, entry.sha256, xbrl_at(filing))

    def _quarter(self, c: Candidate) -> tuple[Figures | None, bool]:
        """The quarter's figures and whether they are derived (Q4 = year less nine months);
        (None, True) when Q4 must be derived and the nine months are not known."""
        parsed = c.parsed
        assert parsed is not None
        if parsed.quarter is not None or parsed.annual is None:
            return parsed.quarter, False
        nine = parsed.nine_month or self._nine_months(c.period_end, c.basis, parsed.fy_start)
        return (None if nine is None else parsed.annual.minus(nine)), True

    def _nine_months(self, period_end: date, basis: str, fy_start: date | None) -> Figures | None:
        q3_end = quarter_ends_before(period_end, 1)[0]
        held = self.latest.get((q3_end, basis, SOURCE_NSE))
        if held is None or held.ytd_figures is None or held.ytd_figures.revenue is None:
            return None
        if fy_start is not None and held.ytd_start not in (None, fy_start):
            return None
        return held.ytd_figures

    def _store(self, c: Candidate) -> Outcome:
        insurer = c.parsed is None or c.parsed.kind.format == INSURANCE
        fmt = INSURANCE if insurer else c.parsed.kind.format  # type: ignore[union-attr]
        base = {"period_end": c.period_end, "basis": c.basis, "format": fmt}
        quarter, q4 = (None, False) if insurer else self._quarter(c)
        if q4 and quarter is None:
            return self._outcome(
                c.filing, result="excluded", reason="q4_nine_month_missing", **base
            )
        ytd = None if c.parsed is None else (c.parsed.annual if q4 else c.parsed.ytd)
        held = self.latest.get((c.period_end, c.basis, SOURCE_NSE))
        if held is not None and (_key(quarter), _key(ytd)) == (held.quarter, held.ytd):
            return self._outcome(c.filing, result="same_figures", **base)
        version = 1 if held is None else held.version + 1
        when = public_at(version, self._announced(c) if version == 1 else None, c.filed)
        if when is None:
            return self._outcome(c.filing, result="excluded", reason="no_time", **base)
        mismatch = c.period_end != c.filing.period_end
        row = self._row(c, fmt, quarter, ytd, q4, mismatch, when, version, held)
        self._add(row, (c.period_end, c.basis, SOURCE_NSE), quarter, ytd)
        return self._outcome(
            c.filing,
            result=INSURANCE if insurer else "stored",
            version=version,
            q4_derived=q4,
            period_mismatch=mismatch,
            public_at_source=when.source,
            **base,
        )

    def _announced(self, c: Candidate) -> datetime | None:
        anchor = anchor_date(c.filing)
        match = match_announcement(self.items, anchor, c.period_end) if anchor else None
        return match.at if match else None

    def _common(self, period_end: date, basis: str, source: str, version: int) -> dict[str, Any]:
        fy, fq = fiscal(period_end)
        return {
            "id": f"{self.company.symbol}:{period_end}:{basis}:{source}:v{version}",
            "symbol": self.company.symbol,
            "isin": self.company.isin,
            "company": self.company.name,
            "period_end": period_end,
            "fiscal_year": fy,
            "fiscal_quarter": fq,
            "basis": basis,
            "source": source,
            "version": version,
            "revision": version > 1,
        }

    def _row(
        self,
        c: Candidate,
        fmt: str,
        quarter: Figures | None,
        ytd: Figures | None,
        q4: bool,
        mismatch: bool,
        when: PublicAt,
        version: int,
        held: Held | None,
    ) -> dict[str, Any]:
        parsed = c.parsed
        return {
            **self._common(c.period_end, c.basis, SOURCE_NSE, version),
            "period_start": (parsed.period_start if parsed else None)
            or quarter_start(c.period_end),
            "format": fmt,
            **_figures_dict("", quarter),
            "ytd_start": parsed.ytd_start if parsed and ytd is not None else None,
            **_figures_dict("ytd_", ytd),
            "q4_derived": q4,
            "eps_corrected": bool(parsed and parsed.eps_corrected),
            "period_mismatch": mismatch,
            "listing_period_end": c.filing.period_end if mismatch else None,
            "public_at": when.at,
            "public_at_source": when.source,
            "public_at_estimated": when.estimated,
            "xbrl_at": c.filed.at if c.filed else None,
            "xbrl_at_estimated": c.filed.estimated if c.filed else False,
            "revision": version > 1 or c.filing.revision,
            "supersedes_id": held.id if held else "",
            "listing": c.filing.listing,
            "listing_seq": c.filing.seq,
            "source_url": c.filing.xbrl_url or "",
            "sha256": c.sha256,
        }

    def _add(
        self,
        row: dict[str, Any],
        key: tuple[date, str, str],
        quarter: Figures | None,
        ytd: Figures | None,
    ) -> None:
        self.rows.append(row)
        self.latest[key] = Held(
            row["id"],
            row["version"],
            _key(quarter),
            _key(ytd),
            row.get("ytd_start"),
            ytd,
            row["public_at"],
            row["public_at_source"],
        )

    def nse_consolidated(self) -> set[date]:
        return {e for e, b, s in self.latest if b == CONSOLIDATED and s == SOURCE_NSE}

    # --- screener.in ------------------------------------------------------------------------

    def screener(self, quarters: Sequence[PageQuarter], start: date, end: date) -> int:
        """Rows for the quarters only screener.in gives; the number of rows added."""
        used = {
            h.public_at
            for (_e, _b, s), h in self.latest.items()
            if s == SOURCE_NSE and h.public_at_source == "announcement"
        }
        added = 0
        for pq in quarters:
            q = pq.quarter
            if not start <= q.period_end <= end:
                continue
            if (q.period_end, q.basis, SOURCE_NSE) in self.latest:
                continue  # NSE gives it: screener.in only cross-checks it
            figures = Figures(q.revenue, None, q.net_profit, q.eps_basic, None)
            key = (q.period_end, q.basis, SOURCE_SCREENER)
            held = self.latest.get(key)
            if held is not None and held.quarter == _key(figures):
                continue
            version = 1 if held is None else held.version + 1
            when = (
                self._screener_public_at(q.period_end, used)
                if version == 1
                else PublicAt(pq.fetched_at, "observed", True)  # first seen in this page
            )
            row = {
                **self._common(q.period_end, q.basis, SOURCE_SCREENER, version),
                "period_start": quarter_start(q.period_end),
                "format": FORMAT_SCREENER,
                **_figures_dict("", figures),
                "q4_derived": False,
                "eps_corrected": False,
                "period_mismatch": False,
                "public_at": when.at,
                "public_at_source": when.source,
                "public_at_estimated": when.estimated,
                "xbrl_at_estimated": False,
                "supersedes_id": held.id if held else "",
                "listing": SOURCE_SCREENER,
                "listing_seq": "",
                "source_url": pq.url,
                "sha256": pq.sha256,
            }
            self._add(row, key, figures, None)
            added += 1
        return added

    def _screener_public_at(self, period_end: date, used: set[datetime]) -> PublicAt:
        match = quarter_announcement(self.items, period_end, used)
        if match is not None:
            used.add(match.at)
            return PublicAt(match.at, "announcement", False)
        return PublicAt(deadline(period_end), "deadline", True)


def _filed_order(c: Candidate) -> tuple[bool, str]:
    return (c.filed is None, c.filed.at.isoformat() if c.filed else "")


def screener_by_rule(
    quarters: Sequence[PageQuarter], rule: str, consolidated_elsewhere: Iterable[date]
) -> list[PageQuarter]:
    """The screener.in quarters the basis rule keeps, a quarter NSE has consolidated figures for
    (stored or listed) counting as consolidated."""
    kept = {id(q) for q in by_rule([p.quarter for p in quarters], rule, consolidated_elsewhere)}
    return [p for p in quarters if id(p.quarter) in kept]


def parse_company(
    nse_cache: RawCache,
    screener_cache: RawCache,
    cfg: Config,
    company: Company,
    *,
    insurers: Sequence[Filing],
    announced: Sequence[Announcement],
    start: date,
    end: date,
    rule: str = CONSOLIDATED_FIRST,
) -> CompanyParse:
    work = CompanyParse(nse_cache, company, announced)
    filings = company_filings(nse_cache, cfg, company)
    filings += [f for f in insurers if f.symbol == company.symbol]
    chosen = wanted(filings, start, end, rule)
    work.nse(chosen)
    if any(o.result == INSURANCE for o in work.outcomes):
        return work  # insurers: metadata rows only
    listed = {f.period_end for f in chosen if f.basis == CONSOLIDATED}
    quarters = screener_by_rule(
        screener_quarters(screener_cache, cfg, company), rule, work.nse_consolidated() | listed
    )
    work.screener(quarters, start, end)
    return work


def parse(
    nse_cache: RawCache,
    screener_cache: RawCache,
    cfg: Config,
    companies: Sequence[Company],
    start: date,
    end: date,
    rule: str = CONSOLIDATED_FIRST,
) -> tuple[list[dict[str, Any]], list[Outcome], ParseReport]:
    announced = announcement_index(nse_cache, cfg)
    insurers = insurance_filings(nse_cache, cfg)
    rows: list[dict[str, Any]] = []
    outcomes: list[Outcome] = []
    report = ParseReport()
    for company in companies:
        work = parse_company(
            nse_cache,
            screener_cache,
            cfg,
            company,
            insurers=insurers,
            announced=announced.get(company.symbol, []),
            start=start,
            end=end,
            rule=rule,
        )
        rows += work.rows
        outcomes += work.outcomes
        report.companies += 1
    report.rows = len(rows)
    report.screener_rows = sum(1 for r in rows if r["source"] == SOURCE_SCREENER)
    for o in outcomes:
        report.outcomes[o.result] = report.outcomes.get(o.result, 0) + 1
        if o.reason:
            report.excluded[o.reason] = report.excluded.get(o.reason, 0) + 1
    rows.sort(key=lambda r: (r["symbol"], r["period_end"], r["basis"], r["source"], r["version"]))
    return rows, outcomes, report


def outcome_rows(outcomes: Iterable[Outcome]) -> list[dict[str, Any]]:
    return [asdict(o) for o in outcomes]

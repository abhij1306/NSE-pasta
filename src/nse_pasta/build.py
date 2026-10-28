"""The build step: from `out/results` to the derived tables. Reads only `out/results.csv` and
the screener.in cache; rewrites each table whole.

    growth      one row per result row: that quarter's year-on-year growth, and whether the row
                is unit-suspect, both as known when the row became public
    coverage    per symbol and calendar year: quarters due, found on NSE, filled from
                screener.in, missing
    crosscheck  NSE vs screener.in, for quarters both give on the same basis
    asof=<ts>   (`as_of`) the table as it could have been known at <ts>: the latest version of
                each quarter public by then, with growth as known then
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from . import tables
from .config import Config
from .fetch import screener_quarters
from .growth import (
    CONSOLIDATED_FIRST,
    INSURANCE,
    Growth,
    ResultRow,
    growth,
    growth_rows,
    known_at,
)
from .nse import IST
from .parse import RESULTS_SCHEMA, SOURCE_NSE, SOURCE_SCREENER
from .raw import RawCache
from .screener import CRORE
from .timing import deadline
from .universe import Company

T, D, TS, M, R, N, B = (
    tables.TEXT, tables.DAY, tables.TIME, tables.MONEY, tables.RATIO, tables.INT, tables.BOOL,
)  # fmt: skip
GROWTH_COLUMNS: tables.Schema = [
    ("growth_basis", T), ("prior_period_end", D), ("prior_id", T),
    ("sales_yoy", R), ("eps_yoy", R), ("turnaround", B), ("growth_reason", T),
]  # fmt: skip
GROWTH_SCHEMA: tables.Schema = [
    ("result_id", T), ("symbol", T), ("period_end", D), ("fiscal_year", T),
    ("fiscal_quarter", T), ("basis", T), ("source", T), ("version", N), ("as_of", TS),
    ("unit_suspect", B), ("current_id", T), *GROWTH_COLUMNS,
]  # fmt: skip
ASOF_SCHEMA: tables.Schema = [
    ("as_of", TS), *RESULTS_SCHEMA, ("unit_suspect", B), *GROWTH_COLUMNS,
]  # fmt: skip
COVERAGE_SCHEMA: tables.Schema = [
    ("symbol", T), ("year", N), ("quarters", N), ("due", N), ("nse", N),
    ("nse_consolidated", N), ("screener", N), ("insurer", N), ("missing", N),
    ("missing_quarters", T),
]  # fmt: skip
CROSSCHECK_SCHEMA: tables.Schema = [
    ("symbol", T), ("period_end", D), ("basis", T),
    ("nse_revenue", M), ("screener_revenue", M), ("revenue_agrees", B),
    ("nse_net_profit", M), ("screener_net_profit", M), ("net_profit_agrees", B),
    ("nse_eps_basic", M), ("screener_eps_basic", M), ("eps_agrees", B),
]  # fmt: skip


def result_row(row: dict[str, Any]) -> ResultRow:
    return ResultRow(
        row["id"],
        row["period_end"],
        row["basis"],
        row["source"],
        row["format"],
        row["version"],
        row["public_at"],
        row["revenue"],
        row["eps_basic"],
    )


def by_symbol(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[row["symbol"]].append(row)
    return out


def _growth_columns(found: Growth, known: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prior = known.get(found.prior_id or "")
    return {
        "growth_basis": found.basis or "",
        "prior_period_end": prior["period_end"] if prior else None,
        "prior_id": found.prior_id or "",
        "sales_yoy": found.sales_yoy,
        "eps_yoy": found.eps_yoy,
        "turnaround": found.turnaround,
        "growth_reason": found.reason or "",
    }


def growth_table(rows: Sequence[dict[str, Any]], rule: str = CONSOLIDATED_FIRST) -> list[dict]:
    out = []
    for company_rows in by_symbol(rows).values():
        index = {r["id"]: r for r in company_rows}
        for g in growth_rows([result_row(r) for r in company_rows], rule):
            row = index[g.row.id]
            out.append(
                {
                    "result_id": row["id"],
                    "symbol": row["symbol"],
                    "period_end": row["period_end"],
                    "fiscal_year": row["fiscal_year"],
                    "fiscal_quarter": row["fiscal_quarter"],
                    "basis": row["basis"],
                    "source": row["source"],
                    "version": row["version"],
                    "as_of": row["public_at"],
                    "unit_suspect": g.unit_suspect,
                    "current_id": g.growth.current_id or "",
                    **_growth_columns(g.growth, index),
                }
            )
    return out


def as_of(
    rows: Sequence[dict[str, Any]],
    growth_rows_: Sequence[dict[str, Any]],
    ts: datetime,
    rule: str = CONSOLIDATED_FIRST,
) -> list[dict[str, Any]]:
    """Each company's quarters as known at `ts`: only rows public at or before `ts`, the latest
    version of each, NSE over screener.in, under the basis rule; growth as known at `ts` (a row
    flagged unit-suspect by then is left out of it)."""
    suspect = {g["result_id"] for g in growth_rows_ if g["unit_suspect"] and g["as_of"] <= ts}
    out = []
    for company_rows in by_symbol(rows).values():
        index = {r["id"]: r for r in company_rows}
        known = known_at([result_row(r) for r in company_rows], ts, rule)
        for key in sorted(known):
            row = index[known[key].id]
            found = growth(known, row["period_end"], suspect)
            out.append(
                {
                    "as_of": ts,
                    **row,
                    "unit_suspect": row["id"] in suspect,
                    **_growth_columns(found, index),
                }
            )
    return out


def parse_as_of(text: str) -> datetime:
    """`2025-06-30` (the end of that day, IST) or `2025-06-30T15:30` (IST unless an offset is
    given) as an aware datetime."""
    text = text.strip()
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time(23, 59, 59), tzinfo=IST)
    found = datetime.fromisoformat(text)
    return found if found.tzinfo else found.replace(tzinfo=IST)


def as_of_stem(ts: datetime) -> str:
    return f"asof={ts.astimezone(IST):%Y-%m-%dT%H%M}"


# --- coverage -------------------------------------------------------------------------------


def quarter_ends(start: date, end: date) -> list[date]:
    out = []
    year, month = start.year, ((start.month - 1) // 3 + 1) * 3
    while True:
        last = date(year, month, 31 if month in (3, 12) else 30)
        if last > end:
            return out
        if last >= start:
            out.append(last)
        year, month = (year + 1, 3) if month == 12 else (year, month + 3)


@dataclass
class Coverage:
    rows: list[dict[str, Any]] = field(default_factory=list)
    by_year: dict[int, Counter] = field(default_factory=lambda: defaultdict(Counter))


def coverage(
    companies: Sequence[Company],
    rows: Sequence[dict[str, Any]],
    start: date,
    end: date,
    now: datetime,
) -> Coverage:
    """Per company and calendar year of the period end: quarters in range that have ended,
    those due (results deadline passed), with an NSE row, with a consolidated NSE row, with a
    screener.in row only, an insurer's metadata row, and due quarters with none."""
    found = by_symbol(rows)
    cov = Coverage()
    ended = [q for q in quarter_ends(start, min(end, now.date())) if q < now.date()]
    for company in companies:
        have: dict[date, set[str]] = defaultdict(set)
        for r in found.get(company.symbol, []):
            tag = r["source"] if r["format"] != INSURANCE else "insurer"
            have[r["period_end"]].add(tag)
            if tag == SOURCE_NSE and r["basis"] == "consolidated":
                have[r["period_end"]].add("nse_consolidated")
        for year in sorted({q.year for q in ended}):
            quarters = [q for q in ended if q.year == year]
            c = Counter(quarters=len(quarters))
            missing = []
            for q in quarters:
                due = deadline(q) <= now
                tags = have.get(q, set())
                c["due"] += due
                c["nse"] += SOURCE_NSE in tags
                c["nse_consolidated"] += "nse_consolidated" in tags
                c["screener"] += SOURCE_SCREENER in tags and SOURCE_NSE not in tags
                c["insurer"] += "insurer" in tags
                if due and not tags:
                    missing.append(q.isoformat())
            c["missing"] = len(missing)
            cov.rows.append(
                {"symbol": company.symbol, "year": year, **c, "missing_quarters": " ".join(missing)}
            )
            cov.by_year[year].update(c)
    return cov


# --- cross-check ----------------------------------------------------------------------------


def _agrees(a: Decimal | None, b: Decimal | None, slack: Decimal) -> bool | None:
    if a is None or b is None:
        return None
    return abs(a - b) <= max(abs(a) * Decimal("0.01"), slack)


def crosscheck(
    screener_cache: RawCache,
    cfg: Config,
    companies: Sequence[Company],
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """NSE's latest version of each quarter against screener.in's latest page, same basis.
    Money agrees within 1% or 1 crore (screener.in shows crore, rounded); EPS within 1% or
    5 paise."""
    latest: dict[tuple[str, date, str], dict[str, Any]] = {}
    for r in rows:
        if r["source"] == SOURCE_NSE and r["format"] != INSURANCE:
            key = (r["symbol"], r["period_end"], r["basis"])
            if key not in latest or r["version"] > latest[key]["version"]:
                latest[key] = r
    out = []
    for company in companies:
        shown = {}
        for pq in screener_quarters(screener_cache, cfg, company):  # oldest page first
            shown[(pq.quarter.period_end, pq.quarter.basis)] = pq.quarter
        for (period_end, basis), q in sorted(shown.items()):
            nse_row = latest.get((company.symbol, period_end, basis))
            if nse_row is None:
                continue
            out.append(
                {
                    "symbol": company.symbol,
                    "period_end": period_end,
                    "basis": basis,
                    "nse_revenue": nse_row["revenue"],
                    "screener_revenue": q.revenue,
                    "revenue_agrees": _agrees(nse_row["revenue"], q.revenue, CRORE),
                    "nse_net_profit": nse_row["net_profit"],
                    "screener_net_profit": q.net_profit,
                    "net_profit_agrees": _agrees(nse_row["net_profit"], q.net_profit, CRORE),
                    "nse_eps_basic": nse_row["eps_basic"],
                    "screener_eps_basic": q.eps_basic,
                    "eps_agrees": _agrees(nse_row["eps_basic"], q.eps_basic, Decimal("0.05")),
                }
            )
    return out


def crosscheck_counts(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for name in ("revenue_agrees", "net_profit_agrees", "eps_agrees"):
        values = Counter(r[name] for r in rows)
        counts[name.removesuffix("_agrees")] = {
            "agree": values[True],
            "differ": values[False],
            "not_comparable": values[None],
        }
    return counts

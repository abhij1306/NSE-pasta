"""NSE's results listings and announcements: the URLs asked and their answers as plain values.

    corporates-financial-results   Reg 33 filings, to the Dec 2024 quarter (`index=equities`,
                                   `period=Quarterly`); insurers under `index=insurance`
    integrated-filing-results      Integrated Filing (`type=Integrated Filing- Financials`), from
                                   the Mar 2025 quarter; the two listings share no quarter
    corporate-announcements        what a company broadcast, and when (`public_at`)

The JSON endpoints answer only a session that loaded the results page first (cookies). Pure:
bytes in, values out; `fetch.py` asks, `parse.py` reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from .config import Sources

IST = timezone(timedelta(hours=5, minutes=30), "IST")
INTEGRATED_FINANCIALS = "Integrated Filing- Financials"
INTEGRATED_PAGE_SIZE = 500  # the endpoint pages by 20 unless asked; no company has 500 rows

LISTING_REG33 = "reg33"
LISTING_INSURANCE = "insurance"
LISTING_INTEGRATED = "integrated"


# --- URLs -----------------------------------------------------------------------------------


def _url(base: str, params: dict[str, str]) -> str:
    return f"{base}?{urlencode(params)}"


def dmy(day: date) -> str:
    return day.strftime("%d-%m-%Y")


def results_url(src: Sources, symbol: str) -> str:
    return _url(src.results_api, {"index": "equities", "symbol": symbol, "period": "Quarterly"})


def integrated_url(src: Sources, symbol: str) -> str:
    params = {
        "index": "equities",
        "symbol": symbol,
        "type": INTEGRATED_FINANCIALS,
        "size": str(INTEGRATED_PAGE_SIZE),
    }
    return _url(src.integrated_api, params)


def insurance_url(src: Sources, start: date, end: date) -> str:
    """Every insurer's Reg 33 filings broadcast in [start, end] (the insurance index is small)."""
    params = {"index": "insurance", "period": "Quarterly", "from_date": dmy(start)}
    return _url(src.results_api, params | {"to_date": dmy(end)})


def announcements_url(src: Sources, symbol: str, start: date, end: date) -> str:
    params = {"index": "equities", "symbol": symbol, "from_date": dmy(start), "to_date": dmy(end)}
    return _url(src.announcements_api, params)


# --- listings -------------------------------------------------------------------------------

NO_XBRL_SUFFIXES = ("/-", "/null")


@dataclass(frozen=True)
class Filing:
    """One results filing of a listing, normalised across the endpoints."""

    listing: str  # reg33 | insurance | integrated
    symbol: str
    isin: str  # "" when the listing does not give it (integrated)
    seq: str
    period_end: date  # the listing's period end (the document's wins when they differ)
    basis: str  # standalone | consolidated | "" (not stated)
    broadcast_at: datetime | None  # the listing's broadcast time, to the second
    created_at: datetime | None  # integrated: the document's creation time
    xbrl_url: str | None
    revision: bool  # integrated `type_Sub` Revision
    markers: str  # the listing's own format markers, joined


def nse_time(raw: str | None) -> datetime | None:
    """`16-Jan-2025 20:20:21` (or without seconds, or a bare date) as an IST datetime."""
    if not raw or raw.strip() in {"-", ""}:
        return None
    for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw.strip().title(), pattern).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def basis_of(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if text == "consolidated":
        return "consolidated"
    if text in {"non-consolidated", "standalone"}:
        return "standalone"
    return ""


def _xbrl(raw: str | None) -> str | None:
    return None if not raw or raw.endswith(NO_XBRL_SUFFIXES) else raw


def _json(body: bytes, empty: str) -> object:
    try:
        return json.loads(body or empty)
    except ValueError:
        return json.loads(empty)


def parse_results_listing(body: bytes, listing: str = LISTING_REG33) -> list[Filing]:
    """The `corporates-financial-results` answer (a JSON list; the insurance index names its
    period end `periodEnd`, the others `toDate`); rows without a period end are skipped."""
    rows = _json(body, "[]")
    filings = []
    for row in rows if isinstance(rows, list) else []:
        end = nse_time(row.get("toDate") or row.get("periodEnd"))
        if end is None:
            continue
        markers = [row.get(k) or "-" for k in ("format", "indAs", "bank", "insuranceType")]
        filings.append(
            Filing(
                listing=listing,
                symbol=row.get("symbol") or "",
                isin=row.get("isin") or "",
                seq=str(row.get("seqNumber") or ""),
                period_end=end.date(),
                basis=basis_of(row.get("consolidated")),
                broadcast_at=nse_time(row.get("broadCastDate")),
                created_at=None,
                xbrl_url=_xbrl(row.get("xbrl")),
                revision=False,
                markers="/".join(m for m in markers if m != "-") or "-",
            )
        )
    return filings


def parse_integrated_listing(body: bytes) -> list[Filing]:
    """The `integrated-filing-results` answer (`{"data": [...], "totalCount": n}`): its
    Financials rows."""
    answer = _json(body, "{}")
    rows = answer.get("data") if isinstance(answer, dict) else None
    filings = []
    for row in rows or []:
        if "Financial" not in (row.get("type") or ""):
            continue
        end = nse_time(row.get("qe_Date"))
        if end is None:
            continue
        sub = row.get("type_Sub") or "-"
        filings.append(
            Filing(
                listing=LISTING_INTEGRATED,
                symbol=row.get("symbol") or "",
                isin="",
                seq=str(row.get("seq_Id") or ""),
                period_end=end.date(),
                basis=basis_of(row.get("consolidated")),
                broadcast_at=nse_time(row.get("broadcast_Date")),
                created_at=nse_time(row.get("creation_Date")),
                xbrl_url=_xbrl(row.get("xbrl")),
                revision=sub.strip().lower().startswith("revis"),
                markers=sub,
            )
        )
    return filings


def parse_listing(listing: str, body: bytes) -> list[Filing]:
    if listing == LISTING_INTEGRATED:
        return parse_integrated_listing(body)
    return parse_results_listing(body, listing)


def listing_ok(listing: str, body: bytes) -> bool:
    """Whether a listing answer has the known shape (a list, or `{"data": [...]}`): a block
    page or a changed format is not mistaken for a company without filings."""
    try:
        answer = json.loads(body)
    except ValueError:
        return False
    if listing == LISTING_INTEGRATED:
        return isinstance(answer, dict) and isinstance(answer.get("data"), list)
    return isinstance(answer, list)


# --- announcements --------------------------------------------------------------------------


@dataclass(frozen=True)
class Announcement:
    symbol: str
    at: datetime  # the broadcast time (`an_dt`)
    desc: str
    text: str


def parse_announcements(body: bytes) -> list[Announcement]:
    """The `corporate-announcements` answer (a JSON list); `an_dt` is the broadcast time."""
    rows = _json(body, "[]")
    items = []
    for row in rows if isinstance(rows, list) else []:
        at = nse_time(row.get("an_dt"))
        if at is not None:
            items.append(
                Announcement(
                    row.get("symbol") or "",
                    at,
                    row.get("desc") or "",
                    row.get("attchmntText") or "",
                )
            )
    return items


RESULT_DESCS = frozenset({"financial result updates", "financial results"})
BOARD_OUTCOME = "outcome of board meeting"
_RESULTS_WORD = re.compile(r"\bresults?\b", re.IGNORECASE)


def results_rule(item: Announcement) -> str:
    """Which rule makes `item` a results announcement: `result_updates` for a 'Financial Result
    Updates' item; `board_outcome` for a board-meeting outcome whose text names the results (the
    Integrated Filing era files the results PDF under it); `board_outcome_bare` for one whose
    text names nothing ('Outcome of Board Meeting held on April 10, 2025'), used only on the
    filing's own day or the day before (`timing.match_announcement`); "" otherwise."""
    desc = item.desc.strip().lower()
    if desc in RESULT_DESCS:
        return "result_updates"
    if desc.startswith(BOARD_OUTCOME):
        return "board_outcome" if _RESULTS_WORD.search(item.text) else "board_outcome_bare"
    return ""

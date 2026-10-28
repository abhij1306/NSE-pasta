"""`pasta doctor`: is each source still where the settings say, in a format pasta reads?

One live request per source (the cache is neither read nor written), each answer classified:

    ok              answered in the known format
    not_found       404: the endpoint or file has moved
    blocked         no answer after the retries, an HTTP error, or a web page instead of data
    format_changed  data, but in a format pasta does not read

Every source that is not ok comes with what to do (`FIXES`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from . import nse, screener, universe
from .config import FILE_NAME, Config
from .http import Client, Fetched
from .xbrl import XbrlError
from .xbrl import parse as parse_xbrl

FIXES = {
    "not_found": (
        "The address answered 404: NSE (or screener.in) has likely moved it. Find the new "
        f"address and set it under [sources] in DATA/{FILE_NAME} (`pasta config init` writes "
        "one)."
    ),
    "blocked": (
        "No usable answer: the site blocks or is down. Try again later, or with a larger "
        "[network] interval (screener.in: [screener] interval)."
    ),
    "format_changed": (
        "The site answers in a format pasta does not read. The parser needs a code change: "
        "open an issue with the URL and the answer's first lines."
    ),
}


@dataclass(frozen=True)
class Probe:
    source: str
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def classify(got: Fetched, valid: Callable[[bytes], bool], markup: bool = False) -> str:
    """`markup`: the source answers XML or HTML, so a page is not by itself a block page."""
    if got.status == 404:
        return "not_found"
    if got.status != 200 or (not markup and got.body.lstrip()[:1] == b"<"):
        return "blocked"
    try:
        return "ok" if valid(got.body) else "format_changed"
    except (ValueError, KeyError, TypeError, AttributeError):
        return "format_changed"


def _rows_with(keys: set[str], rows: object) -> bool:
    return isinstance(rows, list) and bool(rows) and keys <= set(rows[0])


def _valid_reg33(body: bytes) -> bool:
    return _rows_with({"toDate", "xbrl", "consolidated", "broadCastDate"}, json.loads(body))


def _valid_integrated(body: bytes) -> bool:
    data = json.loads(body).get("data")
    return _rows_with({"qe_Date", "xbrl", "consolidated", "broadcast_Date"}, data)


def _valid_list(body: bytes) -> bool:
    return isinstance(json.loads(body), list)


def _valid_xbrl(body: bytes) -> bool:
    try:
        parsed = parse_xbrl(body)
    except XbrlError:
        return False
    return parsed.quarter is not None and parsed.quarter.revenue is not None


def _probe(
    client: Client,
    name: str,
    url: str,
    valid: Callable[[bytes], bool],
    referer: str | None,
    markup: bool = False,
) -> tuple[Probe, bytes]:
    got = client.get(url, referer=referer)
    return Probe(name, classify(got, valid, markup), url), got.body


def first_symbol(body: bytes) -> str:
    """The first company of an index list: the company the other probes ask about."""
    try:
        listed = universe.parse_index_list(body)
    except universe.UniverseError:
        return ""
    return listed[0].symbol if listed else ""


def _lists(client: Client, cfg: Config) -> tuple[list[Probe], str]:
    src = cfg.sources
    index, body = _probe(
        client, "index list", src.index_list.format(name=universe.INDEXES["nifty50"]),
        lambda b: bool(universe.parse_index_list(b)), None,
    )  # fmt: skip
    equity = _probe(
        client, "equity list", src.equity_list, lambda b: bool(universe.parse_equity_list(b)), None
    )[0]
    return [index, equity], first_symbol(body) if index.ok else ""


def _company(client: Client, cfg: Config, symbol: str, today: date) -> list[Probe]:
    src = cfg.sources
    page = src.results_page
    probes = [_probe(client, "reg33 listing", nse.results_url(src, symbol), _valid_reg33, page)[0]]
    integrated, body = _probe(
        client, "integrated listing", nse.integrated_url(src, symbol), _valid_integrated, page
    )
    probes.append(integrated)
    since = today - timedelta(days=120)
    probes.append(
        _probe(client, "insurance listing", nse.insurance_url(src, since, today), _valid_list,
               page)[0]
    )  # fmt: skip
    window = nse.announcements_url(src, symbol, today - timedelta(days=3), today)
    probes.append(_probe(client, "announcements", window, _valid_list, src.announcements_page)[0])
    documents = [f.xbrl_url for f in nse.parse_integrated_listing(body) if f.xbrl_url]
    if documents:
        probes.append(
            _probe(client, "xbrl document", documents[0], _valid_xbrl, None, markup=True)[0]
        )
    else:
        probes.append(Probe("xbrl document", "blocked", "no document listed to ask for"))
    return probes


def _screener(client: Client, cfg: Config, symbol: str) -> list[Probe]:
    base = cfg.screener.base
    page = screener.page_url(base, symbol, "consolidated")
    robots, _body = _probe(
        client, "screener robots.txt", screener.robots_url(base),
        lambda b: screener.allowed(b, page), None,
    )  # fmt: skip
    if not robots.ok:
        return [robots]
    probe = _probe(
        client, "screener page", page, lambda b: bool(screener.parse_page(b)), None, markup=True
    )
    return [robots, probe[0]]


COMPANY_PROBES = ("reg33 listing", "integrated listing", "insurance listing", "announcements",
                  "xbrl document", "screener robots.txt", "screener page")  # fmt: skip


def run(
    client: Client, screener_client: Client, cfg: Config, today: date | None = None
) -> list[Probe]:
    """One probe per source. The company-level probes ask about the first company of NSE's
    NIFTY 50 list (it files every quarter); without that list they cannot run."""
    today = today or date.today()
    probes, symbol = _lists(client, cfg)
    if not symbol:
        why = "no company to ask about: the index list failed"
        return probes + [Probe(name, "blocked", why) for name in COMPANY_PROBES]
    return probes + _company(client, cfg, symbol, today) + _screener(screener_client, cfg, symbol)


def report(probes: list[Probe]) -> list[str]:
    """The lines to print: one per source, then what to do about each kind of problem."""
    lines = [f"  {p.source:<20} {p.status:<15} {p.detail}" for p in probes]
    for status, fix in FIXES.items():
        hit = [p.source for p in probes if p.status == status]
        if hit:
            lines += ["", f"{status} ({', '.join(hit)}):", f"  {fix}"]
    return lines

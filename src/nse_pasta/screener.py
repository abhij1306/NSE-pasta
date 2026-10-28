"""The secondary source: the public company pages of screener.in, read for the quarters NSE does
not give and to cross-check the ones it does. Pure but for `allowed` (robots.txt rules).

Rules (docs/screener.md): public pages only; never log in, never send or store credentials;
every URL is checked against screener.in's robots.txt before it is asked (it disallows
`/company/source/quarter/*`, which is never asked); one request every 3 s by default.

Each company has two pages: consolidated figures at `/company/<SYMBOL>/consolidated/` and
standalone at `/company/<SYMBOL>/`. A page's "Quarterly Results" table shows the latest 13
quarters only (Sales, or Revenue for banks and NBFCs, Net Profit and EPS; money in crore rupees,
rounded as displayed) and names its basis above the table. A company without consolidated
accounts gets its standalone figures on both pages, labelled standalone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

from .num import exact

CRORE = Decimal(10) ** 7
REVENUE_LABELS = ("sales", "revenue")
PROFIT_LABELS = ("net profit",)
EPS_LABELS = ("eps in rs",)


def page_url(base: str, symbol: str, basis: str) -> str:
    path = f"{base}/company/{quote(symbol, safe='')}/"
    return path + "consolidated/" if basis == "consolidated" else path


def robots_url(base: str) -> str:
    return base + "/robots.txt"


def _rules(robots: str, agent: str) -> list[tuple[bool, str]]:
    """The (allow, pattern) rules of the group for `agent`, else of the `*` group."""
    groups: dict[str, list[tuple[bool, str]]] = {}
    current: list[str] = []
    in_rules = False
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                current, in_rules = [], False
            current.append(value.lower())
            for name in current:
                groups.setdefault(name, [])
        elif key in ("allow", "disallow") and current:
            in_rules = True
            if value:
                for name in current:
                    groups[name].append((key == "allow", value))
    return groups.get(agent.lower(), groups.get("*", []))


def _matches(pattern: str, path: str) -> bool:
    regex = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
    return re.match(regex + ("$" if pattern.endswith("$") else ""), path) is not None


def allowed(robots: bytes, url: str, agent: str = "*") -> bool:
    """Whether screener.in's robots.txt lets `agent` ask for `url`, with `*` and `$` in rules
    and the longest matching rule winning (an Allow on a tie). Nothing is asked without a
    robots.txt."""
    if not robots:
        return False
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    rules = _rules(robots.decode("utf-8", errors="replace"), agent)
    hits = [(len(p), allow) for allow, p in rules if _matches(p, path)]
    return max(hits, default=(0, True))[1]


@dataclass(frozen=True)
class Quarter:
    period_end: date
    basis: str
    revenue: Decimal | None  # rupees
    net_profit: Decimal | None  # rupees
    eps_basic: Decimal | None  # rupees a share


class _QuartersTable(HTMLParser):
    """Collects the text of `<section id="quarters">`: the basis line, each header cell's
    `data-date-key` and each body row's cells."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0  # section nesting while inside the quarters section
        self.in_sub = False
        self.sub = ""
        self.dates: list[str] = []
        self.rows: list[list[str]] = []
        self.in_table = False
        self.in_body = False
        self.cell: list[str] | None = None
        self.row: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "section":
            if self.depth or values.get("id") == "quarters":
                self.depth += 1
            return
        if not self.depth:
            return
        if tag == "p" and "sub" in (values.get("class") or "").split() and not self.sub:
            self.in_sub = True
        elif tag == "table" and not self.dates and not self.rows:
            self.in_table = True
        elif self.in_table:
            self._table_start(tag, values.get("data-date-key"))

    def _table_start(self, tag: str, date_key: str | None) -> None:
        if tag == "th" and date_key:
            self.dates.append(date_key)
        elif tag == "tbody":
            self.in_body = True
        elif self.in_body and tag == "tr":
            self.row = []
        elif self.row is not None and tag == "td":
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == "section":
            self.depth -= 1
        elif tag == "p" and self.in_sub:
            self.in_sub = False
        elif tag == "td" and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "tbody":
            self.in_body = False
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_sub:
            self.sub += data
        if self.cell is not None:
            self.cell.append(data)


def _row(rows: list[list[str]], labels: tuple[str, ...]) -> list[str] | None:
    for row in rows:
        label = row[0].replace("+", "").replace("\xa0", " ").strip().lower() if row else ""
        if label in labels:
            return row[1:]
    return None


def _basis(label: str) -> str:
    """The basis a page names first above its table ('Standalone Figures in Rs. Crores / View
    Consolidated' is standalone: the link names the other basis); "" when it names neither."""
    named = [(label.lower().find(b), b) for b in ("consolidated", "standalone")]
    found = sorted((at, b) for at, b in named if at >= 0)
    return found[0][1] if found else ""


def _cell(values: list[str] | None, index: int, scale: Decimal) -> Decimal | None:
    if values is None or index >= len(values):
        return None
    value = exact(values[index].replace("%", ""), grouped=True)
    return None if value is None else value * scale


def parse_page(body: bytes) -> list[Quarter]:
    """The quarters of one company page, with the basis the page names (none when it names
    neither, or the page has no quarterly table)."""
    table = _QuartersTable()
    table.feed(body.decode("utf-8", errors="replace"))
    basis = _basis(table.sub)
    if not basis or not table.dates:
        return []
    revenue = _row(table.rows, REVENUE_LABELS)
    profit = _row(table.rows, PROFIT_LABELS)
    eps = _row(table.rows, EPS_LABELS)
    out = []
    for index, key in enumerate(table.dates):
        try:
            end = date.fromisoformat(key)
        except ValueError:
            continue
        out.append(
            Quarter(
                end,
                basis,
                _cell(revenue, index, CRORE),
                _cell(profit, index, CRORE),
                _cell(eps, index, Decimal(1)),
            )
        )
    return out

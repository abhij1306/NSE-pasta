"""Which companies a data folder covers: an NSE index's current constituents, a symbol list file,
or every listed equity. The choice and every symbol it has held are kept in `universe.json`.

An index list is NSE's current one (`ind_nifty50list.csv`, ...): today's members, not the
members on each past day. A company that left the index stays in the folder's universe once it
was in it (`first_seen`, `last_seen`), but one that left before the folder was started is never
in it. docs/limitations.md says what that means for a backtest.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .layout import write_text

INDEXES = {  # name: NSE's constituent list file
    "nifty50": "ind_nifty50list.csv",
    "niftynext50": "ind_niftynext50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv",
    "midcap150": "ind_niftymidcap150list.csv",
    "smallcap250": "ind_niftysmallcap250list.csv",
}
ALL = "all"
FILE_PREFIX = "file:"


class UniverseError(ValueError):
    """A universe spec or list that cannot be read."""


@dataclass(frozen=True)
class Company:
    symbol: str
    isin: str = ""
    name: str = ""
    first_seen: str = ""  # ISO date the folder's universe first listed it
    last_seen: str = ""  # ... and last listed it


def check_spec(spec: str) -> str:
    """`spec` normalised (`nifty50`, `all`, `file:PATH`); UniverseError when unknown."""
    spec = spec.strip()
    if spec.lower().startswith(FILE_PREFIX):
        return FILE_PREFIX + spec[len(FILE_PREFIX) :]
    name = spec.lower().replace(" ", "").replace("_", "")
    if name in INDEXES or name == ALL:
        return name
    raise UniverseError(
        f"unknown universe {spec!r}: one of {', '.join([*INDEXES, ALL])} or file:PATH"
    )


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]


def parse_index_list(body: bytes) -> list[Company]:
    """NSE's index constituent CSV (`Company Name, Industry, Symbol, Series, ISIN Code`)."""
    rows = _rows(body.decode("utf-8-sig", errors="replace"))
    if not rows or "symbol" not in rows[0]:
        raise UniverseError("not an NSE index constituent list")
    return [Company(r["symbol"], r.get("isin code", ""), r.get("company name", "")) for r in rows]


def parse_equity_list(body: bytes) -> list[Company]:
    """NSE's `EQUITY_L.csv`: every listed equity (`SYMBOL, NAME OF COMPANY, ..., ISIN NUMBER`)."""
    rows = _rows(body.decode("utf-8-sig", errors="replace"))
    if not rows or "symbol" not in rows[0]:
        raise UniverseError("not NSE's equity list")
    return [
        Company(r["symbol"], r.get("isin number", ""), r.get("name of company", "")) for r in rows
    ]


def parse_symbol_file(text: str) -> list[Company]:
    """A symbol list: one symbol a line (`#` starts a comment), or a CSV with a `symbol`
    column (an `isin` column is read too)."""
    lines = [ln.split("#", 1)[0].strip() for ln in text.lstrip("﻿").splitlines()]
    lines = [ln for ln in lines if ln]
    if lines and "," in lines[0] and "symbol" in lines[0].lower():
        rows = _rows("\n".join(lines))
        return [Company(r["symbol"].upper(), r.get("isin", "")) for r in rows if r.get("symbol")]
    return [Company(ln.split(",")[0].strip().upper()) for ln in lines]


def unique(companies: list[Company]) -> list[Company]:
    out: dict[str, Company] = {}
    for c in companies:
        if c.symbol and c.symbol not in out:
            out[c.symbol] = c
    return list(out.values())


@dataclass(frozen=True)
class Universe:
    spec: str
    companies: tuple[Company, ...]
    start: str = ""  # the first period end the last fetch asked for (parse and build default)

    @property
    def symbols(self) -> list[str]:
        return [c.symbol for c in self.companies]


def load(path: Path) -> Universe | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    companies = tuple(Company(**c) for c in raw["companies"])
    return Universe(raw["spec"], companies, raw.get("from", ""))


def save(path: Path, universe: Universe) -> None:
    payload = {
        "spec": universe.spec,
        "from": universe.start,
        "companies": [asdict(c) for c in universe.companies],
    }
    write_text(path, json.dumps(payload, indent=1, ensure_ascii=False) + "\n")


def merge(previous: Universe | None, spec: str, current: list[Company], today: date) -> Universe:
    """Today's list under `spec`, keeping every company an earlier list of the same spec held
    (`last_seen` says when it was last listed). A new spec starts afresh."""
    day = today.isoformat()
    held = {c.symbol: c for c in previous.companies} if previous and previous.spec == spec else {}
    out = dict(held)
    for c in unique(current):
        before = held.get(c.symbol)
        first = before.first_seen if before else day
        out[c.symbol] = Company(
            c.symbol, c.isin or (before.isin if before else ""), c.name, first, day
        )
    return Universe(spec, tuple(sorted(out.values(), key=lambda c: c.symbol)))

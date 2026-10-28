"""`pasta status`: what a data folder holds, from its files alone (no network)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import universe
from .config import Config
from .layout import Layout
from .raw import RawCache


@dataclass(frozen=True)
class Status:
    universe_spec: str = ""
    companies: int = 0
    nse_answers: dict[str, int] = field(default_factory=dict)
    screener_pages: int = 0
    last_fetch: datetime | None = None
    outputs: dict[str, int] = field(default_factory=dict)  # file: data rows

    @property
    def empty(self) -> bool:
        return not (self.companies or self.nse_answers or self.screener_pages or self.outputs)


def _kind(url: str, cfg: Config) -> str:
    src = cfg.sources
    if url.startswith(src.results_api):
        return "reg33 listings" if "index=equities" in url else "insurance listings"
    if url.startswith(src.integrated_api):
        return "integrated listings"
    if url.startswith(src.announcements_api):
        return "announcement windows"
    if url.endswith(".xml"):
        return "xbrl documents"
    return "lists"


def _rows(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def status(layout: Layout, cfg: Config) -> Status:
    held = universe.load(layout.universe)
    nse = RawCache(layout.raw_nse).entries()
    screener = RawCache(layout.raw_screener).entries()
    kinds = Counter(_kind(url, cfg) for url in nse)
    times = [e.fetched_at for e in (*nse.values(), *screener.values())]
    outputs = {p.name: _rows(p) for p in sorted(layout.out.glob("*.csv"))}
    return Status(
        universe_spec=held.spec if held else "",
        companies=len(held.companies) if held else 0,
        nse_answers=dict(sorted(kinds.items())),
        screener_pages=sum(1 for u in screener if "/company/" in u),
        last_fetch=max(times, default=None),
        outputs=outputs,
    )


def describe(st: Status) -> list[str]:
    if st.empty:
        return ["  empty: start with 'Run everything'"]
    lines = [
        f"  universe             {st.universe_spec or 'not chosen'} ({st.companies} companies)",
        *(f"  {kind:<20} {count}" for kind, count in st.nse_answers.items()),
        f"  screener pages       {st.screener_pages}",
        f"  last fetch           {st.last_fetch:%Y-%m-%d %H:%M} UTC" if st.last_fetch else "",
    ]
    lines += [f"  out/{name:<16} {rows} rows" for name, rows in st.outputs.items()]
    if not st.outputs:
        lines.append("  outputs              none yet (run parse and build)")
    return [line for line in lines if line]

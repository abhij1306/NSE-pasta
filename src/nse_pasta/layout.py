"""Where a data folder keeps its files, under the directory the user passes (`--data`).

    pasta.toml                      the folder's settings (`pasta config init`)
    universe.json                   the universe: its spec and every symbol it has held
    raw/nse/                        every NSE answer, by sha256 (`raw.RawCache`), never rewritten
    raw/screener/                   every screener.in page, the same way
    out/results.parquet, .csv       every version of every quarter's results
    out/filings.csv                 every filing considered and what became of it
    out/growth.parquet, .csv        point-in-time year-on-year growth, one row per result row
    out/coverage.csv                quarters due vs found, per symbol and year
    out/crosscheck.csv              NSE vs screener.in figures where both have a quarter
    out/asof=<ts>.parquet, .csv     the table as it could have been known at <ts>

Only `raw/` and `universe.json` are kept between runs; `out/` is rebuilt from them. Every file
in `out/` is written to a temporary name and renamed, so an interrupted run never leaves half a
file. `.pasta.lock` keeps two pulls from running on one folder at once.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


def atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(path: Path, text: str) -> None:
    atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def raw_nse(self) -> Path:
        return self.root / "raw" / "nse"

    @property
    def raw_screener(self) -> Path:
        return self.root / "raw" / "screener"

    @property
    def universe(self) -> Path:
        return self.root / "universe.json"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def lock(self) -> Path:
        return self.root / ".pasta.lock"


class Busy(RuntimeError):
    """Another pasta process holds the data folder's lock."""


@contextlib.contextmanager
def locked(layout: Layout) -> Iterator[None]:
    """Hold the folder's lock for the block: a second pull on the same folder stops at once.
    The operating system releases it when the process ends, however it ends."""
    layout.root.mkdir(parents=True, exist_ok=True)
    handle = layout.lock.open("a+b")
    try:
        try:
            _lock(handle)
        except OSError:
            raise Busy(f"{layout.root} is in use by another pasta process") from None
        yield
    finally:
        handle.close()


def _lock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

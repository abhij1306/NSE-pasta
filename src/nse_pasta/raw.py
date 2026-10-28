"""The raw cache: every answer kept once, gzipped, under the sha256 of its bytes, and a manifest
that records each fetch.

Layout under a cache root (`DATA/raw/nse/`, `DATA/raw/screener/`):

    manifest.jsonl          one line per fetch: url, status, sha256, bytes, fetched_at (UTC)
    blobs/<sha[:2]>/<sha>.gz

A body is written before its manifest line and a blob is never overwritten (same bytes, same
name), so an interrupted run leaves at most an unreferenced blob and a rerun resumes from the
manifest. A URL fetched again (a listing that grew) appends a new line: the latest line is the
URL's current answer, and every earlier answer stays readable (`history`). Nothing is ever
deleted, so every result version can be rebuilt from the cache alone.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .http import Client, Fetched, transient

MANIFEST = "manifest.jsonl"
BLOBS = "blobs"


@dataclass(frozen=True)
class Entry:
    url: str
    status: int
    sha256: str
    size: int
    fetched_at: datetime  # aware UTC


def sha256_of(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class RawCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._history: dict[str, list[Entry]] | None = None

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST

    def blob_path(self, sha: str) -> Path:
        return self.root / BLOBS / sha[:2] / f"{sha}.gz"

    def _all(self) -> dict[str, list[Entry]]:
        if self._history is None:
            self._history = {}
            if self.manifest.exists():
                with self.manifest.open(encoding="utf-8") as handle:
                    for line in handle:
                        entry = _entry(line)
                        if entry is not None:
                            self._history.setdefault(entry.url, []).append(entry)
        return self._history

    def entries(self) -> dict[str, Entry]:
        """Each URL's latest answer."""
        return {url: found[-1] for url, found in self._all().items()}

    def entry(self, url: str) -> Entry | None:
        found = self._all().get(url)
        return found[-1] if found else None

    def history(self, url: str) -> list[Entry]:
        """Every answer `url` ever got, oldest first."""
        return list(self._all().get(url, []))

    def body(self, entry: Entry) -> bytes:
        return gzip.decompress(self.blob_path(entry.sha256).read_bytes())

    def put(self, url: str, status: int, body: bytes, now: datetime | None = None) -> Entry:
        sha = sha256_of(body)
        path = self.blob_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(f".tmp{os.getpid()}")
            temp.write_bytes(gzip.compress(body, compresslevel=6))
            temp.replace(path)
        entry = Entry(url, status, sha, len(body), now or datetime.now(UTC))
        line = {
            "url": url,
            "status": status,
            "sha256": sha,
            "bytes": len(body),
            "fetched_at": entry.fetched_at.isoformat(),
        }
        with self.manifest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        self._all().setdefault(url, []).append(entry)
        return entry


def _entry(line: str) -> Entry | None:
    """One manifest line; a torn last line (an interrupted write) is skipped."""
    try:
        row = json.loads(line)
        return Entry(
            row["url"],
            int(row["status"]),
            row["sha256"],
            int(row["bytes"]),
            datetime.fromisoformat(row["fetched_at"]),
        )
    except (ValueError, KeyError, TypeError):
        return None


Reuse = Callable[[Entry], bool]


def always(_entry: Entry) -> bool:
    return True


@dataclass(frozen=True)
class Answer:
    url: str
    status: int  # 0: no answer (network error, or a cached-only read found nothing)
    body: bytes
    fetched: bool  # asked the network this time


def cached_get(
    cache: RawCache,
    client: Client | None,
    url: str,
    *,
    referer: str | None = None,
    reuse: Reuse = always,
    valid: Callable[[bytes], bool] | None = None,
) -> Answer:
    """The cached answer for `url` when `reuse` accepts it, else a fresh one, kept in the cache
    unless transient, or a 200 that `valid` refuses (a block page): those answer status 0 and are
    asked again next run. `client=None` reads the cache only."""
    entry = cache.entry(url)
    if entry is not None and (client is None or reuse(entry)):
        return Answer(url, entry.status, cache.body(entry), False)
    if client is None:
        return Answer(url, 0, b"", False)
    got: Fetched = client.get(url, referer=referer)
    if got.status == 200 and valid is not None and not valid(got.body):
        return Answer(url, 0, got.body, True)
    if not transient(got.status):
        cache.put(url, got.status, got.body)
    return Answer(url, got.status, got.body, True)

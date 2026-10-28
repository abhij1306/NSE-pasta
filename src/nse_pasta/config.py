"""A data folder's own settings, `DATA/pasta.toml`: where each source is fetched from, how
politely, and the defaults of `run`.

Every key is optional; a missing one keeps its default (`pasta config init` writes the file with
every default, `pasta config show` prints what is in effect). A flag on the command line wins
over the file. The file travels with the data, so a folder kept current by a scheduled
`pasta run` keeps its settings. When NSE moves an endpoint, point its `[sources]` URL at the new
place (`pasta doctor` says which one broke).
"""

from __future__ import annotations

import contextlib
import json
import tomllib
from dataclasses import dataclass, field, fields, replace
from datetime import date
from pathlib import Path
from typing import Any

from . import http

FILE_NAME = "pasta.toml"
SOURCES = ("nse", "screener", "both")
BASIS_RULES = ("consolidated-first", "both")
FIRST_PERIOD_END = date(2020, 3, 31)  # XBRL is complete from the March 2020 quarter
NSE = "https://www.nseindia.com"
ARCHIVES = "https://nsearchives.nseindia.com"


class ConfigError(ValueError):
    """`pasta.toml` names a key or value that does not exist."""


@dataclass(frozen=True)
class Network:
    interval: float = http.DEFAULT_INTERVAL  # seconds between two requests to NSE
    tries: int = http.DEFAULT_TRIES
    timeout: float = http.DEFAULT_TIMEOUT
    user_agent: str = http.USER_AGENT

    def client(self, interval: float | None = None, tries: int | None = None) -> http.Client:
        return http.Client(
            interval=self.interval if interval is None else interval,
            tries=tries or self.tries,
            timeout=self.timeout,
            user_agent=self.user_agent,
        )


@dataclass(frozen=True)
class Screener:
    interval: float = 3.0  # seconds between two requests to screener.in: slower than NSE
    base: str = "https://www.screener.in"


@dataclass(frozen=True)
class Run:
    universe: str = ""  # nifty50 | nifty100 | ... | all | file:PATH; "" = the folder's last one
    start: date = FIRST_PERIOD_END  # `from` in the file: the first period end fetched
    source: str = "nse"  # nse | screener | both
    basis: str = "consolidated-first"  # consolidated-first | both
    announcements: bool = True  # date each filing by its results announcement (public_at)


@dataclass(frozen=True)
class Sources:
    results_page: str = NSE + "/companies-listing/corporate-filings-financial-results"
    announcements_page: str = NSE + "/companies-listing/corporate-filings-announcements"
    results_api: str = NSE + "/api/corporates-financial-results"
    integrated_api: str = NSE + "/api/integrated-filing-results"
    announcements_api: str = NSE + "/api/corporate-announcements"
    index_list: str = ARCHIVES + "/content/indices/{name}"  # ind_nifty50list.csv, ...
    equity_list: str = ARCHIVES + "/content/equities/EQUITY_L.csv"


@dataclass(frozen=True)
class Config:
    network: Network = field(default_factory=Network)
    screener: Screener = field(default_factory=Screener)
    run: Run = field(default_factory=Run)
    sources: Sources = field(default_factory=Sources)
    path: Path | None = None  # the file read, None for the defaults


DEFAULT = Config()


def _typed(section: str, key: str, value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, float):
        ok = isinstance(value, int | float) and not isinstance(value, bool) and value > 0
        value = float(value) if ok else value
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
    elif isinstance(default, date):
        if isinstance(value, str):  # `from = "2020-03-31"` as well as `from = 2020-03-31`
            with contextlib.suppress(ValueError):
                value = date.fromisoformat(value)
        ok = isinstance(value, date)
    else:
        ok = isinstance(value, str)
    if not ok:
        raise ConfigError(f"[{section}] {key} = {value!r}: expected {type(default).__name__}")
    return value


def _section(name: str, raw: Any, base: Any, rename: dict[str, str] | None = None) -> Any:
    """`base` with the keys `raw` sets (`rename` maps file keys to field names)."""
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a table")
    rename = rename or {}
    names = {f.name for f in fields(base)}
    allowed = {k for k, v in rename.items() if v in names} | (names - set(rename.values()))
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"[{name}]: unknown key {unknown[0]!r}; known: {sorted(allowed)}")
    changes = {}
    for key, value in raw.items():
        attr = rename.get(key, key)
        changes[attr] = _typed(name, key, value, getattr(base, attr))
    return replace(base, **changes)


def _check(cfg: Config) -> None:
    if cfg.run.source not in SOURCES:
        raise ConfigError(f"[run] source = {cfg.run.source!r}: one of {list(SOURCES)}")
    if cfg.run.basis not in BASIS_RULES:
        raise ConfigError(f"[run] basis = {cfg.run.basis!r}: one of {list(BASIS_RULES)}")
    urls = [(f"sources] {f.name}", getattr(cfg.sources, f.name)) for f in fields(cfg.sources)]
    for where, url in [*urls, ("screener] base", cfg.screener.base)]:
        if not url.startswith(("https://", "http://")):
            raise ConfigError(f"[{where} = {url!r}: not an http(s) URL")
    if "{name}" not in cfg.sources.index_list:
        raise ConfigError("[sources] index_list must contain {name} (the list's file name)")


def parse(text: str, path: Path | None = None) -> Config:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"not valid TOML: {exc}") from None
    known = {"network", "screener", "run", "sources"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown table [{unknown[0]}]; known: {sorted(known)}")
    cfg = Config(
        _section("network", raw.get("network", {}), Network()),
        _section("screener", raw.get("screener", {}), Screener()),
        _section("run", raw.get("run", {}), Run(), {"from": "start"}),
        _section("sources", raw.get("sources", {}), Sources()),
        path,
    )
    _check(cfg)
    return cfg


def load(data: Path) -> Config:
    """`DATA/pasta.toml`, or the defaults when there is none."""
    path = data / FILE_NAME
    if not path.exists():
        return DEFAULT
    return parse(path.read_text(encoding="utf-8"), path)


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | date):
        return str(value)
    return json.dumps(value)  # a TOML basic string


def render(cfg: Config) -> str:
    """The settings as a `pasta.toml`, every key written out."""
    run = {"from" if f.name == "start" else f.name: getattr(cfg.run, f.name) for f in fields(Run)}
    lines = ["# pasta settings for this data folder. Delete a key to get its default back."]
    for name, values in (
        ("network", {f.name: getattr(cfg.network, f.name) for f in fields(Network)}),
        ("screener", {f.name: getattr(cfg.screener, f.name) for f in fields(Screener)}),
        ("run", run),
        ("sources", {f.name: getattr(cfg.sources, f.name) for f in fields(Sources)}),
    ):
        lines += ["", f"[{name}]", *(f"{k} = {_toml(v)}" for k, v in values.items())]
    return "\n".join(lines) + "\n"

"""`pasta`: download and keep current a point-in-time dataset of quarterly results.

    pasta --data D run [--universe nifty50] [--from 2020-03-31] [--to ...] [--source nse]
    pasta --data D fetch ...         (download only: the same options as run)
    pasta --data D parse             (the cache into out/results and out/filings.csv)
    pasta --data D build             (growth, coverage, cross-check)
    pasta --data D as-of 2025-06-30  (the table as it could have been known then)
    pasta --data D status            (what the folder holds)
    pasta --data D doctor            (is each source still reachable and readable?)
    pasta --data D config init|show  (DATA/pasta.toml: universe, range, source, pace, URLs)

Universes: nifty50, niftynext50, nifty100, nifty200, nifty500, midcap150, smallcap250 (NSE's
current lists), all (every listed equity), or file:PATH (a symbol list). Sources: nse, screener,
both (NSE first, screener.in fills what NSE does not give). `--data` defaults to $PASTA_DATA.
With no arguments, `pasta` opens a guided menu that asks for each choice and shows the command
it runs. Every step is resumable: rerun `run` to bring the data up to date (it skips what is on
disk). The exit code is 1 when a download, a probe or a step failed (the printed counts say
which), 2 for a bad command line or pasta.toml.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path

from . import build, config, doctor, fetch, interactive, parse, status, tables, universe
from .config import Config
from .layout import Busy, Layout, locked
from .raw import RawCache, cached_get


def _day(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _print(title: str, payload: object) -> None:
    print(f"{title}: {json.dumps(payload, default=str)}", flush=True)


# --- the universe ---------------------------------------------------------------------------


def _list_body(layout: Layout, cfg: Config, url: str) -> bytes:
    """An NSE list (index constituents, every equity), fetched at most once in 20 hours."""
    with cfg.network.client() as client:
        answer = cached_get(
            RawCache(layout.raw_nse),
            client,
            url,
            reuse=fetch.fresh(datetime.now(UTC)),
            valid=lambda body: body.lstrip()[:1] != b"<",
        )
    if answer.status != 200:
        raise universe.UniverseError(f"{url}: HTTP {answer.status or 'no answer'}")
    return answer.body


def resolve(
    layout: Layout, cfg: Config, spec: str | None, start: date, today: date
) -> universe.Universe:
    """The universe for this fetch: the spec asked for (flag, then pasta.toml, then the one the
    folder already has), its current list merged into what the folder held; `start` is kept as
    the folder's default range for parse and build."""
    held = universe.load(layout.universe)
    raw = spec or cfg.run.universe or (held.spec if held else "")
    if not raw:
        raise universe.UniverseError(
            "no universe chosen: pass --universe (nifty50, nifty500, all, file:PATH, ...)"
        )
    spec = universe.check_spec(raw)
    if spec.startswith(universe.FILE_PREFIX):
        path = Path(spec.removeprefix(universe.FILE_PREFIX)).expanduser()
        current = universe.parse_symbol_file(path.read_text(encoding="utf-8"))
    elif spec == universe.ALL:
        current = universe.parse_equity_list(_list_body(layout, cfg, cfg.sources.equity_list))
    else:
        url = cfg.sources.index_list.format(name=universe.INDEXES[spec])
        current = universe.parse_index_list(_list_body(layout, cfg, url))
    if not current:
        raise universe.UniverseError(f"{spec}: the list names no company")
    if held is not None and held.spec != spec:
        print(f"universe changed from {held.spec} to {spec}: starting a new list", flush=True)
    found = replace(universe.merge(held, spec, current, today), start=start.isoformat())
    universe.save(layout.universe, found)
    return found


def _companies(layout: Layout) -> list[universe.Company]:
    held = universe.load(layout.universe)
    if held is None:
        raise universe.UniverseError("no universe yet: run `pasta fetch --universe ...` first")
    return list(held.companies)


# --- the steps ------------------------------------------------------------------------------


def do_fetch(layout: Layout, cfg: Config, args: argparse.Namespace) -> bool:
    today = date.today()
    found = resolve(layout, cfg, args.universe, args.start, today)
    companies = list(found.companies)
    _print("universe", {"spec": found.spec, "companies": len(companies)})
    report = fetch.FetchReport()
    nse_cache, screener_cache = RawCache(layout.raw_nse), RawCache(layout.raw_screener)
    with cfg.network.client(args.interval) as client:
        nse_fetch = fetch.NseFetch(nse_cache, client, cfg, report)
        if args.source in ("nse", "both"):
            fetch.fetch_nse(
                nse_fetch,
                companies,
                args.start,
                args.end,
                today,
                rule=args.basis,
                announcements=args.announcements,
            )
        if args.source in ("screener", "both"):
            with cfg.network.client(cfg.screener.interval) as slow:
                screener_fetch = fetch.ScreenerFetch(screener_cache, slow, cfg, report)
                fetch.fetch_screener(screener_fetch, companies, rule=args.basis)
                report.requests += slow.requests
        if args.source == "both" and args.announcements:
            gaps = fetch.fetch_gap_announcements(
                nse_fetch, screener_cache, companies, args.start, args.end, today
            )
            _print("screener-only quarters dated from NSE announcements", gaps)
        report.requests += client.requests
        report.statuses = dict(client.statuses)
    _print("fetch", asdict(report))
    return report.ok()


def do_parse(layout: Layout, cfg: Config, args: argparse.Namespace) -> bool:
    rows, outcomes, report = parse.parse(
        RawCache(layout.raw_nse),
        RawCache(layout.raw_screener),
        cfg,
        _companies(layout),
        args.start,
        args.end,
        args.basis,
    )
    tables.write(layout.out, "results", rows, parse.RESULTS_SCHEMA)
    tables.write_csv(layout.out, "filings", parse.outcome_rows(outcomes), parse.FILINGS_SCHEMA)
    _print("parse", asdict(report))
    return True


def _results(layout: Layout) -> list[dict]:
    path = layout.out / "results.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: run `pasta parse` first")
    return tables.read_csv(path, parse.RESULTS_SCHEMA)


def do_build(layout: Layout, cfg: Config, args: argparse.Namespace) -> bool:
    rows = _results(layout)
    companies = _companies(layout)
    grown = build.growth_table(rows, args.basis)
    tables.write(layout.out, "growth", grown, build.GROWTH_SCHEMA)
    now = datetime.now(UTC)
    cov = build.coverage(companies, rows, args.start, args.end, now)
    tables.write_csv(layout.out, "coverage", cov.rows, build.COVERAGE_SCHEMA)
    checked = build.crosscheck(RawCache(layout.raw_screener), cfg, companies, rows)
    tables.write_csv(layout.out, "crosscheck", checked, build.CROSSCHECK_SCHEMA)
    _print(
        "growth",
        {
            "rows": len(grown),
            "unit_suspect": sum(1 for g in grown if g["unit_suspect"]),
            "sales_yoy_defined": sum(1 for g in grown if g["sales_yoy"] is not None),
            "eps_yoy_defined": sum(1 for g in grown if g["eps_yoy"] is not None),
        },
    )
    _print("coverage", {str(y): dict(c) for y, c in sorted(cov.by_year.items())})
    _print("crosscheck", {"quarters": len(checked), **build.crosscheck_counts(checked)})
    return True


def do_as_of(layout: Layout, cfg: Config, args: argparse.Namespace) -> bool:
    ts = build.parse_as_of(args.when)
    rows = _results(layout)
    grown = build.growth_table(rows, args.basis)
    known = build.as_of(rows, grown, ts, args.basis)
    stem = build.as_of_stem(ts)
    tables.write(layout.out, stem, known, build.ASOF_SCHEMA)
    _print(f"as of {ts.isoformat()}", {"rows": len(known), "file": f"out/{stem}.parquet"})
    return True


def check_sources(cfg: Config, args: argparse.Namespace) -> bool:
    with (
        cfg.network.client(args.interval, tries=2) as client,
        cfg.network.client(cfg.screener.interval, tries=2) as slow,
    ):
        probes = doctor.run(client, slow, cfg)
    print(f"sources ({cfg.path or 'default settings, no ' + config.FILE_NAME}):", flush=True)
    for line in doctor.report(probes):
        print(line, flush=True)
    return all(p.ok for p in probes)


def show_config(layout: Layout, cfg: Config, action: str) -> bool:
    path = layout.root / config.FILE_NAME
    if action == "show":
        print(f"# {cfg.path or f'defaults ({path} does not exist)'}")
        print(config.render(cfg), end="", flush=True)
        return True
    if path.exists():
        print(f"{path} exists; `pasta config show` prints what is in effect", file=sys.stderr)
        return False
    path.write_text(config.render(config.DEFAULT), encoding="utf-8")
    print(f"wrote {path}", flush=True)
    return True


def show_status(layout: Layout, cfg: Config) -> bool:
    print(f"{layout.root}:", flush=True)
    for line in status.describe(status.status(layout, cfg)):
        print(line, flush=True)
    return True


# --- the command line -----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pasta", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data",
        default=os.environ.get("PASTA_DATA"),
        help="data directory, outside any git repo (default $PASTA_DATA)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="seconds between requests to NSE (default 2, or [network] interval in pasta.toml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def ranged(p: argparse.ArgumentParser) -> None:
        p.add_argument("--from", dest="start", type=_day, default=None, help="first period end")
        p.add_argument("--to", dest="end", type=_day, default=None, help="last period end")
        p.add_argument("--basis", choices=config.BASIS_RULES, default=None)

    for name, text in (
        ("run", "fetch, parse and build: the whole pipeline, skipping what is on disk"),
        ("fetch", "download listings, XBRL documents, announcements and pages into raw/"),
    ):
        p = sub.add_parser(name, help=text)
        ranged(p)
        p.add_argument("--universe", help="nifty50 ... nifty500, all, or file:PATH")
        p.add_argument("--source", choices=config.SOURCES, default=None)
        p.add_argument(
            "--no-announcements",
            dest="announcements",
            action="store_false",
            default=None,
            help="do not fetch announcements (public_at then comes from the XBRL filing time)",
        )
    ranged(sub.add_parser("parse", help="the raw cache into out/results and out/filings.csv"))
    ranged(sub.add_parser("build", help="growth, coverage and the cross-check from out/results"))
    asof = sub.add_parser("as-of", help="the table as it could have been known at a time")
    asof.add_argument("when", help="YYYY-MM-DD (end of that day, IST) or YYYY-MM-DDTHH:MM (IST)")
    asof.add_argument("--basis", choices=config.BASIS_RULES, default=None)
    sub.add_parser("status", help="what the data folder holds")
    sub.add_parser("doctor", help="ask each source once and say what is broken")
    settings = sub.add_parser("config", help=f"DATA/{config.FILE_NAME}: write the defaults, show")
    settings.add_argument("action", choices=["init", "show"])
    return parser


def _defaults(args: argparse.Namespace, cfg: Config, layout: Layout) -> None:
    """Fill what the command line left out: `--from` of parse and build from the folder's last
    fetch, the rest (and a fetch's `--from`) from pasta.toml."""
    held = universe.load(layout.universe)
    start = cfg.run.start
    if args.cmd in ("parse", "build") and held is not None and held.start:
        start = date.fromisoformat(held.start)
    for name, value in (
        ("start", start),
        ("end", date.today()),
        ("basis", cfg.run.basis),
        ("source", cfg.run.source),
        ("announcements", cfg.run.announcements),
    ):
        if getattr(args, name, False) is None:
            setattr(args, name, value)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        code = run(argv)
    else:  # no arguments: the guided menu
        try:
            code = interactive.main(input, print, run)
        except EOFError:
            code = 0
        except KeyboardInterrupt:
            raise SystemExit(130) from None
    if code:
        raise SystemExit(code)


def run(argv: list[str]) -> int:
    """Run one command line; 1 when a download, probe or step failed, else 0."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.data:
        parser.error("--data is required (or set PASTA_DATA)")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )
    layout = Layout(Path(args.data).expanduser().resolve())
    layout.root.mkdir(parents=True, exist_ok=True)
    try:
        cfg = config.load(layout.root)
    except config.ConfigError as exc:
        print(f"{layout.root / config.FILE_NAME}: {exc}", file=sys.stderr)
        return 2
    _defaults(args, cfg, layout)
    try:
        return 0 if _dispatch(layout, args, cfg) else 1
    except (Busy, universe.UniverseError, FileNotFoundError, ValueError) as exc:
        print(f"pasta: {exc}", file=sys.stderr)
        return 1


def _dispatch(layout: Layout, args: argparse.Namespace, cfg: Config) -> bool:
    if args.cmd == "doctor":
        return check_sources(cfg, args)
    if args.cmd == "config":
        return show_config(layout, cfg, args.action)
    if args.cmd == "status":
        return show_status(layout, cfg)
    with locked(layout):
        if args.cmd == "fetch":
            return do_fetch(layout, cfg, args)
        if args.cmd == "parse":
            return do_parse(layout, cfg, args)
        if args.cmd == "build":
            return do_build(layout, cfg, args)
        if args.cmd == "as-of":
            return do_as_of(layout, cfg, args)
        ok = do_fetch(layout, cfg, args)  # run: every step, even after a failed download
        ok = do_parse(layout, cfg, args) and ok
        return do_build(layout, cfg, args) and ok


if __name__ == "__main__":
    main()

"""`pasta` with no arguments: a guided menu over the same commands.

It shows what the data folder already holds, asks only for what a command needs (with a default
for each answer), prints the equivalent command line and runs it through `cli.run`. It does
nothing the flags cannot: a front door for people who don't know them yet.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from datetime import date
from pathlib import Path

from . import config, universe
from .layout import Layout
from .status import describe, status

Ask = Callable[[str], str]
Say = Callable[[str], None]
Run = Callable[[list[str]], int]

UNIVERSES = (
    ("nifty50", "NIFTY 50: a quick first run (about 2 hours for 2020 to today)"),
    ("nifty100", "NIFTY 100"),
    ("nifty200", "NIFTY 200"),
    ("nifty500", "NIFTY 500 (about a day for 2020 to today)"),
    ("all", "every listed equity (several days)"),
    ("file", "a file of symbols, one a line"),
)
SOURCES = (
    ("nse", "NSE only: XBRL filings, exact figures"),
    ("both", "NSE first, screener.in fills quarters NSE does not give"),
    ("screener", "screener.in only: the latest 13 quarters, rounded to crore"),
)


class Cancelled(Exception):
    """The person typed `q` at a prompt: back to the menu."""


def _answer(ask: Ask, prompt: str) -> str:
    raw = ask(prompt).strip()
    if raw.lower() in ("q", "quit"):
        raise Cancelled
    return raw


def choose(ask: Ask, say: Say, title: str, options: list[str], default: int = 1) -> int:
    """The 0-based index of the option picked by number; Enter takes `default` (1-based)."""
    say(title)
    for n, option in enumerate(options, 1):
        say(f"  {n}) {option}")
    while True:
        raw = _answer(ask, f"Choose 1-{len(options)} [{default}]: ")
        if not raw:
            return default - 1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        say("  Type a number from the list (q goes back).")


def ask_day(ask: Ask, say: Say, label: str, default: date) -> date:
    while True:
        raw = _answer(ask, f"{label} (YYYY-MM-DD) [{default}]: ")
        if not raw:
            return default
        try:
            return date.fromisoformat(raw)
        except ValueError:
            say("  Not a date: write it as 2026-10-28.")


def ask_yes(ask: Ask, question: str, default: bool) -> bool:
    raw = _answer(ask, f"{question} [{'Y/n' if default else 'y/N'}]: ").lower()
    return default if not raw else raw.startswith("y")


def _inside_git(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def ask_data(ask: Ask, say: Say, default: Path) -> Path:
    while True:
        raw = _answer(ask, f"Data directory [{default}]: ")
        path = Path(raw).expanduser().resolve() if raw else default
        if not _inside_git(path):
            return path
        say("  That is inside a git repository; data must never be committed. Pick another.")


def _universe(ask: Ask, say: Say, layout: Layout) -> list[str]:
    held = universe.load(layout.universe)
    if held is not None and ask_yes(ask, f"Keep the universe {held.spec}?", True):
        return []
    picked = UNIVERSES[choose(ask, say, "Which companies?", [f"{n:<9} {w}" for n, w in UNIVERSES])]
    if picked[0] != "file":
        return ["--universe", picked[0]]
    while True:
        raw = _answer(ask, "File of symbols: ")
        if raw and Path(raw).expanduser().is_file():
            return ["--universe", f"file:{Path(raw).expanduser().resolve()}"]
        say("  No such file (q goes back).")


def _range(ask: Ask, say: Say, today: date) -> list[str]:
    say(
        f"  XBRL is complete from the {config.FIRST_PERIOD_END} quarter; earlier quarters are"
        " partial (2018-2019) or absent."
    )
    first = ask_day(ask, say, "First quarter end", config.FIRST_PERIOD_END)
    return ["--from", first.isoformat(), "--to", today.isoformat()]


def plan_run(ask: Ask, say: Say, layout: Layout, today: date) -> list[str]:
    argv = ["run", *_universe(ask, say, layout), *_range(ask, say, today)]
    source = SOURCES[choose(ask, say, "Which source?", [f"{n:<9} {w}" for n, w in SOURCES])][0]
    return [*argv, "--source", source]


def plan_fetch(ask: Ask, say: Say, layout: Layout, today: date) -> list[str]:
    return ["fetch", *plan_run(ask, say, layout, today)[1:]]


def plan_rebuild(ask: Ask, say: Say, layout: Layout, today: date) -> list[str]:
    say("  Rebuilds out/ from what is on disk; asks the network nothing.")
    return ["parse"]


def plan_as_of(ask: Ask, say: Say, layout: Layout, today: date) -> list[str]:
    when = ask_day(ask, say, "Known at the end of", today)
    return ["as-of", when.isoformat()]


def plan_doctor(ask: Ask, say: Say, layout: Layout, today: date) -> list[str]:
    say("  Asks each source once (about ten requests) and says what is broken.")
    return ["doctor"]


Plan = Callable[[Ask, Say, Layout, date], list[str]]
MENU: tuple[tuple[str, Plan | None], ...] = (
    ("Run everything (fetch, parse, build)", plan_run),
    ("Fetch only", plan_fetch),
    ("Parse and build from what is on disk", plan_rebuild),
    ("Point-in-time table as of a day", plan_as_of),
    ("Check that the sources still work", plan_doctor),
    ("Show what the data folder holds", None),
    ("Quit", None),
)


def command(argv: list[str]) -> str:
    """The command line to type: arguments quoted only where a shell needs it."""
    plain = re.compile(r"[\w@%+=:,./\\-]+")  # a Windows path's backslashes need no quotes
    return "pasta " + " ".join(a if plain.fullmatch(a) else shlex.quote(a) for a in argv)


def _do(picked: int, ask: Ask, say: Say, run: Run, layout: Layout, today: date) -> int | None:
    """Carry out one menu choice; the exit code when a command ran."""
    plan = MENU[picked][1]
    if plan is None:
        for line in describe(status(layout, config.load(layout.root))):
            say(line)
        return None
    try:
        steps = [plan(ask, say, layout, today)]
        if steps[0] == ["parse"]:
            steps.append(["build"])
        for argv in steps:
            say(f"  = {command(['--data', str(layout.root), *argv])}")
        if not ask_yes(ask, "Run it?", True):
            return None
    except Cancelled:
        return None
    code = 0
    for argv in steps:
        code = run(["--data", str(layout.root), *argv]) or code
    say("  done." if code == 0 else f"  finished with exit code {code}: see the counts above.")
    return code


def main(ask: Ask, say: Say, run: Run, today: date | None = None) -> int:
    """The menu loop; returns the exit code of the last command run (0 when none ran)."""
    today = today or date.today()
    say("NSE-pasta: quarterly results, point in time. Type q at any prompt to go back.")
    try:
        root = ask_data(ask, say, Path(os.environ.get("PASTA_DATA", "~/pasta-data")).expanduser())
    except Cancelled:
        return 0
    layout, code = Layout(root), 0
    say("")
    say(f"{root}:")
    for line in describe(status(layout, config.load(root) if root.exists() else config.DEFAULT)):
        say(line)
    while True:
        say("")
        try:
            picked = choose(ask, say, "What next?", [label for label, _ in MENU])
        except Cancelled:
            return code
        if MENU[picked][0] == "Quit":
            return code
        ran = _do(picked, ask, say, run, layout, today)
        code = code if ran is None else ran

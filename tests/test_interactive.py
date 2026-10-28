from datetime import date

from nse_pasta import interactive

TODAY = date(2026, 10, 28)


def _session(answers):
    pending, said, ran = list(answers), [], []

    def ask(prompt):
        said.append(prompt)
        return pending.pop(0)

    def run(argv):
        ran.append(argv)
        return 0

    code = interactive.main(ask, said.append, run, today=TODAY)
    assert pending == [], "the menu asked fewer questions than scripted"
    return code, said, ran


def test_run_everything_with_defaults(tmp_path):
    root = str(tmp_path / "data")
    # data dir, menu 1, universe 1 (nifty50), first quarter end (default), source 1, run it, quit
    code, said, ran = _session([root, "1", "", "", "", "", "7"])
    assert code == 0
    assert ran == [
        ["--data", root, "run", "--universe", "nifty50", "--from", "2020-03-31",
         "--to", "2026-10-28", "--source", "nse"],
    ]  # fmt: skip
    assert any(s.startswith("  = pasta --data") for s in said)


def test_rebuild_runs_parse_then_build(tmp_path):
    root = str(tmp_path / "data")
    _code, _said, ran = _session([root, "3", "", "q"])
    assert ran == [["--data", root, "parse"], ["--data", root, "build"]]


def test_a_data_folder_inside_git_is_refused(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    inside, outside = str(tmp_path / "repo" / "data"), str(tmp_path / "data")
    _code, said, _ran = _session([inside, outside, "7"])
    assert any("inside a git repository" in s for s in said)


def test_command_quotes_only_where_needed():
    assert interactive.command(["--data", "/a b", "as-of", "2025-06-30"]) == (
        "pasta --data '/a b' as-of 2025-06-30"
    )

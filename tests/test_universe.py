from datetime import date

import pytest

from nse_pasta import universe


def test_index_and_equity_lists(fixture):
    index = universe.parse_index_list(fixture("ind_nifty50list.csv"))
    assert index[0] == universe.Company("ADANIENT", "INE423A01024", "Adani Enterprises Ltd.")
    every = universe.parse_equity_list(fixture("EQUITY_L.csv"))
    assert every[0].symbol == "20MICRONS" and every[0].isin == "INE144J01027"
    with pytest.raises(universe.UniverseError):
        universe.parse_index_list(b"<html>blocked</html>")


def test_symbol_file():
    assert [c.symbol for c in universe.parse_symbol_file("tcs\n# a comment\n\nINFY # IT\n")] == [
        "TCS",
        "INFY",
    ]
    rows = universe.parse_symbol_file("name,symbol,isin\nTata,TCS,INE467B01029\n")
    assert rows == [universe.Company("TCS", "INE467B01029")]


def test_spec():
    assert universe.check_spec("NIFTY 50") == "nifty50"
    assert universe.check_spec("file:~/x.txt") == "file:~/x.txt"
    with pytest.raises(universe.UniverseError):
        universe.check_spec("sensex")


def test_a_company_that_leaves_stays(tmp_path):
    first = universe.merge(None, "nifty50", [universe.Company("A"), universe.Company("B")],
                           date(2026, 1, 1))  # fmt: skip
    later = universe.merge(first, "nifty50", [universe.Company("A")], date(2026, 6, 1))
    assert {c.symbol: (c.first_seen, c.last_seen) for c in later.companies} == {
        "A": ("2026-01-01", "2026-06-01"),
        "B": ("2026-01-01", "2026-01-01"),
    }
    assert [
        c.symbol for c in universe.merge(later, "nifty100", [], date(2026, 7, 1)).companies
    ] == []
    path = tmp_path / "universe.json"
    universe.save(path, later)
    assert universe.load(path) == later

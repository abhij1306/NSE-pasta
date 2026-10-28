from datetime import date, datetime, timedelta
from decimal import Decimal

from nse_pasta import growth
from nse_pasta.growth import ResultRow
from nse_pasta.nse import IST

T0 = datetime(2025, 1, 20, 15, 0, tzinfo=IST)


def _row(end, basis="consolidated", revenue="100", eps="1", version=1, at=T0, source="nse"):
    return ResultRow(
        f"X:{end}:{basis}:{source}:v{version}", end, basis, source, "reg33_indas", version, at,
        None if revenue is None else Decimal(revenue), None if eps is None else Decimal(eps),
    )  # fmt: skip


def test_known_at_uses_only_what_was_public():
    v1 = _row(date(2024, 12, 31), revenue="100")
    v2 = _row(date(2024, 12, 31), revenue="90", version=2, at=T0 + timedelta(days=30))
    rows = [v1, v2]
    assert growth.known_at(rows, T0 - timedelta(seconds=1)) == {}
    assert growth.known_at(rows, T0)[(date(2024, 12, 31), "consolidated")] is v1
    assert (
        growth.known_at(rows, T0 + timedelta(days=31))[(date(2024, 12, 31), "consolidated")] is v2
    )


def test_nse_wins_over_screener_and_consolidated_first():
    end = date(2024, 12, 31)
    nse_row, other = _row(end), _row(end, source="screener", revenue="99")
    standalone = _row(end, basis="standalone")
    known = growth.known_at([other, nse_row, standalone], T0)
    assert list(known.values()) == [nse_row]
    both = growth.known_at([other, nse_row, standalone], T0, growth.BOTH)
    assert set(both) == {(end, "consolidated"), (end, "standalone")}


def test_growth_never_mixes_bases():
    now, prior = date(2024, 12, 31), date(2023, 12, 31)
    known = {
        (now, "consolidated"): _row(now, revenue="150"),
        (prior, "standalone"): _row(prior, basis="standalone", revenue="100"),
    }
    assert growth.growth(known, now, set()).reason == "no_common_basis"
    known[(prior, "consolidated")] = _row(prior, revenue="100", eps="-1")
    found = growth.growth(known, now, set())
    assert found.basis == "consolidated" and found.sales_yoy == Decimal("0.5")
    assert found.turnaround is True and found.eps_yoy is None


def test_unit_suspect_20x_either_way_and_left_out():
    quarters = [date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31)]
    rows = [_row(q, revenue="100", at=T0 + timedelta(days=i)) for i, q in enumerate(quarters[:3])]
    rows.append(_row(quarters[3], revenue="2500", at=T0 + timedelta(days=10)))  # lakh vs rupees
    flagged = growth.growth_rows(rows)
    assert [g.unit_suspect for g in flagged] == [False, False, False, True]
    assert growth.unit_suspect(Decimal(4), [Decimal(100), Decimal(100)])
    assert not growth.unit_suspect(Decimal(100), [Decimal(100)])  # too little history


def test_year_ago_and_quarters_before():
    assert growth.year_ago(date(2024, 2, 29)) == date(2023, 2, 28)
    assert growth.quarter_ends_before(date(2025, 3, 31), 2) == [
        date(2024, 12, 31),
        date(2024, 9, 30),
    ]

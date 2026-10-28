from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from nse_pasta import build, universe
from nse_pasta.nse import IST

T = datetime(2025, 1, 20, 15, 0, tzinfo=IST)


def _row(end, version=1, at=T, revenue="100", source="nse", fmt="reg33_indas"):
    return {
        "id": f"X:{end}:consolidated:{source}:v{version}", "symbol": "X", "period_end": end,
        "basis": "consolidated", "source": source, "format": fmt, "version": version,
        "public_at": at, "revenue": Decimal(revenue), "eps_basic": Decimal(1),
        "fiscal_year": "", "fiscal_quarter": "",
    }  # fmt: skip


def test_as_of_reads_only_what_was_public():
    rows = [
        _row(date(2023, 12, 31), at=T - timedelta(days=365), revenue="80"),
        _row(date(2024, 12, 31), revenue="100"),
        _row(date(2024, 12, 31), version=2, at=T + timedelta(days=40), revenue="120"),
    ]
    grown = build.growth_table(rows)
    before = build.as_of(rows, grown, T - timedelta(minutes=1))
    assert [r["period_end"] for r in before] == [date(2023, 12, 31)]
    at = build.as_of(rows, grown, T)
    assert at[-1]["version"] == 1 and at[-1]["sales_yoy"] == Decimal("0.25")
    later = build.as_of(rows, grown, T + timedelta(days=41))
    assert later[-1]["version"] == 2 and later[-1]["sales_yoy"] == Decimal("0.5")


def test_parse_as_of():
    assert build.parse_as_of("2025-06-30") == datetime(2025, 6, 30, 23, 59, 59, tzinfo=IST)
    assert build.parse_as_of("2025-06-30T09:15").tzinfo is IST
    assert build.as_of_stem(datetime(2025, 6, 30, 3, 45, tzinfo=UTC)) == "asof=2025-06-30T0915"


def test_coverage_counts_due_and_missing():
    rows = [_row(date(2024, 3, 31)), _row(date(2024, 6, 30), source="screener")]
    now = datetime(2024, 11, 20, tzinfo=IST)  # Sep quarter due 14 Nov, Dec not ended
    cov = build.coverage([universe.Company("X")], rows, date(2024, 3, 31), date(2024, 12, 31), now)
    (row,) = cov.rows
    assert (row["quarters"], row["due"], row["nse"], row["screener"], row["missing"]) == (
        3,
        3,
        1,
        1,
        1,
    )
    assert row["missing_quarters"] == "2024-09-30"

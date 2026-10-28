from datetime import date
from decimal import Decimal

import pytest

from nse_pasta import xbrl


def test_reg33_q3_quarter_is_not_the_year_to_date(fixture):
    parsed = xbrl.parse(fixture("xbrl_reg33_indas.xml"))  # TCS, Dec 2024, consolidated
    assert parsed.kind.format == "reg33_indas"
    assert (parsed.basis, parsed.period_start, parsed.period_end) == (
        "consolidated",
        date(2024, 10, 1),
        date(2024, 12, 31),
    )
    assert parsed.quarter.revenue == Decimal("639730000000.00")
    assert parsed.quarter.net_profit == Decimal("123800000000.00")
    assert parsed.quarter.eps_basic == Decimal("34.21")
    assert parsed.ytd_start == date(2024, 4, 1)
    assert parsed.ytd.revenue == Decimal("1908450000000.00")  # nine months, never the quarter
    assert parsed.annual is None


def test_bank_interest_earned_is_revenue(fixture):
    parsed = xbrl.parse(fixture("xbrl_reg33_banking.xml"))  # HDFCBANK, Dec 2024
    assert parsed.kind.format == "reg33_banking"
    assert parsed.quarter.revenue == Decimal("850401700000.00")
    assert parsed.quarter.total_income == Decimal("1121939400000.00")
    assert parsed.quarter.eps_diluted == Decimal("23.00")


@pytest.mark.parametrize(
    ("name", "fmt", "revenue", "eps"),
    [
        ("xbrl_integrated_indas.xml", "integrated_indas", "644790000000", "33.79"),
        ("xbrl_integrated_banking.xml", "integrated_banking", "951316300000", "13.43"),
    ],
)
def test_integrated_fills_the_same_fields(fixture, name, fmt, revenue, eps):
    parsed = xbrl.parse(fixture(name))
    assert parsed.kind.format == fmt
    assert parsed.quarter.revenue == Decimal(revenue)
    assert parsed.quarter.eps_basic == Decimal(eps)
    assert parsed.quarter.net_profit is not None and parsed.ytd is not None


def test_insurer_is_metadata_only(fixture):
    parsed = xbrl.parse(fixture("xbrl_integrated_li.xml"))  # HDFCLIFE, Sep 2026
    assert parsed.kind.format == xbrl.INSURANCE
    assert parsed.quarter is None and parsed.period_end == date(2026, 9, 30)


def test_doctype_is_refused(fixture):
    body = fixture("xbrl_reg33_indas.xml").replace(b"?>", b'?><!DOCTYPE x [<!ENTITY e "boom">]>', 1)
    with pytest.raises(xbrl.XbrlError, match="xbrl_doctype"):
        xbrl.parse(body)


def test_money_must_be_inr(fixture):
    body = fixture("xbrl_reg33_indas.xml").replace(b"iso4217:INR<", b"iso4217:USD<", 1)
    with pytest.raises(xbrl.XbrlError, match="unit_not_inr"):
        xbrl.parse(body)


def test_q4_with_only_the_year_is_flagged_annual(fixture):
    # the real Mar 2025 document with its quarter's start moved back to the financial year's
    body = fixture("xbrl_integrated_indas.xml").replace(b">2025-01-01<", b">2024-04-01<")
    parsed = xbrl.parse(body)
    assert parsed.quarter is None and parsed.annual is not None
    assert parsed.period_start == date(2025, 1, 1)  # the derived Q4's own quarter


def test_figures_minus_and_quarter_start():
    a = xbrl.Figures(Decimal(10), None, Decimal(4), Decimal(2), Decimal(2))
    b = xbrl.Figures(Decimal(7), Decimal(1), Decimal(3), Decimal("1.5"), None)
    assert a.minus(b) == xbrl.Figures(Decimal(3), None, Decimal(1), Decimal("0.5"), None)
    assert xbrl.quarter_start(date(2025, 3, 31)) == date(2025, 1, 1)
    assert xbrl.quarter_start(date(2024, 12, 31)) == date(2024, 10, 1)


def test_eps_copied_into_discontinued_is_corrected(fixture):
    # MARUTI, Mar 2024: continuing 125.71, "discontinued" 125.71, total 251.42 as filed
    parsed = xbrl.parse(fixture("xbrl_reg33_indas_eps_copied.xml"))
    assert parsed.eps_corrected
    assert parsed.quarter.eps_basic == parsed.quarter.eps_diluted == Decimal("125.71")
    assert parsed.ytd.eps_basic == Decimal("429.01")
    assert not xbrl.parse(fixture("xbrl_reg33_indas.xml")).eps_corrected

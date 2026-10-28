from datetime import date
from decimal import Decimal

from nse_pasta import screener


def test_consolidated_page(fixture):
    quarters = screener.parse_page(fixture("screener_tcs_consolidated.html"))
    assert len(quarters) == 13  # the public page shows the latest 13 quarters
    assert quarters[0].period_end == date(2023, 9, 30)
    last = quarters[-1]
    assert (last.period_end, last.basis) == (date(2026, 9, 30), "consolidated")
    assert last.revenue == Decimal("731880000000")  # 73,188 crore
    assert last.eps_basic == Decimal("38.37")


def test_bank_page_reads_revenue(fixture):
    quarters = screener.parse_page(fixture("screener_hdfcbank_consolidated.html"))
    assert quarters[-1].revenue == Decimal("951320000000")
    assert quarters[-1].net_profit == Decimal("215370000000")


def test_a_page_without_the_table_has_no_quarters():
    assert screener.parse_page(b"<html><body>Please log in</body></html>") == []


def test_robots_wildcards_are_honoured(fixture):
    robots = fixture("screener_robots.txt")
    base = "https://www.screener.in"
    assert screener.allowed(robots, screener.page_url(base, "TCS", "consolidated"))
    assert screener.allowed(robots, screener.page_url(base, "M&M", "standalone"))
    assert not screener.allowed(robots, base + "/company/source/quarter/123/2025/")
    assert not screener.allowed(robots, base + "/company/TCS/?q=1")
    assert not screener.allowed(b"", base + "/company/TCS/")  # no robots.txt: ask nothing
    assert not screener.allowed(b"User-agent: *\nDisallow: /\n", base + "/company/TCS/")

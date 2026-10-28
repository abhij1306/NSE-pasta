"""The parse step on recorded answers: real (trimmed) listings, announcements and documents
put into a cache as a fetch would have."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from nse_pasta import config, fetch, parse
from nse_pasta.nse import IST
from nse_pasta.raw import RawCache
from nse_pasta.universe import Company

CFG = config.DEFAULT
TCS = Company("TCS", "INE467B01029", "Tata Consultancy Services Ltd.")
DOC = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1412101_11042025074137_WEB.xml"
WINDOW = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=TCS&from_date=09-04-2025&to_date=12-04-2025"


@pytest.fixture
def caches(tmp_path, fixture):
    nse_cache, screener_cache = RawCache(tmp_path / "nse"), RawCache(tmp_path / "screener")
    nse_cache.put(fetch.listing_urls(CFG, "TCS")[1][1], 200, fixture("listing_integrated_tcs.json"))
    nse_cache.put(DOC, 200, fixture("xbrl_integrated_indas.xml"))
    nse_cache.put(WINDOW, 200, fixture("announcements_tcs_2025-04.json"))
    url = "https://www.screener.in/company/TCS/consolidated/"
    screener_cache.put(url, 200, fixture("screener_tcs_consolidated.html"))
    return nse_cache, screener_cache


def _parse(caches, start=date(2025, 3, 31), end=date(2025, 3, 31)):
    nse_cache, screener_cache = caches
    rows, outcomes, report = parse.parse(nse_cache, screener_cache, CFG, [TCS], start, end)
    return rows, outcomes, report


def test_a_filing_becomes_a_row_dated_by_its_announcement(caches):
    rows, outcomes, _ = _parse(caches)
    (row,) = rows  # consolidated first: the standalone filing is not read
    assert row["id"] == "TCS:2025-03-31:consolidated:nse:v1"
    assert (row["fiscal_year"], row["fiscal_quarter"]) == ("FY2025", "Q4")
    assert row["revenue"] == Decimal("644790000000")
    assert row["public_at"] == datetime(2025, 4, 10, 16, 5, 24, tzinfo=IST)
    assert row["public_at_source"] == "announcement"
    assert row["xbrl_at"] == datetime(2025, 4, 11, 7, 41, 38, tzinfo=IST)
    assert [o.result for o in outcomes] == ["stored"]


def test_a_document_not_fetched_is_excluded_with_its_reason(caches, tmp_path, fixture):
    nse_cache = RawCache(tmp_path / "empty")
    nse_cache.put(fetch.listing_urls(CFG, "TCS")[1][1], 200, fixture("listing_integrated_tcs.json"))
    rows, _outcomes, report = parse.parse(
        nse_cache, caches[1], CFG, [TCS], date(2025, 3, 31), date(2025, 3, 31)
    )
    assert report.excluded == {"not_fetched": 1}
    # NSE has no row, so screener.in's consolidated figures fill the quarter, dated by the
    # deadline (no announcement in this cache for it), flagged estimated
    assert [r["source"] for r in rows] == ["screener"]
    assert rows[0]["public_at_source"] == "deadline" and rows[0]["public_at_estimated"]


def test_screener_fills_only_quarters_nse_does_not_give(caches):
    rows, _, report = _parse(caches, start=date(2024, 12, 31), end=date(2025, 6, 30))
    by_quarter = {(r["period_end"], r["source"]) for r in rows}
    assert (date(2025, 3, 31), "nse") in by_quarter
    assert (date(2025, 3, 31), "screener") not in by_quarter
    assert {(date(2024, 12, 31), "screener"), (date(2025, 6, 30), "screener")} <= by_quarter
    assert report.screener_rows == 2


def test_a_changed_filing_is_a_new_version_and_the_same_one_adds_none(caches, fixture):
    nse_cache, _ = caches
    work = parse.CompanyParse(nse_cache, TCS, [])
    listed = fetch.company_filings(nse_cache, CFG, TCS)
    filings = fetch.wanted(listed, date(2025, 3, 31), date(2025, 3, 31), "consolidated-first")
    work.nse(filings)
    revised = fixture("xbrl_integrated_indas.xml").replace(b">644790000000<", b">644800000000<")
    other = DOC.replace("1412101", "1412999")
    nse_cache.put(other, 200, revised)
    later = replace(filings[0], xbrl_url=other, created_at=datetime(2025, 5, 2, 10, 0, tzinfo=IST))
    work.nse([later])
    assert [(r["version"], r["revision"], r["supersedes_id"]) for r in work.rows] == [
        (1, False, ""),
        (2, True, "TCS:2025-03-31:consolidated:nse:v1"),
    ]
    assert work.rows[1]["public_at"] == datetime(2025, 5, 2, 10, 0, tzinfo=IST)  # its own filing
    nse_cache.put(DOC.replace("1412101", "1413000"), 200, revised + b"\n")
    work.nse([replace(later, xbrl_url=DOC.replace("1412101", "1413000"))])
    assert work.outcomes[-1].result == "same_figures"


def test_fiscal():
    assert parse.fiscal(date(2024, 12, 31)) == ("FY2025", "Q3")
    assert parse.fiscal(date(2025, 6, 30)) == ("FY2026", "Q1")

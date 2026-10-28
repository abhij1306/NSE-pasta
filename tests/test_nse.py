from datetime import date, datetime

from nse_pasta import nse

IST = nse.IST


def test_reg33_listing(fixture):
    filings = nse.parse_results_listing(fixture("listing_reg33_tcs.json"))
    assert [(f.period_end, f.basis, f.seq) for f in filings] == [
        (date(2024, 12, 31), "consolidated", "1189599"),
        (date(2024, 12, 31), "standalone", "1189595"),
        (date(2018, 6, 30), "consolidated", "1046512"),
    ]
    assert filings[0].broadcast_at == datetime(2025, 1, 9, 21, 39, 43, tzinfo=IST)
    assert filings[0].isin == "INE467B01029"
    assert filings[0].markers == "New/Ind-AS New/N"
    assert filings[2].xbrl_url is None  # listed as ".../-": no XBRL


def test_integrated_listing(fixture):
    filings = nse.parse_integrated_listing(fixture("listing_integrated_tcs.json"))
    assert {f.basis for f in filings} == {"consolidated", "standalone"}
    first = filings[0]
    assert first.listing == nse.LISTING_INTEGRATED and first.period_end == date(2025, 3, 31)
    assert first.created_at == datetime(2025, 4, 11, 7, 41, 38, tzinfo=IST)
    assert not first.revision


def test_insurance_listing_reads_period_end(fixture):
    filings = nse.parse_results_listing(fixture("listing_insurance.json"), nse.LISTING_INSURANCE)
    assert filings and all(f.period_end == date(2024, 12, 31) for f in filings)


def test_listing_shape_is_checked(fixture):
    assert nse.listing_ok(nse.LISTING_REG33, fixture("listing_reg33_tcs.json"))
    assert nse.listing_ok(nse.LISTING_INTEGRATED, fixture("listing_integrated_tcs.json"))
    assert not nse.listing_ok(nse.LISTING_REG33, b"<html>Access Denied</html>")
    assert not nse.listing_ok(nse.LISTING_INTEGRATED, b"[]")


def test_results_announcement_rules(fixture):
    items = nse.parse_announcements(fixture("announcements_tcs_2025-04.json"))
    rules = {i.desc: nse.results_rule(i) for i in items}
    assert rules == {
        "Press Release": "",
        "Dividend": "",
        "Outcome of Board Meeting": "board_outcome_bare",  # names neither results nor quarter
    }
    named = nse.Announcement("X", items[0].at, "Outcome of Board Meeting", "the financial results")
    assert nse.results_rule(named) == "board_outcome"
    updates = nse.Announcement("X", items[0].at, "Financial Result Updates", "")
    assert nse.results_rule(updates) == "result_updates"


def test_nse_time():
    assert nse.nse_time("16-JAN-2025 20:20") == datetime(2025, 1, 16, 20, 20, tzinfo=IST)
    assert nse.nse_time("30-JUN-2026") == datetime(2026, 6, 30, tzinfo=IST)
    assert nse.nse_time("-") is None

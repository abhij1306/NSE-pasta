from datetime import date, datetime

from nse_pasta import nse, timing
from nse_pasta.nse import IST, Announcement, Filing


def _filing(**kw):
    base = dict(
        listing="reg33", symbol="X", isin="", seq="1", period_end=date(2019, 3, 31),
        basis="consolidated", broadcast_at=None, created_at=None, xbrl_url=None,
        revision=False, markers="",
    )  # fmt: skip
    return Filing(**(base | kw))


def test_name_stamp_time_is_never_used():
    url = "https://x/INTEGRATED_FILING_INDAS_1_17072026075004_WEB.xml"  # filed 19:50:04
    assert timing.stamp_date(url) == date(2026, 7, 17)


def test_a_rebroadcast_listing_time_is_not_the_filing_time():
    # RELIANCE Mar 2019: listed 06-May-2019, the file name says 19-Apr-2019
    filing = _filing(
        broadcast_at=datetime(2019, 5, 6, 10, 0, tzinfo=IST),
        xbrl_url="https://x/INDAS_1_2_19042019053000.xml",
    )
    filed = timing.xbrl_at(filing)
    assert filed == timing.FiledAt(datetime(2019, 4, 19, 23, 59, 59, tzinfo=IST), True)
    same_day = _filing(
        broadcast_at=datetime(2019, 4, 19, 17, 30, tzinfo=IST),
        xbrl_url="https://x/INDAS_1_2_19042019053000.xml",
    )
    assert timing.xbrl_at(same_day) == timing.FiledAt(same_day.broadcast_at, False)


def test_public_at_is_the_earlier_of_announcement_and_filing():
    filed = timing.FiledAt(datetime(2024, 7, 21, 12, 48, tzinfo=IST), False)
    announced = datetime(2024, 7, 20, 14, 15, tzinfo=IST)
    assert timing.public_at(1, announced, filed) == timing.PublicAt(
        announced, "announcement", False
    )
    assert timing.public_at(1, None, filed).source == "xbrl"
    # a revision is public from its own filing, never from the original's announcement
    assert timing.public_at(2, announced, filed).at == filed.at
    estimated = timing.FiledAt(datetime(2024, 7, 21, 23, 59, 59, tzinfo=IST), True)
    assert timing.public_at(1, None, estimated) == timing.PublicAt(estimated.at, "xbrl_date", True)


def test_announcement_read_12_hours_early():
    filed = timing.FiledAt(datetime(2025, 4, 24, 20, 32, tzinfo=IST), False)
    early = datetime(2025, 4, 24, 5, 8, tzinfo=IST)
    assert timing.pm_fix(early, filed) == datetime(2025, 4, 24, 17, 8, tzinfo=IST)
    assert timing.pm_fix(datetime(2025, 4, 24, 10, 0, tzinfo=IST), filed).hour == 10


def test_a_bare_board_outcome_dates_the_integrated_q4(fixture):
    # TCS Mar 2025: the outcome says only "Outcome of Board Meeting held on April 10, 2025"
    items = timing.results_announcements(
        nse.parse_announcements(fixture("announcements_tcs_2025-04.json"))
    )
    found = timing.match_announcement(items, date(2025, 4, 11), date(2025, 3, 31))
    assert found.at == datetime(2025, 4, 10, 16, 5, 24, tzinfo=IST)
    # ... but not when the filing is two days later
    assert timing.match_announcement(items, date(2025, 4, 12), date(2025, 3, 31)) is None


def test_an_announcement_naming_another_quarter_is_skipped():
    at = datetime(2021, 7, 20, 15, 0, tzinfo=IST)
    other = Announcement("X", at, "Financial Result Updates", "results for March 31, 2021")
    this = Announcement(
        "X", at.replace(hour=16), "Financial Result Updates", "quarter ended 30.06.2021"
    )
    found = timing.match_announcement([other, this], date(2021, 7, 20), date(2021, 6, 30))
    assert found is this


def test_deadline():
    assert timing.deadline(date(2024, 12, 31)) == datetime(2025, 2, 14, 23, 59, tzinfo=IST)
    assert timing.deadline(date(2025, 3, 31)) == datetime(2025, 5, 30, 23, 59, tzinfo=IST)


def test_quarter_announcement_ignores_bare_outcomes(fixture):
    items = timing.results_announcements(
        nse.parse_announcements(fixture("announcements_tcs_2025-04.json"))
    )
    assert timing.quarter_announcement(items, date(2025, 3, 31), set()) is None

from nse_pasta import doctor
from nse_pasta.http import Fetched


def test_each_answer_is_classified(fixture):
    listing = fixture("listing_reg33.json")
    assert doctor.classify(Fetched(200, listing), doctor._valid_reg33) == "ok"
    assert doctor.classify(Fetched(404), doctor._valid_reg33) == "not_found"
    assert doctor.classify(Fetched(0), doctor._valid_reg33) == "blocked"
    assert doctor.classify(Fetched(200, b"<html>denied</html>"), doctor._valid_reg33) == "blocked"
    assert doctor.classify(Fetched(200, b'[{"x": 1}]'), doctor._valid_reg33) == "format_changed"
    xml = fixture("xbrl_reg33_indas.xml")
    assert doctor.classify(Fetched(200, xml), doctor._valid_xbrl, markup=True) == "ok"


def test_report_says_what_to_do():
    probes = [
        doctor.Probe("reg33 listing", "ok", "u"),
        doctor.Probe("announcements", "blocked", "v"),
    ]
    lines = doctor.report(probes)
    assert "blocked (announcements):" in lines


class Answers:
    """Answers by URL (without its query); any other URL is a 404."""

    def __init__(self, answers):
        self.answers = answers

    def get(self, url, params=None, referer=None):
        return self.answers.get(url.split("?")[0], Fetched(404))


def test_company_probes_ask_about_the_first_listed_company(fixture):
    from nse_pasta import config

    index = config.DEFAULT.sources.index_list.format(name="ind_nifty50list.csv")
    assert doctor.first_symbol(fixture("ind_nifty50list.csv")) == "ABC"
    probes = doctor.run(Answers({}), Answers({}), config.DEFAULT)
    assert probes[0].status == "not_found"
    assert {p.status for p in probes[2:]} == {"blocked"}  # no company to ask about
    found = doctor.run(Answers({index: Fetched(200, fixture("ind_nifty50list.csv"))}),
                       Answers({}), config.DEFAULT)  # fmt: skip
    assert "symbol=ABC" in found[2].detail

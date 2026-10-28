from nse_pasta import doctor
from nse_pasta.http import Fetched


def test_each_answer_is_classified(fixture):
    listing = fixture("listing_reg33_tcs.json")
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

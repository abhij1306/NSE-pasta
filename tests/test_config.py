from datetime import date

import pytest

from nse_pasta import config


def test_defaults_round_trip():
    assert config.parse(config.render(config.DEFAULT)) == config.DEFAULT
    assert config.DEFAULT.network.interval == 2.0
    assert config.DEFAULT.screener.interval == 3.0


def test_settings_are_read_and_checked():
    cfg = config.parse('[run]\nfrom = 2018-03-31\nuniverse = "nifty500"\nsource = "both"\n')
    assert (cfg.run.start, cfg.run.universe, cfg.run.source) == (
        date(2018, 3, 31),
        "nifty500",
        "both",
    )
    for bad in ('[run]\nsource = "bse"\n', "[network]\ninterval = 0\n", "[nope]\n",
                '[sources]\nresults_api = "ftp://x"\n', "[run]\nfromm = 1\n"):  # fmt: skip
        with pytest.raises(config.ConfigError):
            config.parse(bad)

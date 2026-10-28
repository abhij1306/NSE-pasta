from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    """The bytes of a fixture: an answer in NSE's (or screener.in's) real shape, trimmed, with
    invented names, codes, times and figures."""
    return lambda name: (FIXTURES / name).read_bytes()

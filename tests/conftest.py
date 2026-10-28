from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    """The bytes of a recorded, trimmed real answer in tests/fixtures/."""
    return lambda name: (FIXTURES / name).read_bytes()

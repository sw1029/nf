import pytest


EXPECTED_MARKERS = {"smoke", "unit", "integration", "placeholder"}


@pytest.mark.smoke
def test_pytest_markers_registered(pytestconfig: pytest.Config) -> None:
    registered = {m.split(":")[0].strip() for m in pytestconfig.getini("markers")}
    missing = EXPECTED_MARKERS - registered
    assert not missing, f"Missing markers in pytest.ini: {sorted(missing)}"


@pytest.mark.placeholder
def test_testpath_configuration(pytestconfig: pytest.Config) -> None:
    testpaths = pytestconfig.getini("testpaths")
    assert "tests" in testpaths, "testpaths should include the tests directory."


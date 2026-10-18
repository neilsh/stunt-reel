"""Basic smoke tests for stunt_reel Python package."""

from stunt_reel import __version__, version


def test_package_version() -> None:
    assert version() == "0.1.0"
    assert __version__ == "0.1.0"

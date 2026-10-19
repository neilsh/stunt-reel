"""Basic smoke tests for stunt_reel Python package."""

from importlib.metadata import version as distribution_version

from stunt_reel import __version__, version


def test_package_version() -> None:
    assert __version__ == distribution_version("stunt-reel")
    assert version() == __version__

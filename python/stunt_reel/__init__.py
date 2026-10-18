"""Stunt Reel Python tooling and automation package."""

from . import tac

__version__ = "0.1.0"
stunt_tac = tac


def version() -> str:
    """Return the package version string."""
    return __version__


__all__ = ["__version__", "stunt_tac", "tac", "version"]

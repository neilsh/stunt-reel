"""Errors every emulator wrapper raises; the wrapper itself is [`automation`](automation.py).

The DOSBox-X process and its debugger connection (ADR 0021) are retired, see
research/playone-exe/dosbox-x-legacy.md.
"""

from __future__ import annotations

__all__ = ["EmulatorUnavailable", "GuestTimeout"]


class EmulatorUnavailable(RuntimeError):  # noqa: N818 - the agreed interface name
    """The emulator executable is not installed or not on PATH."""


class GuestTimeout(RuntimeError):  # noqa: N818 - the agreed interface name
    """The guest did not come up or did not finish within its budget."""

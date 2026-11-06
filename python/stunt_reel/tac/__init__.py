"""Test Automation and Capture (TAC) harness for Stunt Reel.

Capture runs on dosbox-automation as plans (generated Lua, [`plan`](plan.py)).
"""

from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout
from stunt_reel.tac.framebuffer import capture

__all__ = [
    "EmulatorUnavailable",
    "GuestTimeout",
    "capture",
]

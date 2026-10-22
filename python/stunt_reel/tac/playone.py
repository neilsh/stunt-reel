"""Drive ``PLAYONE.EXE``'s LOAD FILM dialog and sample frames deterministically.

The parity capture owns the emulator through DOSBox-X's debugger, and this build
imposes two hard constraints the driver is built around:

* any debugger command issued while ``PLAYONE.EXE`` is still unpacking (roughly the
  first two seconds) kills the guest with an ``Illegal Unhandled Interrupt Called 6``
  storm, and reads of DGROUP during the load can crash the emulator outright, so the
  driver touches nothing until the dialog has settled on screen; and
* ``VRT`` after Mode 13h playback starts crashes the emulator (``0xC0000409``), so
  frames are sampled through the documented post-retrace trap at ``0D51:0C5E``: an
  execution breakpoint plus ``RUN`` stops the guest once per rendered frame.

Keystrokes only reach ``INT 16h`` while the guest free-runs, so the dialog is driven
by writing words into the BIOS keyboard ring buffer and letting the guest poll them.
"""

from __future__ import annotations

from stunt_reel.tac.bda import KEY_DOWN, KEY_ENTER, BdaInjector, char_to_key
from stunt_reel.tac.client import TacClient

__all__ = [
    "DGROUP_RUNTIME_SEG",
    "DGROUP_SEG",
    "FILM_CLOCK_OFFSET",
    "FILM_PREFIX_LETTER",
    "GLOBAL_TICK_OFFSET",
    "VBLANK_TRAP",
    "arm_frame_trap",
    "confirm_film",
    "next_frame",
]

#: Real-mode segment of ``PLAYONE.EXE``'s DGROUP, which holds both code and data.
DGROUP_SEG: str = "0D51"
#: Runtime ``DS`` (the DGROUP segment while playing), observed live in the T11 check. The
#: debugger exposes no register read, so captures take it as a parameter defaulting to this.
DGROUP_RUNTIME_SEG: int = 0x1575
#: ``DS`` offset of the active film clock, 50 Hz ticks into the film (``# [MEM-FLM-TICK]``).
FILM_CLOCK_OFFSET: int = 0x4896
#: ``DS`` offset of the global 50 Hz timer tick, which trails the film clock by about 5.
GLOBAL_TICK_OFFSET: int = 0x22B8
#: Code offset immediately after the vertical retrace wait loop (``# [MEM-VSYNC-03DA]``).
VBLANK_TRAP: str = f"{DGROUP_SEG}:0C5E"
#: First letter of the film to play; jumps the listbox to ``CTRY.ALL``.
FILM_PREFIX_LETTER: str = "c"


def confirm_film(client: TacClient) -> None:
    """Select ``CTRY.FLM`` in the open dialog and confirm it.

    The listbox starts on ``[..]``; the prefix jump lands on ``CTRY.ALL`` (the first
    entry starting with ``C``), one Down selects ``CTRY.FLM``, and Enter confirms.
    Each keystroke is queued in the BIOS Data Area and consumed by the guest's
    ``INT 16h`` poll while the emulator free-runs.
    """
    BdaInjector.inject_keys(client, [char_to_key(FILM_PREFIX_LETTER)])
    BdaInjector.inject_keys(client, [KEY_DOWN])
    BdaInjector.inject_keys(client, [KEY_ENTER])


def arm_frame_trap(client: TacClient) -> None:
    """Stop the guest at the post-retrace trap so every sample is a whole frame."""
    client.execute(f"BP {VBLANK_TRAP}")


def next_frame(client: TacClient) -> None:
    """Run the guest to the next post-retrace trap hit."""
    client.resume()

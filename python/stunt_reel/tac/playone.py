"""Addresses and dialog keys for driving PLAYONE.EXE through the TAC harness.

The parity capture owns the emulator through DOSBox-X's debugger, and this build
imposes two hard constraints the driver is built around:

* any debugger command issued while PLAYONE.EXE is still unpacking (roughly the
  first two seconds) kills the guest with an Illegal Unhandled Interrupt Called 6
  storm, and reads of DGROUP during the load can crash the emulator outright, so
  the driver touches nothing until the dialog has settled on screen; and
* VRT after Mode 13h playback starts crashes the emulator (0xC0000409), so frames
  are sampled through the documented post-retrace trap at 0D51:0C5E: an
  execution breakpoint plus RUN stops the guest once per rendered frame.

Keystrokes only reach INT 16h while the guest free-runs, so the dialog is driven
by writing words into the BIOS keyboard ring buffer (bda.py) and letting the
guest poll them.
"""

from __future__ import annotations

from stunt_reel.tac.bda import KEY_DOWN, KEY_ENTER, char_to_key

__all__ = [
    "DGROUP_RUNTIME_SEG",
    "DGROUP_SEG",
    "FILM_CLOCK_OFFSET",
    "FILM_PREFIX_LETTER",
    "GLOBAL_TICK_OFFSET",
    "VBLANK_TRAP",
    "film_selection_keys",
]

#: Real-mode segment of PLAYONE.EXE's DGROUP, which holds both code and data.
DGROUP_SEG: str = "0D51"
#: Runtime DS (the DGROUP segment while playing), observed live in the T11 check. The
#: debugger exposes no register read, so captures take it as a parameter defaulting to this.
DGROUP_RUNTIME_SEG: int = 0x1575
#: DS offset of the active film clock, 50 Hz ticks into the film (# [MEM-FLM-TICK]).
FILM_CLOCK_OFFSET: int = 0x4896
#: DS offset of the global 50 Hz timer tick, whose offset from the film clock is not constant (memory.md 3.2).
GLOBAL_TICK_OFFSET: int = 0x22B8
#: Code offset immediately after the vertical retrace wait loop (# [MEM-VSYNC-03DA]).
VBLANK_TRAP: str = f"{DGROUP_SEG}:0C5E"
#: First letter of the film to play when a name is missing; jumps the listbox.
FILM_PREFIX_LETTER: str = "c"


def film_selection_keys(name: str) -> list[tuple[int, int]]:
    """BIOS keystrokes that select the film whose file name starts with name[0].

    The listbox starts on [..]; the prefix jump lands on the first entry starting with
    the letter (the film's .ALL, when VAULT holds only that film's pair), one Down
    selects its .FLM, and Enter confirms.
    """
    letter = name[:1].lower() or FILM_PREFIX_LETTER
    return [char_to_key(letter), KEY_DOWN, KEY_ENTER]

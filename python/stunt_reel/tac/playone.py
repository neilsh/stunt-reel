"""Addresses and dialog keys for driving PLAYONE.EXE through dosbox-automation.

A run is a plan (``plan.py``): Lua traces the film clock per emulated frame, then replays the
boot and dumps the frames Python picked. The dialog is driven by ``KBD_*`` key names in the
generated Lua (``film_selection_names``); the ``film_selection_keys`` scan codes and the DOSBox-X
segment constants remain for the offline streamer model and its notes
(``research/playone-exe/dosbox-x-legacy.md``).
"""

from __future__ import annotations

from stunt_reel.tac.bda import KEY_DOWN, KEY_ENTER, char_to_key

__all__ = [
    "AUTOMATION_DS",
    "DGROUP_PARAGRAPH",
    "DGROUP_RUNTIME_SEG",
    "DGROUP_SEG",
    "FILM_CLOCK_OFFSET",
    "FILM_PREFIX_LETTER",
    "GLOBAL_TICK_OFFSET",
    "IMAGE_PARAGRAPH",
    "VBLANK_TRAP",
    "WORKING_PALETTE_OFFSET",
    "film_selection_keys",
    "film_selection_names",
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
#: DGROUP paragraph within the image, and the paragraph dosbox-automation loads the image at.
DGROUP_PARAGRAPH: int = 0x0D51
IMAGE_PARAGRAPH: int = 0x01F5
#: Runtime DS under dosbox-automation (DOSBox-X's is DGROUP_RUNTIME_SEG): image + DGROUP.
AUTOMATION_DS: int = IMAGE_PARAGRAPH + DGROUP_PARAGRAPH
#: DS offset of the working palette in 6-bit DAC units (768 bytes).
WORKING_PALETTE_OFFSET: int = 0x2768


def film_selection_keys(name: str) -> list[tuple[int, int]]:
    """BIOS keystrokes that select the film whose file name starts with name[0].

    The listbox starts on [..]; the prefix jump lands on the first entry starting with
    the letter (the film's .ALL, when VAULT holds only that film's pair), one Down
    selects its .FLM, and Enter confirms.
    """
    letter = name[:1].lower() or FILM_PREFIX_LETTER
    return [char_to_key(letter), KEY_DOWN, KEY_ENTER]


def film_selection_names(name: str) -> list[str]:
    """The same dialog sequence as :func:`film_selection_keys`, as dosbox-automation key names."""
    letter = name[:1].lower() or FILM_PREFIX_LETTER
    return [f"KBD_{letter}", "KBD_down", "KBD_enter"]

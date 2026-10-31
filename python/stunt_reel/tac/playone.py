"""Addresses and dialog keys for driving PLAYONE.EXE through dosbox-automation.

A run is a plan (``plan.py``): Lua traces the film clock per emulated frame, then replays the
boot and dumps the frames Python picked. The dialog is driven by ``KBD_*`` key names in the
generated Lua (``film_selection_names``); the ``film_selection_keys`` scan codes and the DOSBox-X
segment constants remain for the offline streamer model and its notes
(``research/playone-exe/dosbox-x-legacy.md``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel.tac.bda import KEY_DOWN, KEY_ENTER, char_to_key

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "AUTOMATION_DS",
    "DGROUP_PARAGRAPH",
    "DGROUP_RUNTIME_SEG",
    "DGROUP_SEG",
    "FILM_CLOCK_OFFSET",
    "FILM_PREFIX_LETTER",
    "GLOBAL_TICK_OFFSET",
    "IMAGE_PARAGRAPH",
    "LAYOUTS",
    "PATCH3",
    "UNPATCHED",
    "VBLANK_TRAP",
    "WORKING_PALETTE_OFFSET",
    "PlayoneLayout",
    "UnknownBuild",
    "film_selection_keys",
    "film_selection_names",
    "layout_for",
]

#: Real-mode segment of PLAYONE.EXE's DGROUP, which holds both code and data.
DGROUP_SEG: str = "0D51"
#: Runtime DS under the retired DOSBox-X harness, observed live in the T11 check. Only the
#: offline streamer model (``vsync.py``, ``MockTransport``) uses it; live runs use AUTOMATION_DS.
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


class UnknownBuild(ValueError):  # noqa: N818 - names the condition, like NoArchive
    """A PLAYONE.EXE whose hash matches no known layout, so its offsets are unknown."""


@dataclass(frozen=True)
class PlayoneLayout:
    """Where one build of PLAYONE.EXE keeps what a capture reads, identified by its SHA-256.

    Offsets are DS-relative. Patch #3 relinked the program: its DGROUP starts 0xE0 paragraphs
    lower and every data offset the harness reads moved down by 0x67A
    (``research/playone-exe/patch3.md``).
    """

    name: str
    sha256: str
    dgroup_paragraph: int
    film_clock: int
    global_tick: int
    working_palette: int

    @property
    def ds(self) -> int:
        """Runtime DS under dosbox-automation: the load paragraph plus DGROUP's."""
        return IMAGE_PARAGRAPH + self.dgroup_paragraph


#: The 1992 PLAYONE.EXE that ``corpus/stuntisl`` and the demo ship (102,703 bytes).
UNPATCHED = PlayoneLayout(
    name="unpatched",
    sha256="3c93493c5ec4eb64e4942ccaaa77d3fdb658fb5b5ab0f2454e57590ffe9977f4",
    dgroup_paragraph=DGROUP_PARAGRAPH,
    film_clock=FILM_CLOCK_OFFSET,
    global_tick=GLOBAL_TICK_OFFSET,
    working_palette=WORKING_PALETTE_OFFSET,
)
#: Patch #3's PLAYONE.EXE (97,790 bytes; ``mise run game-builds`` puts it in the patched tree).
PATCH3 = PlayoneLayout(
    name="patch3",
    sha256="fc532c94e4ff3e70bffdc3c51b72cce5f5a20e5d502256bb9fb58c3c4f411769",
    dgroup_paragraph=0x0C71,
    film_clock=0x421C,
    global_tick=0x1C3E,
    working_palette=0x20EE,
)
LAYOUTS: tuple[PlayoneLayout, ...] = (UNPATCHED, PATCH3)


def layout_for(exe: Path) -> PlayoneLayout:
    """The layout of the PLAYONE.EXE at *exe*; raises UnknownBuild for any other file."""
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    for layout in LAYOUTS:
        if layout.sha256 == digest:
            return layout
    known = ", ".join(f"{layout.name} {layout.sha256[:8]}" for layout in LAYOUTS)
    raise UnknownBuild(f"{exe} (sha256 {digest[:8]}) is no known PLAYONE.EXE build ({known})")


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

"""Stage a film, start DOSBox-X with the debugger link, and drive PLAYONE to the film.

The sequence follows what the retired DOSBox-X harness found safe
(`research/playone-exe/dosbox-x-legacy.md`): nothing but `A000` page dumps until the film dialog
has settled, then the film's keys through the BIOS keyboard buffer at `0040:001E..003D`.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dbx.link import Link, LinkError, Listener
from stunt_reel import dataroot, game_builds
from stunt_reel.tac import staging
from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout
from stunt_reel.tac.playone import film_selection_names

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DOSBOX_X_VERSION: str = "2026.10.01"
MISE_TOOL: str = f"github:joncampbell123/dosbox-x@dosbox-x-v{DOSBOX_X_VERSION}"
#: The SDL1 build, the one the 2026-11-04 spike ran (SDL2 was chosen for OpenGL, unused here).
EXE_IN_TOOL: str = "bin/x64/Release/dosbox-x.exe"
TEMPLATE: Path = Path(__file__).resolve().parents[3] / "tools" / "dosbox-x" / "dosbox-x.conf"

BDA_SEGMENT: int = 0x40
BDA_HEAD: int = 0x1A
BDA_TAIL: int = 0x1C
BDA_START: int = 0x1E
BDA_END: int = 0x3E

KEY_DOWN: tuple[int, int] = (0x00, 0x50)
KEY_ENTER: tuple[int, int] = (0x0D, 0x1C)

#: PC scan codes for the characters a film's selection letter can be.
_SCAN_CODES: dict[str, int] = {
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09,
    "9": 0x0A, "0": 0x0B, "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15,
    "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19, "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21,
    "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26, "z": 0x2C, "x": 0x2D, "c": 0x2E,
    "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32, ".": 0x34, "-": 0x0C, "_": 0x0C,
}  # fmt: skip

#: The film dialog is up once this many identical page dumps in a row each hold this many colours.
SETTLE_PAGES: int = 5
DIALOG_COLOURS: int = 6
DIALOG_DUMPS: int = 600
DUMP_GAP: float = 0.1
KEY_GAP: float = 1.0
ACCEPT_TIMEOUT: float = 60.0


def dosbox_x_exe() -> Path:
    """The pinned DOSBox-X binary, from mise."""
    mise = shutil.which("mise")
    if mise is None:
        msg = "mise is not on PATH"
        raise EmulatorUnavailable(msg)
    try:
        where = subprocess.run(  # noqa: S603 - fixed argv, mise resolved from PATH
            [mise, "where", MISE_TOOL], capture_output=True, text=True, check=True, timeout=60
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"mise cannot find {MISE_TOOL} (run mise install): {exc}"
        raise EmulatorUnavailable(msg) from exc
    exe = Path(where) / EXE_IN_TOOL
    if not exe.is_file():
        msg = f"{exe} is missing"
        raise EmulatorUnavailable(msg)
    return exe


def render_conf(template: str, *, mount: Path, cycles: int) -> str:
    """The conf for one run: *template* with its mount path and cycle count filled in."""
    return template.replace("{mount}", mount.as_posix()).replace("{cycles}", str(cycles))


class DialogSettle:
    """Feed `A000` page dumps; True once the film dialog has stopped changing."""

    def __init__(self) -> None:
        self._last = b""
        self._run = 0

    def feed(self, page: bytes) -> bool:
        """Whether *page* completes a run of identical dialog-coloured pages."""
        if len(set(page)) != DIALOG_COLOURS:
            self._run = 0
        elif page == self._last:
            self._run += 1
        else:
            self._run = 1
        self._last = page
        return self._run >= SETTLE_PAGES


def char_key(ch: str) -> tuple[int, int]:
    """The `(ascii, scan)` BIOS key word for one character."""
    if len(ch) != 1:
        msg = f"char_key expects one character, got {ch!r}"
        raise ValueError(msg)
    return ord(ch), _SCAN_CODES.get(ch.lower(), 0x00)


def bios_keys(names: Sequence[str]) -> list[tuple[int, int]]:
    """BIOS key words for dosbox-automation key names (`KBD_<c>`, `KBD_down`, `KBD_enter`)."""
    keys: list[tuple[int, int]] = []
    for name in names:
        if name == "KBD_down":
            keys.append(KEY_DOWN)
        elif name == "KBD_enter":
            keys.append(KEY_ENTER)
        elif name.startswith("KBD_") and len(name) == 5:
            keys.append(char_key(name[4]))
        else:
            msg = f"no BIOS key for {name}"
            raise ValueError(msg)
    return keys


def key_writes(head: int, tail: int, keys: Sequence[tuple[int, int]]) -> list[tuple[int, bytes]]:
    """The BDA writes (offset in segment 0x40, bytes) that queue *keys*, then the new tail."""
    writes: list[tuple[int, bytes]] = []
    for ascii_code, scan in keys:
        after = tail + 2 if tail + 2 < BDA_END else BDA_START
        if after == head:
            msg = "the BIOS keyboard buffer is full"
            raise ValueError(msg)
        writes.append((tail, bytes([ascii_code, scan])))
        tail = after
    writes.append((BDA_TAIL, tail.to_bytes(2, "little")))
    return writes


def send_keys(link: Link, keys: Sequence[tuple[int, int]], gap: float = KEY_GAP) -> None:
    """Queue *keys* one at a time, *gap* seconds apart; each SM byte gets a leading 0, since SM
    reads a bare `AF` or `DF` as a flag name (dosbox-x-legacy.md section 2)."""
    for key in keys:
        head = int.from_bytes(link.dump(BDA_SEGMENT, BDA_HEAD, 2), "little")
        tail = int.from_bytes(link.dump(BDA_SEGMENT, BDA_TAIL, 2), "little")
        for off, data in key_writes(head, tail, [key]):
            link.ex(f"SM {BDA_SEGMENT:04X}:{off:04X} " + " ".join(f"0{b:02X}" for b in data))
        time.sleep(gap)


def parse_mcbs(lines: Sequence[str], program: str = "PLAYONE") -> int:
    """The PSP segment of the memory block owned by *program*, from `DOS MCBS`."""
    for line in lines:
        fields = line.split()
        if len(fields) == 4 and fields[3] == program:
            return int(fields[2], 16)
    msg = f"no {program} block in DOS MCBS"
    raise ValueError(msg)


@dataclass
class Booted:
    """PLAYONE at its film dialog with the film selected: the link, load paragraph and stage.

    The last selection key (Enter) is held back until `start`, so probes armed first see the
    film load.
    """

    link: Link
    load: int
    stage: Path
    held: tuple[tuple[int, int], ...] = ()

    def start(self) -> None:
        """Send the held key(s): the film starts loading."""
        send_keys(self.link, self.held)
        self.held = ()


@contextmanager
def booted(film: Path, build: Literal["unpatched", "patched"], *, cycles: int) -> Iterator[Booted]:
    """Stage *film* on *build*, boot PLAYONE in DOSBox-X and select the film, holding back Enter
    (`Booted.start`); clean up on exit."""
    exe = dosbox_x_exe()
    engine = dataroot.data_root() / game_builds.BUILDS_DIR / build
    staged = staging.stage_film(film, engine_root=engine)
    listener: Listener | None = None
    proc: subprocess.Popen[bytes] | None = None
    link: Link | None = None
    try:
        conf = staged.root / "dosbox-x.conf"
        conf.write_text(
            render_conf(TEMPLATE.read_text(encoding="utf-8"), mount=staged.mount, cycles=cycles),
            encoding="utf-8",
            newline="\n",
        )
        dump_dir = staged.root / "dump"
        dump_dir.mkdir()
        listener = Listener()
        proc = subprocess.Popen(  # noqa: S603 - the pinned emulator and our own conf
            [
                str(exe),
                "-conf",
                str(conf),
                "-fastlaunch",
                "-set",
                f"dosbox mcp_server={listener.port}",
            ],
            cwd=staged.root,
        )
        link = Link(listener.accept(ACCEPT_TIMEOUT), dump_dir)
        link.req("PING")
        settle = DialogSettle()
        for _ in range(DIALOG_DUMPS):
            if settle.feed(link.dump(0xA000, 0, 0xFA00)):
                break
            time.sleep(DUMP_GAP)
        else:
            msg = f"PLAYONE's film dialog did not settle within {DIALOG_DUMPS} page dumps"
            raise GuestTimeout(msg)
        load = parse_mcbs(link.ex("DOS MCBS")) + 0x10
        keys = bios_keys(film_selection_names(film.name))
        send_keys(link, keys[:-1])
        yield Booted(link, load, staged.root, tuple(keys[-1:]))
    finally:
        if link is not None:
            with contextlib.suppress(LinkError, OSError):
                link.req("BREAK", timeout=2.0)
            link.close()
        if proc is not None:
            proc.kill()
            proc.wait(timeout=30)
        if listener is not None:
            listener.close()
        staging.unstage(staged)

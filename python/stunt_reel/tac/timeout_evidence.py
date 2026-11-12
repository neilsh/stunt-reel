"""What a timed-out MAKEONE run leaves behind: a picture of the guest screen and the emulators.

A ``make-all`` that passes its timeout kills the guest, and the log alone cannot say whether
MAKEONE hung, waits at a prompt, runs slowly or shares the machine with other emulators
(``research/makeone-exe/driving.md`` item 9). :func:`save` records both before the kill. It never
raises: evidence is best effort and must not change the run's outcome.
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import zlib
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["Evidence", "emulator_processes", "page_png", "save", "screen_script"]

#: Mode 13h: 320 x 200 palette indices at ``A000:0000``.
WIDTH: int = 320
HEIGHT: int = 200
#: Seconds the screen-grab script may take.
_SCRIPT_TIMEOUT: float = 60.0
_EMULATOR = re.compile(r"dosbox", re.IGNORECASE)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: The 16 EGA colours that VGA's default palette starts with.
_EGA = (
    (0, 0, 0),
    (0, 0, 170),
    (0, 170, 0),
    (0, 170, 170),
    (170, 0, 0),
    (170, 0, 170),
    (170, 85, 0),
    (170, 170, 170),
    (85, 85, 85),
    (85, 85, 255),
    (85, 255, 85),
    (85, 255, 255),
    (255, 85, 85),
    (255, 85, 255),
    (255, 255, 85),
    (255, 255, 255),
)


class Evidence(NamedTuple):
    """What :func:`save` kept: the picture's path (None when it failed) and any problems."""

    picture: Path | None
    processes: list[str]
    problems: list[str]


class _Client(Protocol):
    def run_script(self, text: str, *, timeout: float) -> dict[str, Any]: ...


def screen_script() -> str:
    """A Lua script that returns the mode 13h page as ``out.page`` (``x`` and hex)."""
    return (
        "local out = dosbox.output\n"
        "local H = {}\n"
        'for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end\n'
        f'out.page = "x" .. dosbox.mem_read(0xA000, 0, {WIDTH * HEIGHT}):gsub(".", H)\n'
        "out.done = true\n"
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def page_png(page: bytes) -> bytes:
    """An indexed PNG of a 320 x 200 page, coloured by the default VGA palette's first 16 and grey.

    The emulator's DAC is not readable from Lua, so this shows palette *indices*, not the
    colours the guest chose; enough to read a prompt or tell a frozen title from a scene.
    """
    if len(page) != WIDTH * HEIGHT:
        raise ValueError(f"a page is {WIDTH * HEIGHT} bytes, got {len(page)}")
    palette = bytearray(b"".join(bytes(rgb) for rgb in _EGA))
    for index in range(16, 256):
        palette += bytes((index,) * 3)
    rows = b"".join(b"\x00" + page[y * WIDTH : (y + 1) * WIDTH] for y in range(HEIGHT))
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 3, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"PLTE", bytes(palette))
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def emulator_processes() -> list[str]:
    """One ``pid name`` line for every running process whose name contains ``dosbox``."""
    windows = sys.platform == "win32"
    argv = ["tasklist", "/fo", "csv", "/nh"] if windows else ["ps", "-eo", "pid=,comm="]
    text = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
        argv, capture_output=True, text=True, check=True, timeout=30
    ).stdout
    found: list[str] = []
    for line in text.splitlines():
        if not _EMULATOR.search(line):
            continue
        if windows:
            name, pid, *_ = (field.strip('"') for field in line.split('","'))
            found.append(f"{pid} {name}")
        else:
            found.append(" ".join(line.split()))
    return found


def save(
    client: _Client,
    directory: Path,
    stem: str,
    *,
    listing: Callable[[], list[str]] | None = None,
) -> Evidence:
    """Save the guest screen as ``<stem>.png`` in *directory* and list the emulator processes."""
    problems: list[str] = []
    picture: Path | None = None
    try:
        out = client.run_script(screen_script(), timeout=_SCRIPT_TIMEOUT)
        page = bytes.fromhex(str(out["page"])[1:])
        directory.mkdir(parents=True, exist_ok=True)
        picture = directory / f"{stem}.png"
        picture.write_bytes(page_png(page))
    except Exception as exc:  # noqa: BLE001 - evidence must never mask the timeout
        picture = None
        problems.append(f"no screen picture: {exc}")
    processes: list[str] = []
    try:
        processes = (listing or emulator_processes)()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"no process list: {exc}")
    return Evidence(picture, processes, problems)

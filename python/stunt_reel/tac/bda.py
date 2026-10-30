"""BIOS Data Area (BDA) keystroke buffer injection for automated navigation.

Directly manipulates the standard IBM PC BIOS keyboard circular buffer
in segment 0x0040 (head: 0040:001A, tail: 0040:001C, buffer: 0040:001E-0040:003D).

Enables headless navigation through PLAYONE.EXE's modal film selection dialog
(0x0787) without command-line parameter support. Every operation goes through the
transport's memory operations, so a live session and the offline mock share the
ring-buffer arithmetic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "BDA_BUFFER_END",
    "BDA_BUFFER_START",
    "BDA_HEAD_OFFSET",
    "BDA_SEGMENT",
    "BDA_TAIL_OFFSET",
    "KEY_DOWN",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_SPACE",
    "KEY_UP",
    "BdaBuffer",
    "BdaInjector",
    "char_to_key",
]


class BdaBuffer(Protocol):
    """The real-mode memory operations a keystroke injection needs."""

    def read_memory(self, address: tuple[int, int], length: int) -> bytes:
        """Read length bytes at (segment, offset)."""
        ...

    def write_memory(self, address: tuple[int, int], data: bytes) -> None:
        """Write data at (segment, offset)."""
        ...


# BIOS Data Area Memory Offsets
BDA_SEGMENT: int = 0x0040
BDA_HEAD_OFFSET: int = 0x001A
BDA_TAIL_OFFSET: int = 0x001C
BDA_BUFFER_START: int = 0x001E
BDA_BUFFER_END: int = 0x003E  # 32 bytes, 16 16-bit word slots

# Standard Key Codes (ASCII, Scan Code)
KEY_ENTER: tuple[int, int] = (0x0D, 0x1C)  # 0x1C0D
KEY_ESC: tuple[int, int] = (0x1B, 0x01)  # 0x011B
KEY_SPACE: tuple[int, int] = (0x20, 0x39)  # 0x3920
KEY_UP: tuple[int, int] = (0x00, 0x48)  # 0x4800
KEY_DOWN: tuple[int, int] = (0x00, 0x50)  # 0x5000

# Standard PC Scan Codes for Alphanumerics
_SCAN_CODES: dict[str, int] = {
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    ".": 0x34,
    "-": 0x0C,
    "_": 0x0C,
}


def char_to_key(ch: str) -> tuple[int, int]:
    """Map character to 16-bit BIOS keystroke tuple (ascii_code, scan_code)."""
    if len(ch) != 1:
        raise ValueError(f"char_to_key expects single character, got {ch!r}")
    lower = ch.lower()
    scan = _SCAN_CODES.get(lower, 0x00)
    ascii_code = ord(ch)
    return (ascii_code, scan)


class BdaInjector:
    """Writes keystrokes into the conventional-memory BIOS Data Area ring buffer."""

    @staticmethod
    def get_buffer_state(buffer: BdaBuffer) -> tuple[int, int]:
        """Read current BDA head and tail pointer offsets."""
        head = int.from_bytes(buffer.read_memory((BDA_SEGMENT, BDA_HEAD_OFFSET), 2), "little")
        tail = int.from_bytes(buffer.read_memory((BDA_SEGMENT, BDA_TAIL_OFFSET), 2), "little")
        return head, tail

    @classmethod
    def inject_keys(cls, buffer: BdaBuffer, keys: Sequence[tuple[int, int]]) -> None:
        """Inject a sequence of keystrokes (ascii, scan_code) into the BDA ring buffer.

        The whole sequence is capacity-checked before anything is written, so an
        overflowing request leaves the buffer, the head and the tail untouched.
        """
        if not keys:
            return

        head, tail = cls.get_buffer_state(buffer)

        # Normalize out-of-range or unaligned pointers (must be even word offsets in [0x001E, 0x003C])
        if not (BDA_BUFFER_START <= head <= 0x003C) or (head % 2 != 0):
            head = BDA_BUFFER_START
            buffer.write_memory((BDA_SEGMENT, BDA_HEAD_OFFSET), head.to_bytes(2, "little"))
        if not (BDA_BUFFER_START <= tail <= 0x003C) or (tail % 2 != 0):
            tail = BDA_BUFFER_START
            buffer.write_memory((BDA_SEGMENT, BDA_TAIL_OFFSET), tail.to_bytes(2, "little"))

        # Atomic buffer capacity check before writing to memory
        buffer_size = BDA_BUFFER_END - BDA_BUFFER_START  # 32 bytes
        available_slots = ((head - tail - 2) % buffer_size) // 2
        if len(keys) > available_slots:
            raise BufferError(
                f"BDA keyboard buffer overflow: capacity exceeded "
                f"({len(keys)} keys requested, {available_slots} slots available)"
            )

        curr_tail = tail
        for ascii_code, scan_code in keys:
            # Next tail position after writing 2-byte word
            next_tail = curr_tail + 2
            if next_tail >= BDA_BUFFER_END:
                next_tail = BDA_BUFFER_START

            # Write word [ascii, scan_code] at curr_tail
            key_bytes = bytes([ascii_code & 0xFF, scan_code & 0xFF])
            buffer.write_memory((BDA_SEGMENT, curr_tail), key_bytes)
            curr_tail = next_tail

        # Commit new tail pointer
        buffer.write_memory((BDA_SEGMENT, BDA_TAIL_OFFSET), curr_tail.to_bytes(2, "little"))

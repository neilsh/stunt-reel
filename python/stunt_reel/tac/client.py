"""Typed decoding over the TAC operations transport.

The transport seam speaks operations (read_memory, dump_framebuffer, read_palette,
inject_key, step_to_retrace, close); this client is the thin typed reader the
trajectory streamer decodes memory structures with. Capture, probing and trapping
go through the session and the transport operations directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType

    from stunt_reel.tac.transport import Address, Transport

__all__ = ["TacClient"]


class TacClient:
    """Typed, read-only decoding over a transport."""

    def __init__(self, transport: Transport) -> None:
        self.transport: Transport = transport

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the transport connection."""
        self.transport.close()

    @staticmethod
    def _parse_seg_off(seg_off: str) -> Address:
        """Parse a segment:offset string into an integer pair."""
        if ":" not in seg_off:
            raise ValueError(f"Expected <seg>:<off>, got {seg_off!r}")
        seg_s, off_s = seg_off.split(":", 1)
        return int(seg_s, 16), int(off_s, 16)

    def read_memory(self, seg_off: str, length: int = 16) -> bytes:
        """Read arbitrary bytes from real-mode memory at a segment:offset string."""
        if length <= 0:
            return b""
        return self.transport.read_memory(self._parse_seg_off(seg_off), length)

    def read_u8(self, seg_off: str) -> int:
        """Read 8-bit unsigned integer."""
        data = self.read_memory(seg_off, 1)
        if not data:
            raise RuntimeError(f"Failed to read u8 from {seg_off}")
        return data[0]

    def read_u16(self, seg_off: str) -> int:
        """Read 16-bit unsigned little-endian word."""
        data = self.read_memory(seg_off, 2)
        if len(data) < 2:
            raise RuntimeError(f"Failed to read u16 from {seg_off}")
        return int.from_bytes(data, "little")

    def read_i16(self, seg_off: str) -> int:
        """Read 16-bit signed little-endian word."""
        data = self.read_memory(seg_off, 2)
        if len(data) < 2:
            raise RuntimeError(f"Failed to read i16 from {seg_off}")
        return int.from_bytes(data, "little", signed=True)

    def read_u32(self, seg_off: str) -> int:
        """Read 32-bit unsigned little-endian integer."""
        data = self.read_memory(seg_off, 4)
        if len(data) < 4:
            raise RuntimeError(f"Failed to read u32 from {seg_off}")
        return int.from_bytes(data, "little")

    def read_i32(self, seg_off: str) -> int:
        """Read 32-bit signed little-endian integer."""
        data = self.read_memory(seg_off, 4)
        if len(data) < 4:
            raise RuntimeError(f"Failed to read i32 from {seg_off}")
        return int.from_bytes(data, "little", signed=True)

    def read_fixed16_16(self, seg_off: str) -> float:
        """Read 32-bit signed 16.16 fixed-point number as float meters."""
        return float(self.read_i32(seg_off)) / 65536.0

    def read_string(self, seg_off: str, max_len: int = 64) -> str:
        """Read null-terminated or $-terminated ASCII string from memory."""
        data = self.read_memory(seg_off, max_len)
        chars: list[str] = []
        for byte in data:
            if byte in (0, ord("$")):
                break
            chars.append(chr(byte))
        return "".join(chars)

"""High-level client for the DOSBox-X Test Automation and Capture (TAC) harness.

Wraps debugger commands (D, SM, BP, BPDEL, BPIO, RUN, VRT) into strongly typed
memory reading, writing, and execution controls.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from stunt_reel.tac.transport import LiveSocketTransport, Transport

__all__ = ["TacClient"]


class TacClient:
    """Client interface interacting with DOSBox-X debugger via Transport."""

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport: Transport = transport if transport is not None else LiveSocketTransport()

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
        """Close transport connection."""
        self.transport.close()

    def execute(self, cmd: str) -> list[str]:
        """Execute raw debugger command line and return response lines."""
        return self.transport.send_command(cmd)

    def ping(self) -> bool:
        """Send PING command; return True if response is PONG."""
        res = self.execute("PING")
        return any("PONG" in line for line in res)

    def set_breakpoint(self, addr: str) -> None:
        """Set execution breakpoint at specified segment:offset (BP <addr>)."""
        self.execute(f"BP {addr}")

    def set_io_breakpoint(self, port: int | str) -> None:
        """Set I/O breakpoint on VGA or peripheral port (BPIO <port>)."""
        port_str = f"{port:04X}" if isinstance(port, int) else str(port)
        self.execute(f"BPIO {port_str}")

    def delete_breakpoints(self) -> None:
        """Delete all active breakpoints (BPDEL *)."""
        self.execute("BPDEL *")

    def resume(self) -> list[str]:
        """Resume execution until breakpoint or halt (RUN)."""
        return self.execute("RUN")

    def wait_vertical_retrace(self) -> list[str]:
        """Step execution until next vertical blank interval (VRT)."""
        return self.execute("VRT")

    @staticmethod
    def _parse_seg_off(seg_off: str) -> tuple[int, int]:
        """Parse segment:offset string into integer pair."""
        if ":" not in seg_off:
            raise ValueError(f"Expected <seg>:<off>, got {seg_off!r}")
        seg_s, off_s = seg_off.split(":", 1)
        return int(seg_s, 16), int(off_s, 16)

    @staticmethod
    def add_seg_off(seg_off: str, delta: int) -> str:
        """Add integer byte delta to a real-mode segment:offset string."""
        seg, off = TacClient._parse_seg_off(seg_off)
        new_off = (off + delta) & 0xFFFF
        return f"{seg:04X}:{new_off:04X}"

    def read_memory(self, seg_off: str, length: int = 16) -> bytes:
        """Read arbitrary byte slice from real-mode memory using D command."""
        if length <= 0:
            return b""

        lines = self.execute(f"D {seg_off} {length}")
        raw_bytes = bytearray()

        for line in lines:
            line_str = line.strip()
            if not line_str or ":" not in line_str:
                continue
            parts = line_str.split(":", 1)
            rest = parts[1].strip()
            tokens = rest.split()
            if not tokens:
                continue

            # First token is the offset within the line (e.g. "0C60")
            for token in tokens[1:]:
                if token == "-":  # noqa: S105
                    continue
                if len(token) == 2:
                    try:
                        val = int(token, 16)
                        raw_bytes.append(val)
                        if len(raw_bytes) == length:
                            break
                    except ValueError:
                        break
                else:
                    # Non-hex characters indicate ASCII column or formatting
                    break

            if len(raw_bytes) >= length:
                break

        return bytes(raw_bytes[:length])

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
        raw = self.read_i32(seg_off)
        return float(raw) / 65536.0

    def read_string(self, seg_off: str, max_len: int = 64) -> str:
        """Read null-terminated or $-terminated ASCII string from memory."""
        data = self.read_memory(seg_off, max_len)
        chars: list[str] = []
        for b in data:
            if b in (0, ord("$")):
                break
            chars.append(chr(b))
        return "".join(chars)

    def write_memory(self, seg_off: str, data: bytes | bytearray) -> None:
        """Write byte slice into real-mode memory using SM command (chunked in 16B)."""
        seg, off = self._parse_seg_off(seg_off)
        chunk_size = 16

        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            curr_off = off + i
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            self.execute(f"SM {seg:04X}:{curr_off:04X} {hex_str}")

    def write_u16(self, seg_off: str, val: int) -> None:
        """Write 16-bit unsigned little-endian word."""
        self.write_memory(seg_off, (val & 0xFFFF).to_bytes(2, "little"))

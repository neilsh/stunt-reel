"""Transport layer abstractions for DOSBox-X debugger communication.

Supports:
- Transport Protocol: Abstract interface for commands and queries.
- LiveSocketTransport: Line-framed socket client connecting to dosbox-x-mcp-server (TCP 58991).
- ListenTransport: Socket listener accepting DOSBox-X's outbound debugger connection,
  which is how ``[dosbox] mcp_server`` actually connects.
- MockTransport: In-memory virtual 8086 machine for 100% offline CI verification [I7].
"""

from __future__ import annotations

import contextlib
import math
import socket
import struct
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, TextIO, runtime_checkable

__all__ = [
    "ListenTransport",
    "LiveSocketTransport",
    "MockTransport",
    "Transport",
    "format_hex_dump",
]


@runtime_checkable
class Transport(Protocol):
    """Abstract protocol for executing debugger commands against DOSBox-X."""

    def send_command(self, cmd: str) -> list[str]:
        """Send a debugger command and return the framed response lines."""
        ...

    def is_connected(self) -> bool:
        """Check if transport is currently connected and active."""
        ...

    def close(self) -> None:
        """Close connection and clean up resources."""
        ...


class _LineChannel:
    """Line-framed request/response channel over a connected socket.

    Owns a text ``makefile`` view of the socket (UTF-8, undecodable bytes replaced,
    ``\\n`` as the only line terminator) and speaks the dosbox-x-mcp-server framing
    shared by every live transport:

    - request: ``REQ <id> <command>\\n``
    - response: ``BEGIN <id> OK|ERR\\n``, body lines, ``END <id>\\n``

    A ``TimeoutError`` leaves the socket's buffered reader unusable (the stdlib refuses
    further reads after one), so callers must drop the connection when it is raised.
    """

    def __init__(self, sock: socket.socket, closed_message: str) -> None:
        self._sock = sock
        self._closed_message = closed_message
        self._file = self._open()

    def _open(self) -> TextIO:
        return self._sock.makefile("rw", encoding="utf-8", errors="replace", newline="\n")

    def discard_pending(self) -> None:
        """Drop any bytes already buffered, e.g. stale lines after a framing error."""
        with contextlib.suppress(OSError):
            self._file.close()
        self._file = self._open()

    def close(self) -> None:
        """Close the stream and the socket."""
        with contextlib.suppress(OSError):
            self._file.close()
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._sock.close()

    def read_line(self) -> str:
        """Read one newline-terminated line, without its terminator (CR tolerated)."""
        line = self._file.readline()
        if not line.endswith("\n"):
            raise ConnectionResetError(self._closed_message)
        return line[:-1].strip("\r")

    def request(self, req_id: int, wire: str, label: str) -> list[str]:
        """Send one framed request and return its response body lines.

        Raises ``RuntimeError`` for a malformed or mismatched header and for an ``ERR``
        response; ``ConnectionResetError`` if the peer closes mid-response.
        """
        self._file.write(f"REQ {req_id} {wire}\n")
        self._file.flush()

        begin_line = self.read_line()
        tokens = begin_line.strip().split()
        if len(tokens) < 3 or tokens[0] != "BEGIN" or tokens[1] != str(req_id):
            raise RuntimeError(
                f"Unexpected response header: {begin_line!r}, expected BEGIN {req_id} <status>"
            )
        is_ok = tokens[2] == "OK"

        lines: list[str] = []
        end_marker = f"END {req_id}"
        while True:
            line = self.read_line()
            if line == end_marker:
                break
            lines.append(line)

        if not is_ok:
            error_msg = "\n".join(lines) if lines else "Unknown debugger error"
            raise RuntimeError(
                f"DOSBox-X command error for request {req_id} ({label}): {error_msg}"
            )
        return lines


class _FramedTransport:
    """Shared request bookkeeping and error policy for the socket transports."""

    _NOT_CONNECTED = "Socket is not connected"
    _CLOSED = "Socket closed prematurely by remote host"

    def __init__(self) -> None:
        self._channel: _LineChannel | None = None
        self._req_id: int = 1

    def _attach(self, sock: socket.socket) -> None:
        self._channel = _LineChannel(sock, self._CLOSED)

    def _drop_connection(self) -> None:
        """Forget the current connection after it failed."""
        self.close()

    def close(self) -> None:
        """Close the active connection."""
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def is_connected(self) -> bool:
        """Return True while a connection is open."""
        return self._channel is not None

    def _exchange(self, wire: str, label: str) -> list[str]:
        """Run one framed request, dropping or resyncing the stream on failure."""
        channel = self._channel
        if channel is None:
            raise ConnectionError(self._NOT_CONNECTED)

        req_id = self._req_id
        self._req_id += 1
        try:
            return channel.request(req_id, wire, label)
        except (ConnectionError, TimeoutError):
            self._drop_connection()
            raise
        except Exception:
            channel.discard_pending()
            raise


class LiveSocketTransport(_FramedTransport):
    """Live TCP socket transport connecting to dosbox-x-mcp-server wire protocol.

    Wire framing:
    - Outgoing request: `REQ <id> <command>\n`
    - Incoming response:
        `BEGIN <id> OK\n` or `BEGIN <id> ERR\n`
        `<line 1>\n` ...
        `END <id>\n`
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 58991,
        timeout: float = 5.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout

    @property
    def _buffer(self) -> str:
        """Unread text carried between requests; always empty (see ``discard_pending``)."""
        return ""

    def connect(self) -> None:
        """Establish TCP connection to the debugger server."""
        if self._channel is not None:
            self.close()
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._attach(sock)

    def send_command(self, cmd: str) -> list[str]:
        """Send framed REQ command and parse BEGIN ... END response block."""
        if self._channel is None:
            self.connect()
        return self._exchange(cmd.strip(), cmd)


def format_hex_dump(seg: int, off: int, data: bytes) -> list[str]:
    """Render a memory slice as DOSBox-X ``D`` hex-dump lines (16 bytes per row)."""
    lines: list[str] = []
    for offset_step in range(0, len(data), 16):
        chunk = data[offset_step : offset_step + 16]
        curr_off = (off + offset_step) & 0xFFFF
        hex_tokens = [f"{b:02X}" for b in chunk]
        if len(hex_tokens) > 8:
            hex_str = " ".join(hex_tokens[:8]) + " - " + " ".join(hex_tokens[8:])
        else:
            hex_str = " ".join(hex_tokens)
        ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{seg:04X}:{curr_off:04X}  {hex_str:<49}  {ascii_chars}")
    return lines


class ListenTransport(_FramedTransport):
    """Debugger transport that listens for DOSBox-X's outbound debugger connection.

    DOSBox-X configured with ``[dosbox] mcp_server = <port>`` is a TCP *client*: it
    dials the controller that listens on that port. This transport owns the listener,
    accepts the single emulator connection, and speaks the ``REQ <id> <command>`` /
    ``BEGIN <id> OK`` / ``END <id>`` framing.

    Two live-debugger quirks are normalized here so [`TacClient`] reads the same as
    against [`MockTransport`]:
    - Only ``PING`` and ``BREAK`` are bare verbs; every debugger command must be
      sent as ``EXEC <command>``.
    - The live ``D <seg>:<off> <len>`` command only moves the debugger's data view,
      so reads are translated into ``MEMDUMPBIN`` against a host file that this
      transport reads back.
    """

    BARE_VERBS: frozenset[str] = frozenset({"PING", "BREAK"})

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 58991,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout
        self._listener: socket.socket | None = None
        self._read_path: Path = Path(tempfile.gettempdir()) / "stunt_tac_read.bin"

    def listen(self) -> None:
        """Bind the control port and wait for one emulator connection."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(1)
        self._listener = sock

    def accept(self, timeout: float | None = None) -> None:
        """Block until DOSBox-X connects, or raise ``TimeoutError``."""
        if self._listener is None:
            raise RuntimeError("listen() must be called before accept()")
        self._listener.settimeout(self.timeout if timeout is None else timeout)
        conn, _addr = self._listener.accept()
        conn.settimeout(self.timeout)
        self._attach(conn)

    _NOT_CONNECTED = "DOSBox-X has not connected yet"
    _CLOSED = "DOSBox-X closed the debugger socket"

    def _drop_connection(self) -> None:
        """Forget the emulator connection but keep listening for a reconnect."""
        super().close()

    def close(self) -> None:
        """Close the emulator connection and the control port listener."""
        super().close()
        if self._listener is not None:
            with contextlib.suppress(OSError):
                self._listener.close()
            self._listener = None

    def _request(self, wire: str) -> list[str]:
        """Send one framed request and return its response body lines."""
        return self._exchange(wire, wire)

    def _dump_memory(self, args: Sequence[str]) -> list[str]:
        """Translate ``D <seg>:<off> <len>`` into a ``MEMDUMPBIN`` round trip."""
        if not args:
            raise ValueError("D requires a <segment>:<offset> target")
        target = args[0]
        length = int(args[1]) if len(args) > 1 else 16
        if length <= 0:
            return []

        body = self._request(f"EXEC MEMDUMPBIN {target} {length:04X} {self._read_path.as_posix()}")
        try:
            data = self._read_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"MEMDUMPBIN {target} produced no file: {body}") from exc
        if len(data) != length:
            raise RuntimeError(
                f"MEMDUMPBIN {target} wrote {len(data)} bytes, expected {length}: {body}"
            )

        seg_s, off_s = target.split(":", 1)
        return format_hex_dump(int(seg_s, 16), int(off_s, 16), data)

    def send_command(self, cmd: str) -> list[str]:
        """Execute one debugger command against the live emulator."""
        tokens = cmd.strip().split()
        if not tokens:
            return []
        if tokens[0].upper() == "D":
            return self._dump_memory(tokens[1:])
        wire = cmd.strip() if tokens[0].upper() in self.BARE_VERBS else f"EXEC {cmd.strip()}"
        return self._request(wire)


class MockTransport:
    """In-memory virtual x86 machine for 100% offline CI verification."""

    def __init__(self, memory_size: int = 1024 * 1024) -> None:
        self.memory = bytearray(memory_size)
        self.breakpoints: set[str] = set()
        self.io_breakpoints: set[str] = set()
        self.current_tick: int = 0
        self.max_ticks: int = 600
        self.tick_address: tuple[int, int] = (0x1575, 0x4896)
        self.custom_handlers: dict[str, Callable[[list[str]], list[str]]] = {}
        self._closed: bool = False
        self._scenario: list[Any] | None = None
        self._sim_started: bool = False

        # Initialize standard BIOS Data Area (0040:001A head=0x001E, 0040:001C tail=0x001E)
        self.write_u16(0x0040, 0x001A, 0x001E)
        self.write_u16(0x0040, 0x001C, 0x001E)

        # Initialize dynamic actor heap pointer at 0x0D51:0C50 -> 0x0D51:0CA0
        self.write_u16(0x0D51, 0x0C50, 0x0CA0)
        self.write_u16(0x0D51, 0x0C52, 0x0D51)

        # Initialize DGROUP tick counter
        self.set_sim_tick(0)

    def load_trajectory(self, records: Sequence[Any]) -> None:
        """Load precomputed trajectory records to simulate authentic memory on each tick."""
        self._scenario = list(records)
        self.max_ticks = len(self._scenario)
        self._sim_started = False
        self.set_sim_tick(0)

    def _write_tick_state(self, tick: int) -> None:
        """Write camera and actor binary structures for current tick into virtual RAM."""
        if not self._scenario or tick >= len(self._scenario):
            return

        rec = self._scenario[tick]

        # 1. Write [MEM-CAMERA-RIG] (32 bytes at 0x0D51:0C10)
        cam = rec.camera
        eye_raw = [round(x * 65536.0) for x in cam.eye]
        tgt_raw = [round(x * 65536.0) for x in cam.target]
        focal_u16 = (
            round(120.0 / math.tan(math.radians(cam.fov_degrees / 2.0)))
            if cam.fov_degrees > 0
            else 290
        )
        roll_bam = round((cam.roll_radians / (2.0 * math.pi)) * 65536.0) & 0xFFFF
        mode_id = 2 if cam.cut_from_previous else 1
        cam_bytes = struct.pack(
            "<6iHHHH",
            eye_raw[0],
            eye_raw[1],
            eye_raw[2],
            tgt_raw[0],
            tgt_raw[1],
            tgt_raw[2],
            focal_u16,
            roll_bam,
            mode_id,
            0,
        )
        self.write_bytes(0x0D51, 0x0C10, cam_bytes)

        # 2. Write [MEM-ACTOR-TABLE] far pointer at 0x0D51:0C50 -> 0x0D51:0CA0
        self.write_u16(0x0D51, 0x0C50, 0x0CA0)
        self.write_u16(0x0D51, 0x0C52, 0x0D51)

        # 3. Write [MEM-ACTOR-TABLE] entries (64 bytes each, chained from 0x0D51:0CA0)
        if rec.actors:
            base_offset = 0x0CA0
            stride = 64
            for idx, act in enumerate(rec.actors):
                pos_raw = [round(x * 65536.0) for x in act.position_meters]
                name_bytes = act.model_name.encode("ascii")[:8].ljust(8, b"\x00")
                qx, qy, qz, qw = act.rotation_quat
                joint_count = len(act.joint_angles_bam)
                act_header = struct.pack(
                    "<I8s3i4fHH",
                    act.actor_id,
                    name_bytes,
                    pos_raw[0],
                    pos_raw[1],
                    pos_raw[2],
                    qx,
                    qy,
                    qz,
                    qw,
                    act.state_mask,
                    joint_count,
                )
                joints_buf = bytearray(16)
                for j_idx, (sub_id, bam_val) in enumerate(act.joint_angles_bam[:4]):
                    struct.pack_into("<HH", joints_buf, j_idx * 4, sub_id, bam_val)

                has_next = (idx + 1) < len(rec.actors)
                next_off = (base_offset + (idx + 1) * stride) if has_next else 0
                next_seg = 0x0D51 if has_next else 0
                next_ptr = struct.pack("<HH", next_off, next_seg)

                act_bytes = act_header + joints_buf + next_ptr
                self.write_bytes(0x0D51, base_offset + idx * stride, act_bytes)

    @staticmethod
    def linear_address(seg: int, off: int) -> int:
        """Convert real-mode segment:offset to 20-bit linear address."""
        return ((seg & 0xFFFF) << 4) + (off & 0xFFFF)

    def write_bytes(self, seg: int, off: int, data: bytes | bytearray) -> None:
        """Write raw byte slice into virtual memory."""
        addr = self.linear_address(seg, off)
        self.memory[addr : addr + len(data)] = data

    def read_bytes(self, seg: int, off: int, length: int) -> bytes:
        """Read raw byte slice from virtual memory."""
        addr = self.linear_address(seg, off)
        return bytes(self.memory[addr : addr + length])

    def write_u16(self, seg: int, off: int, val: int) -> None:
        """Write 16-bit little-endian word."""
        self.write_bytes(seg, off, (val & 0xFFFF).to_bytes(2, "little"))

    def read_u16(self, seg: int, off: int) -> int:
        """Read 16-bit little-endian word."""
        return int.from_bytes(self.read_bytes(seg, off, 2), "little")

    def set_sim_tick(self, tick: int) -> None:
        """Set simulation tick counter in memory and write binary state structures."""
        self.current_tick = tick
        seg, off = self.tick_address
        self.write_u16(seg, off, tick)
        self._write_tick_state(tick)

    def register_handler(self, verb: str, handler: Callable[[list[str]], list[str]]) -> None:
        """Register custom debugger command handler."""
        self.custom_handlers[verb.upper()] = handler

    def is_connected(self) -> bool:
        """Return True if mock transport is active."""
        return not self._closed

    def close(self) -> None:
        """Close mock transport."""
        self._closed = True

    def _parse_seg_off(self, target: str) -> tuple[int, int]:
        """Parse segment:offset string e.g. '1575:4896' or '0040:001A'."""
        if ":" not in target:
            raise ValueError(f"Invalid segment:offset specification: {target}")
        seg_s, off_s = target.split(":", 1)
        return int(seg_s, 16), int(off_s, 16)

    def send_command(self, cmd: str) -> list[str]:
        """Execute mock debugger command against virtual RAM and return output lines."""
        if self._closed:
            raise ConnectionError("MockTransport is closed")

        tokens = cmd.strip().split()
        if not tokens:
            return ["OK"]

        verb = tokens[0].upper()

        if verb in self.custom_handlers:
            return self.custom_handlers[verb](tokens[1:])

        if verb == "PING":
            return ["PONG"]

        if verb == "BP":
            if len(tokens) > 1:
                self.breakpoints.add(tokens[1].upper())
                return [f"Breakpoint set at {tokens[1]}"]
            return ["Missing breakpoint address"]

        if verb == "BPIO":
            if len(tokens) > 1:
                self.io_breakpoints.add(tokens[1].upper())
                return [f"IO Breakpoint set for port {tokens[1]}"]
            return ["Missing port"]

        if verb in ("BPDEL", "BPC"):
            if len(tokens) > 1 and tokens[1] != "*":
                self.breakpoints.discard(tokens[1].upper())
            else:
                self.breakpoints.clear()
                self.io_breakpoints.clear()
            return ["Breakpoints deleted"]

        if verb == "BPLIST":
            return [f"BP {bp}" for bp in sorted(self.breakpoints)]

        if verb == "RUN":
            if self._scenario is not None and not self._sim_started:
                self._sim_started = True
                self.set_sim_tick(0)
            elif self.current_tick < self.max_ticks:
                self.set_sim_tick(self.current_tick + 1)
            return ["Running... Breakpoint hit at post_vsync"]

        if verb == "VRT":
            if self._scenario is not None and not self._sim_started:
                self._sim_started = True
                self.set_sim_tick(0)
            elif self.current_tick < self.max_ticks:
                self.set_sim_tick(self.current_tick + 1)
            return ["Vertical retrace reached"]

        if verb == "SM":
            # SM <seg>:<off> <hex_bytes...>
            if len(tokens) < 3:
                return ["Usage: SM <seg>:<off> <hex>"]
            seg, off = self._parse_seg_off(tokens[1])
            data = bytes.fromhex("".join(tokens[2:]))
            self.write_bytes(seg, off, data)
            return ["OK"]

        if verb == "D":
            # D <seg>:<off> [length]
            if len(tokens) < 2:
                return ["Usage: D <seg>:<off> [len]"]
            seg, off = self._parse_seg_off(tokens[1])
            length = (
                int(tokens[2], 16)
                if len(tokens) > 2 and tokens[2].startswith("0x")
                else (int(tokens[2]) if len(tokens) > 2 else 128)
            )
            return self._format_dump(seg, off, length)

        return ["OK"]

    def _format_dump(self, seg: int, off: int, length: int) -> list[str]:
        """Format memory slice matching standard DOSBox-X D command hex dump."""
        start_addr = self.linear_address(seg, off)
        return format_hex_dump(seg, off, bytes(self.memory[start_addr : start_addr + length]))

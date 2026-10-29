"""Transport layer: the operation-altitude seam to DOSBox-X.

The transport speaks operations rather than debugger text:

- read_memory(address, length)       read real-mode bytes
- write_memory(address, data)       write real-mode bytes (used by BDA injection)
- dump_framebuffer()                dump page 0 of the Mode 13h framebuffer
- read_palette()                    read the live DAC palette, with its provenance
- inject_key(key)                   queue one BIOS Data Area keystroke
- step_to_retrace()                 arm the post-retrace trap, then stop at its next hit
- close()                           drop the connection and release the control port

Implementations:

- LiveSocketTransport: line-framed socket client dialing a debugger control server at
  the host and port its caller supplies.
- ListenTransport: socket listener accepting DOSBox-X's outbound debugger connection,
  which is how [dosbox] mcp_server actually connects. It binds port 0 by default, so the
  OS gives every session its own control port (ADR 0021).
- MockTransport: in-memory virtual 8086 machine for 100% offline CI verification [I7].
"""

from __future__ import annotations

import contextlib
import itertools
import math
import os
import re
import socket
import struct
import tempfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol, TextIO, runtime_checkable

from stunt_reel.tac.bda import BdaInjector
from stunt_reel.tac.models import TrajectoryRecord
from stunt_reel.tac.palette import MODE_13H_PALETTE
from stunt_reel.tac.playone import VBLANK_TRAP

__all__ = [
    "FRAME_BYTES",
    "PAGE_OFFSET",
    "PALETTE_ENTRIES",
    "RGB",
    "Address",
    "Key",
    "ListenTransport",
    "LiveSocketTransport",
    "MockTransport",
    "Transport",
]

#: A colour as an 8-bit RGB triple.
RGB = tuple[int, int, int]
#: A BIOS keystroke: (ASCII code, scan code).
Key = tuple[int, int]
#: A real-mode segmented address: (segment, offset).
Address = tuple[int, int]

#: Mode 13h page size in bytes (320x200, one byte per pixel).
FRAME_BYTES: int = 320 * 200
#: Byte offset of the page PLAYONE.EXE scans out during playback.
PAGE_OFFSET: int = 0
#: Number of VGA DAC entries.
PALETTE_ENTRIES: int = 256
#: Real-mode segment of the VGA linear framebuffer window.
_VGA_SEGMENT: int = 0xA000

#: Dump-file names are per listener, so two listeners in one process cannot share one.
_DUMP_IDS: Iterator[int] = itertools.count(1)

_DAC_ENTRY_RE = re.compile(r"[0-9A-Fa-f]{6}")


@runtime_checkable
class Transport(Protocol):
    """The operations a capture session and the trajectory streamer need."""

    def read_memory(self, address: Address, length: int) -> bytes:
        """Read length bytes from a real-mode segment:offset address."""
        ...

    def dump_framebuffer(self) -> bytes:
        """Dump the 64,000-byte Mode 13h page at offset 0."""
        ...

    def read_palette(self) -> tuple[list[RGB], str]:
        """Read the live DAC palette and its provenance (dacpal or fallback)."""
        ...

    def inject_key(self, key: Key) -> None:
        """Queue one keystroke in the BIOS Data Area ring buffer."""
        ...

    def step_to_retrace(self) -> None:
        """Arm the post-retrace trap on the first call, then stop at its next hit."""
        ...

    def close(self) -> None:
        """Close the connection and release any resources held by the transport."""
        ...


def _decode_hex_dump(lines: Sequence[str], length: int) -> bytes:
    """Decode DOSBox-X D hex-dump lines into raw bytes, stopping at length."""
    raw = bytearray()
    for line in lines:
        line_str = line.strip()
        if not line_str or ":" not in line_str:
            continue
        rest = line_str.split(":", 1)[1].strip()
        tokens = rest.split()
        if not tokens:
            continue
        # First token is the offset within the line (e.g. "0C60").
        for token in tokens[1:]:
            if token == "-":  # noqa: S105 - the dump's half-row separator
                continue
            if len(token) != 2:
                # Non-hex characters indicate the ASCII column or formatting.
                break
            try:
                raw.append(int(token, 16))
            except ValueError:
                break
            if len(raw) == length:
                return bytes(raw)
        if len(raw) >= length:
            break
    return bytes(raw[:length])


def _scale_6bit(value: int) -> int:
    """Scale a 6-bit VGA DAC channel (0..=63) to the 8-bit range (0..=255)."""
    return (value * 255 + 31) // 63


def parse_dac_palette(lines: Sequence[str]) -> tuple[list[RGB], str]:
    """Parse VGA DACPAL lines into 8-bit RGB triples, with fallback provenance.

    DAC registers are 6 bits per channel and are scaled to 0..=255 so reference
    pixels are comparable to rendered palette-index pixels. The SDK table is the
    documented fallback when the emulator does not report a palette.
    """
    palette: list[RGB] = []
    for line in lines:
        if ":" not in line:
            continue
        for entry in _DAC_ENTRY_RE.findall(line.split(":", 1)[1]):
            palette.append(
                (
                    _scale_6bit(int(entry[0:2], 16)),
                    _scale_6bit(int(entry[2:4], 16)),
                    _scale_6bit(int(entry[4:6], 16)),
                )
            )
        if len(palette) >= PALETTE_ENTRIES:
            break

    if len(palette) == PALETTE_ENTRIES:
        return palette, "dacpal"

    fallback = [MODE_13H_PALETTE[i] for i in range(PALETTE_ENTRIES)]
    return [(int(r), int(g), int(b)) for r, g, b in fallback], "fallback"


class _LineChannel:
    """Line-framed request/response channel over a connected socket.

    Owns a text makefile view of the socket (UTF-8, undecodable bytes replaced,
    \\n as the only line terminator) and speaks the dosbox-x-mcp-server framing
    shared by every live transport:

    - request: REQ <id> <command>\\n
    - response: BEGIN <id> OK|ERR\\n, body lines, END <id>\\n

    A TimeoutError leaves the socket's buffered reader unusable (the stdlib refuses
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

        Raises RuntimeError for a malformed or mismatched header and for an ERR
        response; ConnectionResetError if the peer closes mid-response.
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
    """Shared operations, framing bookkeeping and error policy for the live transports."""

    _NOT_CONNECTED = "Socket is not connected"
    _CLOSED = "Socket closed prematurely by remote host"

    def __init__(self) -> None:
        self._channel: _LineChannel | None = None
        self._req_id: int = 1
        self._trap_armed: bool = False

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

    def _wire(self, command: str) -> str:
        """Wire form of one debugger command; the listener overrides with EXEC."""
        return command

    def request(self, command: str) -> list[str]:
        """Send one debugger command through the framed line channel.

        This is the packet-level channel the operations are built on; tests drive
        it directly to pin BEGIN/END framing without depending on a guest verb.
        """
        return self._exchange(self._wire(command), command)

    def read_memory(self, address: Address, length: int) -> bytes:
        """Read real-mode memory through the debugger's D hex dump."""
        if length <= 0:
            return b""
        segment, offset = address
        lines = self.request(f"D {segment:04X}:{offset:04X} {length}")
        return _decode_hex_dump(lines, length)

    def write_memory(self, address: Address, data: bytes) -> None:
        """Write real-mode memory through SM, in 16-byte debugger-sized chunks."""
        segment, offset = address
        for start in range(0, len(data), 16):
            chunk = data[start : start + 16]
            chunk_offset = (offset + start) & 0xFFFF
            hexes = " ".join(f"{byte:02X}" for byte in chunk)
            self.request(f"SM {segment:04X}:{chunk_offset:04X} {hexes}")

    def dump_framebuffer(self) -> bytes:
        """Dump page 0 of the Mode 13h framebuffer."""
        return self.read_memory((_VGA_SEGMENT, PAGE_OFFSET), FRAME_BYTES)

    def read_palette(self) -> tuple[list[RGB], str]:
        """Read the live DAC palette and its provenance."""
        return parse_dac_palette(self.request("VGA DACPAL"))

    def inject_key(self, key: Key) -> None:
        """Queue one keystroke in the BIOS Data Area ring buffer."""
        BdaInjector.inject_keys(self, [key])

    def step_to_retrace(self) -> None:
        """Arm the post-retrace trap on the first call, then run to its next hit."""
        if not self._trap_armed:
            self.request(f"BP {VBLANK_TRAP}")
            self._trap_armed = True
        self.request("RUN")


class LiveSocketTransport(_FramedTransport):
    """Live TCP socket transport connecting to the dosbox-x-mcp-server wire protocol.

    Wire framing:
    - Outgoing request: REQ <id> <command>\\n
    - Incoming response: BEGIN <id> OK|ERR, body lines, END <id>
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        *,
        port: int,
        timeout: float = 5.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout

    def connect(self) -> None:
        """Establish TCP connection to the debugger server."""
        if self._channel is not None:
            self.close()
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._attach(sock)


class ListenTransport(_FramedTransport):
    """Debugger transport that listens for DOSBox-X's outbound debugger connection.

    DOSBox-X configured with [dosbox] mcp_server = <port> is a TCP client: it
    dials the controller that listens on that port. This transport owns the listener,
    accepts the single emulator connection, and speaks the REQ <id> <command> /
    BEGIN <id> OK / END <id> framing.

    The port defaults to 0, so the OS assigns one per session and `listen()`
    returns what it gave: the launch passes that back to DOSBox-X, which is what lets
    two captures coexist (ADR 0021). A caller may still pin a port.

    Two live-debugger quirks are normalized here so the operations read the same as
    against MockTransport:
    - Only PING and BREAK are bare verbs; every debugger command must be sent as
      EXEC <command>.
    - A live D command only moves the debugger's data view, so reads use
      MEMDUMPBIN against a host file that this transport reads back.
    """

    BARE_VERBS: frozenset[str] = frozenset({"PING", "BREAK"})

    _NOT_CONNECTED = "DOSBox-X has not connected yet"
    _CLOSED = "DOSBox-X closed the debugger socket"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout
        self._listener: socket.socket | None = None
        # Per-listener: a process-wide name let two sessions overwrite each other's dump.
        self._read_path: Path = (
            Path(tempfile.gettempdir()) / f"stunt_tac_read_{os.getpid()}_{next(_DUMP_IDS)}.bin"
        )

    def listen(self) -> int:
        """Bind the control port and return the port DOSBox-X must dial."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Exclusive use stops another process from sharing the number the OS just gave
        # us: on Windows SO_REUSEADDR would let a second socket bind the same port.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError:
            sock.close()
            raise
        sock.listen(1)
        self._listener = sock
        port: int = sock.getsockname()[1]
        return port

    def accept(self, timeout: float | None = None) -> None:
        """Block until DOSBox-X connects, or raise TimeoutError."""
        if self._listener is None:
            raise RuntimeError("listen() must be called before accept()")
        self._listener.settimeout(self.timeout if timeout is None else timeout)
        conn, _addr = self._listener.accept()
        conn.settimeout(self.timeout)
        # Abort on close rather than leave TIME_WAIT on the port: under
        # SO_EXCLUSIVEADDRUSE it would refuse the next capture's bind for minutes.
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self._attach(conn)

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
        with contextlib.suppress(OSError):
            self._read_path.unlink(missing_ok=True)

    def _wire(self, command: str) -> str:
        """Wrap debugger commands in EXEC; PING and BREAK are the only bare verbs."""
        tokens = command.split()
        if tokens and tokens[0].upper() in self.BARE_VERBS:
            return command
        return f"EXEC {command}"

    def read_memory(self, address: Address, length: int) -> bytes:
        """Read real-mode memory through MEMDUMPBIN and this listener's host file."""
        if length <= 0:
            return b""
        segment, offset = address
        target = f"{segment:04X}:{offset:04X}"
        body = self.request(f"MEMDUMPBIN {target} {length:04X} {self._read_path.as_posix()}")
        try:
            data = self._read_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"MEMDUMPBIN {target} produced no file: {body}") from exc
        finally:
            # A low-integrity process may not reach the user temp dir, so the file
            # can land in the checkout; never leave a read-back dump behind.
            self._read_path.unlink(missing_ok=True)
        if len(data) != length:
            raise RuntimeError(
                f"MEMDUMPBIN {target} wrote {len(data)} bytes, expected {length}: {body}"
            )
        return data


class MockTransport:
    """In-memory virtual x86 machine for 100% offline CI verification.

    The guest is programmable: set framebuffer bytes, a palette, or the
    dump_source / retrace_source hooks to model a boot sequence or a film.
    """

    def __init__(self, memory_size: int = 1024 * 1024) -> None:
        self.memory = bytearray(memory_size)
        self.current_tick: int = 0
        self.max_ticks: int = 600
        self.tick_address: Address = (0x1575, 0x4896)
        self._closed: bool = False
        self._scenario: list[TrajectoryRecord] | None = None
        self._sim_started: bool = False
        self._trap_armed: bool = False

        #: Page served by dump_framebuffer() unless dump_source is set.
        self.framebuffer: bytearray = bytearray(FRAME_BYTES)
        #: Palette served by read_palette(); None means the SDK fallback table.
        self.palette: tuple[list[RGB], str] | None = None
        #: Optional hook returning one framebuffer page per dump.
        self.dump_source: Callable[[], bytes] | None = None
        #: Optional hook advancing the guest once per step_to_retrace() call.
        self.retrace_source: Callable[[], None] | None = None

        # Initialize standard BIOS Data Area (0040:001A head=0x001E, 0040:001C tail=0x001E)
        self.write_u16(0x0040, 0x001A, 0x001E)
        self.write_u16(0x0040, 0x001C, 0x001E)

        # Initialize dynamic actor heap pointer at 0x0D51:0C50 -> 0x0D51:0CA0
        self.write_u16(0x0D51, 0x0C50, 0x0CA0)
        self.write_u16(0x0D51, 0x0C52, 0x0D51)

        # Initialize DGROUP tick counter
        self.set_sim_tick(0)

    def load_trajectory(self, records: Sequence[TrajectoryRecord]) -> None:
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

    def _require_open(self) -> None:
        if self._closed:
            raise ConnectionError("MockTransport is closed")

    def is_connected(self) -> bool:
        """Return True if mock transport is active."""
        return not self._closed

    def close(self) -> None:
        """Close mock transport."""
        self._closed = True

    # ------------------------------------------------------------------
    # Transport operations
    # ------------------------------------------------------------------

    def read_memory(self, address: Address, length: int) -> bytes:
        """Read raw bytes from virtual memory."""
        self._require_open()
        if length <= 0:
            return b""
        segment, offset = address
        return self.read_bytes(segment, offset, length)

    def write_memory(self, address: Address, data: bytes) -> None:
        """Write raw bytes into virtual memory."""
        self._require_open()
        segment, offset = address
        self.write_bytes(segment, offset, data)

    def dump_framebuffer(self) -> bytes:
        """Serve one framebuffer page from dump_source or the current page bytes."""
        self._require_open()
        source = self.dump_source
        if source is not None:
            return source()
        return bytes(self.framebuffer)

    def read_palette(self) -> tuple[list[RGB], str]:
        """Serve the configured palette, or the SDK fallback table."""
        self._require_open()
        if self.palette is not None:
            return self.palette
        fallback = [MODE_13H_PALETTE[i] for i in range(PALETTE_ENTRIES)]
        return [(int(r), int(g), int(b)) for r, g, b in fallback], "fallback"

    def inject_key(self, key: Key) -> None:
        """Queue one keystroke in the simulated BIOS Data Area ring buffer."""
        self._require_open()
        BdaInjector.inject_keys(self, [key])

    def step_to_retrace(self) -> None:
        """Advance the simulated guest to its next post-retrace trap hit."""
        self._require_open()
        self._trap_armed = True
        step = self.retrace_source
        if step is not None:
            step()
            return
        if self._scenario is not None and not self._sim_started:
            self._sim_started = True
            self.set_sim_tick(0)
        elif self.current_tick < self.max_ticks:
            self.set_sim_tick(self.current_tick + 1)

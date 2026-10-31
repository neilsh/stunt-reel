"""Transport layer: the operation-altitude seam to a guest's memory, palette and keys.

The live backends (a DOSBox-X debugger socket) are retired; the mock stays as the offline
virtual machine behind the reference trajectory model ([`streamer`](streamer.py)).

The transport speaks operations rather than debugger text:

- read_memory(address, length)       read real-mode bytes
- write_memory(address, data)       write real-mode bytes (used by BDA injection)
- dump_framebuffer()                dump page 0 of the Mode 13h framebuffer
- read_palette()                    read the live DAC palette, with its provenance
- inject_key(key)                   queue one BIOS Data Area keystroke
- step_to_retrace()                 arm the post-retrace trap, then stop at its next hit
- close()                           drop the connection and release the control port

Implementation:

- MockTransport: in-memory virtual 8086 machine for 100% offline CI verification [I7].
"""

from __future__ import annotations

import math
import re
import struct
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from stunt_reel.tac.bda import BdaInjector
from stunt_reel.tac.palette import MODE_13H_PALETTE
from stunt_reel.tac.playone import DGROUP_RUNTIME_SEG, FILM_CLOCK_OFFSET

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stunt_reel.tac.models import TrajectoryRecord

__all__ = [
    "FRAME_BYTES",
    "PAGE_OFFSET",
    "PALETTE_ENTRIES",
    "RGB",
    "Address",
    "Key",
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

#: Dump-file names are per listener, so two listeners in one process cannot share one.

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

    def video_mode(self) -> str:
        """The VGA mode name the emulator reports, for example ``M_VGA`` or ``M_TEXT``."""
        ...

    def close(self) -> None:
        """Close the connection and release any resources held by the transport."""
        ...


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
        palette.extend(
            (
                _scale_6bit(int(entry[0:2], 16)),
                _scale_6bit(int(entry[2:4], 16)),
                _scale_6bit(int(entry[4:6], 16)),
            )
            for entry in _DAC_ENTRY_RE.findall(line.split(":", 1)[1])
        )
        if len(palette) >= PALETTE_ENTRIES:
            break

    if len(palette) == PALETTE_ENTRIES:
        return palette, "dacpal"

    fallback = [MODE_13H_PALETTE[i] for i in range(PALETTE_ENTRIES)]
    return [(int(r), int(g), int(b)) for r, g, b in fallback], "fallback"


class MockTransport:
    """In-memory virtual x86 machine for 100% offline CI verification.

    The guest is programmable: set framebuffer bytes, a palette, or the
    dump_source / retrace_source hooks to model a boot sequence or a film.
    """

    def __init__(self, memory_size: int = 1024 * 1024) -> None:
        self.memory = bytearray(memory_size)
        self.current_tick: int = 0
        self.max_ticks: int = 600
        self.tick_address: Address = (DGROUP_RUNTIME_SEG, FILM_CLOCK_OFFSET)
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
        #: Mode served by video_mode() unless video_mode_source is set.
        self.video_mode_name: str = "M_VGA"
        #: Optional hook returning the mode name per video_mode() call.
        self.video_mode_source: Callable[[], str] | None = None

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

    def video_mode(self) -> str:
        """Serve the configured mode name, from video_mode_source when it is set."""
        self._require_open()
        source = self.video_mode_source
        return source() if source is not None else self.video_mode_name

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

"""VGA port 0x03DA vertical retrace trap and simulation tick deduplication.

Synchronizes capture with VGA vertical blanking while downsampling 70 Hz CRT
presentation frames to the 50 Hz simulation clock per Invariant [I4]. The trap is
the transport's post-retrace stop: step_to_retrace arms it on the first call and
stops at each later hit.
"""

from __future__ import annotations

from stunt_reel.tac.playone import DGROUP_RUNTIME_SEG, FILM_CLOCK_OFFSET
from stunt_reel.tac.transport import Address, Transport

__all__ = [
    "DEFAULT_TICK_ADDRESS",
    "PORT_VGA_STATUS",
    "VGA_REFRESH_HZ",
    "VsyncTrap",
]

PORT_VGA_STATUS: int = 0x03DA
VGA_REFRESH_HZ: float = 70.087
#: Active film clock (# [MEM-FLM-TICK]) at the runtime DGROUP segment. The historic
#: 0D51:0C60 label is retired: no code references it and it always read 0.
DEFAULT_TICK_ADDRESS: Address = (DGROUP_RUNTIME_SEG, FILM_CLOCK_OFFSET)


class VsyncTrap:
    """Hardware V-Sync synchronization and tick deduplicator.

    Traps vertical blanking loops and gates snapshot extraction on strictly
    monotonic increments of PLAYONE.EXE's [MEM-FLM-TICK] counter.
    """

    def __init__(
        self,
        tick_address: Address = DEFAULT_TICK_ADDRESS,
        max_spins_per_tick: int = 50,
    ) -> None:
        self.tick_address = tick_address
        self.max_spins_per_tick = max_spins_per_tick

        self.last_captured_tick: int = -1
        self.captured_frames: int = 0
        self.duplicate_frames_dropped: int = 0

    def reset(self) -> None:
        """Reset internal capture counters and tick state."""
        self.last_captured_tick = -1
        self.captured_frames = 0
        self.duplicate_frames_dropped = 0

    def wait_next_sim_tick(self, transport: Transport) -> int:
        """Advance emulation until a strictly new simulation tick is observed.

        Discards duplicate 70 Hz raster frames where [MEM-FLM-TICK] has not incremented.
        Returns the new 16-bit simulation tick index.
        """
        for _ in range(self.max_spins_per_tick):
            transport.step_to_retrace()
            data = transport.read_memory(self.tick_address, 2)
            if len(data) < 2:
                raise RuntimeError(f"Failed to read u16 from {self.tick_address}")
            current_tick = int.from_bytes(data, "little")

            if current_tick > self.last_captured_tick:
                self.last_captured_tick = current_tick
                self.captured_frames += 1
                return current_tick

            self.duplicate_frames_dropped += 1

        raise TimeoutError(
            f"Timed out waiting for simulation tick to advance beyond {self.last_captured_tick} "
            f"after {self.max_spins_per_tick} V-Sync hits"
        )

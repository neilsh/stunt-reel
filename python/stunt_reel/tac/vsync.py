"""VGA Port 0x03DA vertical retrace trap and simulation tick deduplication.

Synchronizes capture with VGA vertical blanking while downsampling 70 Hz CRT
presentation frames to the 50 Hz simulation clock per Invariant [I4].
"""

from __future__ import annotations

from stunt_reel.tac.client import TacClient

__all__ = [
    "DEFAULT_POST_RETRACE_BP",
    "DEFAULT_TICK_ADDR",
    "PORT_VGA_STATUS",
    "VGA_REFRESH_HZ",
    "VsyncTrap",
]

PORT_VGA_STATUS: int = 0x03DA
VGA_REFRESH_HZ: float = 70.087
DEFAULT_POST_RETRACE_BP: str = "0D51:0C5E"
DEFAULT_TICK_ADDR: str = "0D51:0C60"


class VsyncTrap:
    """Hardware V-Sync synchronization and tick deduplicator.

    Traps vertical blanking loops on port 0x03DA and gates snapshot extraction
    on strictly monotonic increments of PLAYONE.EXE's [MEM-FLM-TICK] counter.
    """

    def __init__(
        self,
        post_retrace_bp: str = DEFAULT_POST_RETRACE_BP,
        tick_addr: str = DEFAULT_TICK_ADDR,
        max_spins_per_tick: int = 50,
    ) -> None:
        self.post_retrace_bp = post_retrace_bp
        self.tick_addr = tick_addr
        self.max_spins_per_tick = max_spins_per_tick

        self.last_captured_tick: int = -1
        self.captured_frames: int = 0
        self.duplicate_frames_dropped: int = 0

    def reset(self) -> None:
        """Reset internal capture counters and tick state."""
        self.last_captured_tick = -1
        self.captured_frames = 0
        self.duplicate_frames_dropped = 0

    def arm(self, client: TacClient) -> None:
        """Set post-retrace execution breakpoint."""
        client.set_breakpoint(self.post_retrace_bp)

    def disarm(self, client: TacClient) -> None:
        """Clear active breakpoints."""
        client.delete_breakpoints()

    def wait_next_sim_tick(self, client: TacClient) -> int:
        """Advance emulation until a strictly new simulation tick is observed.

        Discards duplicate 70 Hz raster frames where [MEM-FLM-TICK] has not incremented.
        Returns the new 16-bit simulation tick index.
        """
        for _ in range(self.max_spins_per_tick):
            client.resume()
            current_tick = client.read_u16(self.tick_addr)

            if current_tick > self.last_captured_tick:
                self.last_captured_tick = current_tick
                self.captured_frames += 1
                return current_tick

            self.duplicate_frames_dropped += 1

        raise TimeoutError(
            f"Timed out waiting for simulation tick to advance beyond {self.last_captured_tick} "
            f"after {self.max_spins_per_tick} V-Sync hits"
        )

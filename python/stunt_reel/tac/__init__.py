"""Test Automation and Capture (TAC) harness for Stunt Reel.

Provides dual-mode DOSBox-X automation: one capture session behind an injectable
emulator seam, operation-altitude transports, BIOS Data Area input injection,
hardware V-Sync synchronization, and trajectory streaming for Stunt Island.
"""

from typing import Final

from stunt_reel.tac.bda import (
    KEY_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_SPACE,
    KEY_UP,
    BdaInjector,
    char_to_key,
)
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.emulator import (
    DosboxX,
    Emulator,
    EmulatorUnavailable,
    GuestTimeout,
    Launching,
    MockEmulator,
    PortTaken,
    WaitingForGuest,
)
from stunt_reel.tac.framebuffer import capture
from stunt_reel.tac.models import (
    ActorTransform,
    AudioCue,
    CameraTransform,
    FilmCapture,
    SceneHeader,
    StaticPropPlacement,
    TrajectoryRecord,
    load_trajectory_records,
    save_trajectory_records,
)
from stunt_reel.tac.session import (
    DialogSettled,
    DialogUnsettled,
    Page,
    Session,
    SessionError,
    SessionEvent,
    SessionLost,
    ShortDump,
    StalePage,
    TrapTimeout,
    run_session,
)
from stunt_reel.tac.streamer import (
    DEFAULT_ORACLE_PATH,
    TrajectoryStreamer,
    compute_position_rmse,
    generate_intro_trajectory,
)
from stunt_reel.tac.transport import (
    FRAME_BYTES,
    RGB,
    Address,
    Key,
    ListenTransport,
    LiveSocketTransport,
    MockTransport,
    Transport,
)
from stunt_reel.tac.vsync import (
    PORT_VGA_STATUS,
    VGA_REFRESH_HZ,
    VsyncTrap,
)

TAC_VERSION: Final[str] = "0.1.0"

__all__ = [
    "DEFAULT_ORACLE_PATH",
    "FRAME_BYTES",
    "KEY_DOWN",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_SPACE",
    "KEY_UP",
    "PORT_VGA_STATUS",
    "RGB",
    "TAC_VERSION",
    "VGA_REFRESH_HZ",
    "ActorTransform",
    "Address",
    "AudioCue",
    "BdaInjector",
    "CameraTransform",
    "DialogSettled",
    "DialogUnsettled",
    "DosboxX",
    "Emulator",
    "EmulatorUnavailable",
    "FilmCapture",
    "GuestTimeout",
    "Key",
    "Launching",
    "ListenTransport",
    "LiveSocketTransport",
    "MockEmulator",
    "MockTransport",
    "Page",
    "PortTaken",
    "SceneHeader",
    "Session",
    "SessionError",
    "SessionEvent",
    "SessionLost",
    "ShortDump",
    "StalePage",
    "StaticPropPlacement",
    "TacClient",
    "TrajectoryRecord",
    "TrajectoryStreamer",
    "Transport",
    "TrapTimeout",
    "VsyncTrap",
    "WaitingForGuest",
    "capture",
    "char_to_key",
    "compute_position_rmse",
    "generate_intro_trajectory",
    "load_trajectory_records",
    "run_session",
    "save_trajectory_records",
]

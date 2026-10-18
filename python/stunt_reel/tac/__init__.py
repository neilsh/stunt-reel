"""Test Automation and Capture (TAC) harness for Stunt Reel.

Provides dual-mode DOSBox-X automation, BIOS Data Area input injection,
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
from stunt_reel.tac.streamer import (
    DEFAULT_ORACLE_PATH,
    TrajectoryStreamer,
    compute_position_rmse,
    generate_intro_trajectory,
)
from stunt_reel.tac.transport import (
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
    "KEY_DOWN",
    "KEY_ENTER",
    "KEY_ESC",
    "KEY_SPACE",
    "KEY_UP",
    "PORT_VGA_STATUS",
    "TAC_VERSION",
    "VGA_REFRESH_HZ",
    "ActorTransform",
    "AudioCue",
    "BdaInjector",
    "CameraTransform",
    "FilmCapture",
    "LiveSocketTransport",
    "MockTransport",
    "SceneHeader",
    "StaticPropPlacement",
    "TacClient",
    "TrajectoryRecord",
    "TrajectoryStreamer",
    "Transport",
    "VsyncTrap",
    "char_to_key",
    "compute_position_rmse",
    "generate_intro_trajectory",
    "load_trajectory_records",
    "save_trajectory_records",
]

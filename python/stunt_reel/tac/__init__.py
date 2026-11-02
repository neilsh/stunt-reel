"""Test Automation and Capture (TAC) harness for Stunt Reel.

Capture runs on dosbox-automation as plans (generated Lua, [`plan`](plan.py)); this package
also holds the Seam 2 trajectory models and the DOS math they share.
"""

from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout
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

__all__ = [
    "ActorTransform",
    "AudioCue",
    "CameraTransform",
    "EmulatorUnavailable",
    "FilmCapture",
    "GuestTimeout",
    "SceneHeader",
    "StaticPropPlacement",
    "TrajectoryRecord",
    "capture",
    "load_trajectory_records",
    "save_trajectory_records",
]

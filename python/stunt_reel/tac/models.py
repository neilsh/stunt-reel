"""Strongly typed data contracts matching Seam 2: Kinematic Trajectory & Film Timeline.

Directly mirrors Rust contracts in crates/stunt-core/src/contracts/trajectory.rs.
Governed by architectural invariants:
- [I1] Metric right-handed coordinate basis (+X right, +Y up, +Z toward viewer, -Z forward)
- [I4] Decoupled fixed simulation ticks (50 Hz) with sub-tick interpolation
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stunt_reel.tac.dos_math import compute_world_matrix as math_compute_world_matrix

__all__ = [
    "ActorTransform",
    "AudioCue",
    "CameraTransform",
    "FilmCapture",
    "SceneHeader",
    "StaticPropPlacement",
    "TrajectoryRecord",
    "load_trajectory_records",
    "save_trajectory_records",
]


@dataclass
class CameraTransform:
    """Evaluated camera transform at a 50 Hz tick."""

    eye: list[float] = field(default_factory=lambda: [0.0, 10.0, 50.0])
    target: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov_degrees: float = 45.0
    roll_radians: float = 0.0
    cut_from_previous: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching Seam 2 JSON schema."""
        d: dict[str, Any] = {
            "eye": [float(x) for x in self.eye],
            "target": [float(x) for x in self.target],
            "fov_degrees": float(self.fov_degrees),
            "roll_radians": float(self.roll_radians),
        }
        if self.cut_from_previous:
            d["cut_from_previous"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraTransform:
        """Create CameraTransform from dictionary."""
        return cls(
            eye=[float(x) for x in data["eye"]],
            target=[float(x) for x in data["target"]],
            fov_degrees=float(data.get("fov_degrees", 45.0)),
            roll_radians=float(data.get("roll_radians", 0.0)),
            cut_from_previous=bool(data.get("cut_from_previous", False)),
        )


@dataclass
class ActorTransform:
    """Evaluated transform and state for an active actor entity in the scene."""

    actor_id: int
    model_name: str
    world_matrix: list[float]
    rotation_quat: list[float]
    position_meters: list[float]
    state_mask: int
    joint_angles_bam: list[tuple[int, int]] = field(default_factory=list)

    def compute_world_matrix(self) -> list[float]:
        """Compute the canonical column-major 4x4 world transformation matrix."""
        return math_compute_world_matrix(self.position_meters, self.rotation_quat)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching Seam 2 JSON schema."""
        d: dict[str, Any] = {
            "actor_id": int(self.actor_id),
            "model_name": str(self.model_name),
            "world_matrix": [float(x) for x in self.world_matrix],
            "rotation_quat": [float(x) for x in self.rotation_quat],
            "position_meters": [float(x) for x in self.position_meters],
            "state_mask": int(self.state_mask),
        }
        if self.joint_angles_bam:
            d["joint_angles_bam"] = [[int(a), int(b)] for a, b in self.joint_angles_bam]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActorTransform:
        """Create ActorTransform from dictionary."""
        raw_joints = data.get("joint_angles_bam", [])
        joint_angles = [(int(j[0]), int(j[1])) for j in raw_joints]
        return cls(
            actor_id=int(data["actor_id"]),
            model_name=str(data["model_name"]),
            world_matrix=[float(x) for x in data["world_matrix"]],
            rotation_quat=[float(x) for x in data["rotation_quat"]],
            position_meters=[float(x) for x in data["position_meters"]],
            state_mask=int(data["state_mask"]),
            joint_angles_bam=joint_angles,
        )


@dataclass
class AudioCue:
    """Discrete sound trigger cue emitted by the film stream."""

    tick: int
    sample_name: str
    volume: float
    pan: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching Seam 2 JSON schema."""
        return {
            "tick": int(self.tick),
            "sample_name": str(self.sample_name),
            "volume": float(self.volume),
            "pan": float(self.pan),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioCue:
        """Create AudioCue from dictionary."""
        return cls(
            tick=int(data["tick"]),
            sample_name=str(data["sample_name"]),
            volume=float(data["volume"]),
            pan=float(data["pan"]),
        )


@dataclass
class TrajectoryRecord:
    """Complete snapshot of the cinematic world state at 50 Hz tick ``tick``.

    ``tick`` is the cumulative authored 50 Hz tick, never a list index or slice ordinal.
    """

    tick: int
    camera: CameraTransform
    actors: list[ActorTransform] = field(default_factory=list)
    audio_cues: list[AudioCue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching Seam 2 JSON schema."""
        return {
            "tick": int(self.tick),
            "camera": self.camera.to_dict(),
            "actors": [actor.to_dict() for actor in self.actors],
            "audio_cues": [cue.to_dict() for cue in self.audio_cues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrajectoryRecord:
        """Create TrajectoryRecord from dictionary."""
        return cls(
            tick=int(data["tick"]),
            camera=CameraTransform.from_dict(data["camera"]),
            actors=[ActorTransform.from_dict(a) for a in data.get("actors", [])],
            audio_cues=[AudioCue.from_dict(c) for c in data.get("audio_cues", [])],
        )


@dataclass
class StaticPropPlacement:
    """Static prop placed once in the stage at film start."""

    model_name: str
    position_meters: list[float]
    rotation_quat: list[float]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_name": str(self.model_name),
            "position_meters": [float(x) for x in self.position_meters],
            "rotation_quat": [float(x) for x in self.rotation_quat],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StaticPropPlacement:
        """Create StaticPropPlacement from dictionary."""
        return cls(
            model_name=str(data["model_name"]),
            position_meters=[float(x) for x in data["position_meters"]],
            rotation_quat=[float(x) for x in data["rotation_quat"]],
        )


@dataclass
class SceneHeader:
    """Static stage setup and environment metadata for a film sequence.

    The playback rate is the constant 50 Hz timeline clock, so it is not stored. A legacy
    ``tick_rate_hz`` key in input dictionaries is ignored.
    """

    film_name: str = ""
    horizon_sky_palette: tuple[int, int] = (0, 0)
    terrain_set_name: str | None = None
    static_props: list[StaticPropPlacement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "film_name": str(self.film_name),
            "horizon_sky_palette": [
                int(self.horizon_sky_palette[0]),
                int(self.horizon_sky_palette[1]),
            ],
            "terrain_set_name": self.terrain_set_name,
            "static_props": [p.to_dict() for p in self.static_props],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SceneHeader:
        """Create SceneHeader from dictionary."""
        raw_pal = data.get("horizon_sky_palette", [0, 0])
        return cls(
            film_name=str(data.get("film_name", "")),
            horizon_sky_palette=(int(raw_pal[0]), int(raw_pal[1])),
            terrain_set_name=data.get("terrain_set_name"),
            static_props=[StaticPropPlacement.from_dict(p) for p in data.get("static_props", [])],
        )


@dataclass
class FilmCapture:
    """Self-contained kinematic capture of a film containing static stage metadata and 50 Hz tick records."""

    header: SceneHeader
    ticks: list[TrajectoryRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "header": self.header.to_dict(),
            "ticks": [t.to_dict() for t in self.ticks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilmCapture:
        """Create FilmCapture from dictionary."""
        return cls(
            header=SceneHeader.from_dict(data["header"]),
            ticks=[TrajectoryRecord.from_dict(t) for t in data.get("ticks", [])],
        )


def load_trajectory_records(path: str | Path) -> list[TrajectoryRecord]:
    """Load list of TrajectoryRecord objects from a JSON file."""
    text = Path(path).read_text(encoding="utf-8")
    raw_list: list[dict[str, Any]] = json.loads(text)
    return [TrajectoryRecord.from_dict(item) for item in raw_list]


def save_trajectory_records(records: Sequence[TrajectoryRecord], path: str | Path) -> None:
    """Save list of TrajectoryRecord objects to a JSON file matching Seam 2 specification."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = [rec.to_dict() for rec in records]
    json_text = json.dumps(payload, indent=2) + "\n"
    dest.write_text(json_text, encoding="utf-8")

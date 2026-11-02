"""Offline unit tests for the TAC models and DOS math.

Verifies:
- 3D math and BAM angle conversions
- Seam 2 dataclass serialization/deserialization

The capture plan, Lua and automation have their own tests (test_tac_plan.py and friends).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from stunt_reel.tac import (
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
from stunt_reel.tac.dos_math import (
    bam_to_radians,
    compute_world_matrix,
    focal_to_fov_y,
    quat_from_euler,
    quat_norm,
    quat_norm_diff,
    quat_normalize,
    vec3_sub,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "oracle_intro_trajectory.json"


# ==============================================================================
# 1. Math Unit Tests
# ==============================================================================


def test_bam_conversions() -> None:
    """Verify Binary Angular Measurement (BAM) 16-bit conversions."""
    assert bam_to_radians(0) == 0.0
    assert math.isclose(bam_to_radians(0x4000), math.pi / 2.0, rel_tol=1e-5)
    assert math.isclose(bam_to_radians(0x8000), math.pi, rel_tol=1e-5)
    assert math.isclose(bam_to_radians(0xC000), 1.5 * math.pi, rel_tol=1e-5)


def test_focal_to_fov_y_conversion() -> None:
    """Verify Stunt Island focal zoom to vertical FOV calculation."""
    focal = 120.0 / math.tan(math.radians(22.5))
    assert math.isclose(focal_to_fov_y(focal), 45.0, abs_tol=1e-4)

    with pytest.raises(ValueError, match="focal_dist must be positive"):
        focal_to_fov_y(0.0)


def test_vec3_sub() -> None:
    """Verify vector subtraction."""
    assert vec3_sub([4.0, 5.0, 6.0], [1.0, 2.0, 3.0]) == [3.0, 3.0, 3.0]


def test_quaternion_normalization() -> None:
    """Verify unit quaternion calculation."""
    q_norm = quat_normalize([0.0, 0.0, 0.0, 2.0])
    assert q_norm == [0.0, 0.0, 0.0, 1.0]
    assert quat_norm(q_norm) == 1.0
    assert quat_norm_diff(q_norm) < 1e-6

    q_euler = quat_from_euler(yaw=0.0, pitch=math.radians(10.0), roll=0.0)
    assert quat_norm_diff(q_euler) < 1e-4


def test_quat_from_euler_invariant_i1_axes() -> None:
    """Verify quat_from_euler maps pitch to X, yaw to Y, and roll to Z per Invariant [I1]."""
    angle = math.radians(30.0)

    q_pitch = quat_from_euler(yaw=0.0, pitch=angle, roll=0.0)
    assert quat_norm_diff(q_pitch) < 1e-6
    m_pitch = compute_world_matrix([0.0, 0.0, 0.0], q_pitch)
    assert pytest.approx(m_pitch[0:3], abs=1e-5) == [1.0, 0.0, 0.0]
    assert pytest.approx(m_pitch[4:7], abs=1e-5) == [0.0, math.cos(angle), -math.sin(angle)]

    q_yaw = quat_from_euler(yaw=angle, pitch=0.0, roll=0.0)
    assert quat_norm_diff(q_yaw) < 1e-6
    m_yaw = compute_world_matrix([0.0, 0.0, 0.0], q_yaw)
    assert pytest.approx(m_yaw[4:7], abs=1e-5) == [0.0, 1.0, 0.0]
    assert pytest.approx(m_yaw[0:3], abs=1e-5) == [math.cos(angle), 0.0, math.sin(angle)]

    q_roll = quat_from_euler(yaw=0.0, pitch=0.0, roll=angle)
    assert quat_norm_diff(q_roll) < 1e-6
    m_roll = compute_world_matrix([0.0, 0.0, 0.0], q_roll)
    assert pytest.approx(m_roll[8:11], abs=1e-5) == [0.0, 0.0, 1.0]
    assert pytest.approx(m_roll[0:3], abs=1e-5) == [math.cos(angle), math.sin(angle), 0.0]

    assert quat_from_euler(0.0, 0.0, 0.0) == [0.0, 0.0, 0.0, 1.0]


def test_compute_world_matrix() -> None:
    """Verify column-major 4x4 matrix computation matching Rust contract."""
    m = compute_world_matrix([10.0, 20.0, 30.0], [0.0, 0.0, 0.0, 1.0])
    assert m == [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        10.0,
        20.0,
        30.0,
        1.0,
    ]


# ==============================================================================
# 2. Models Unit Tests
# ==============================================================================


def test_models_dataclass_serde_roundtrip() -> None:
    """Verify serialization and deserialization of Seam 2 contract dataclasses."""
    cam = CameraTransform(
        eye=[1.0, 2.0, 3.0],
        target=[0.0, 0.0, 0.0],
        fov_degrees=50.0,
        roll_radians=0.05,
        cut_from_previous=True,
    )
    cam_dict = cam.to_dict()
    assert cam_dict["cut_from_previous"] is True
    assert CameraTransform.from_dict(cam_dict) == cam

    actor = ActorTransform(
        actor_id=42,
        model_name="FOKKER",
        rotation_quat=[0.0, 0.0, 0.0, 1.0],
        position_meters=[10.0, 20.0, 30.0],
        state_mask=0x0001,
        joint_angles_bam=[(0, 0x4000)],
    )
    assert ActorTransform.from_dict(actor.to_dict()) == actor
    assert actor.compute_world_matrix() == compute_world_matrix(
        actor.position_meters, actor.rotation_quat
    )

    cue = AudioCue(tick=10, sample_name="ENGINE.VOC", volume=0.8, pan=-0.5)
    assert AudioCue.from_dict(cue.to_dict()) == cue

    record = TrajectoryRecord(tick=10, camera=cam, actors=[actor], audio_cues=[cue])
    assert TrajectoryRecord.from_dict(record.to_dict()) == record

    header = SceneHeader(
        film_name="INTRO",
        horizon_sky_palette=(1, 2),
        terrain_set_name="ISLAND",
        static_props=[
            StaticPropPlacement(
                model_name="TOWER",
                position_meters=[0.0, 0.0, 0.0],
                rotation_quat=[0.0, 0.0, 0.0, 1.0],
            )
        ],
    )
    capture = FilmCapture(header=header, ticks=[record])
    assert FilmCapture.from_dict(capture.to_dict()) == capture


def test_scene_header_ignores_legacy_tick_rate_hz() -> None:
    """Old captures carrying tick_rate_hz still load; the key is not re-emitted."""
    header = SceneHeader.from_dict({"film_name": "INTRO", "tick_rate_hz": 20})
    assert header.film_name == "INTRO"
    assert "tick_rate_hz" not in header.to_dict()


def test_models_file_save_and_load(tmp_path: Path) -> None:
    """Verify loading and saving trajectory records from JSON file."""
    records = load_trajectory_records(FIXTURE_PATH)
    assert [rec.camera.eye for rec in records] == [[0.0, 10.0, 50.0], [0.0, 10.0, 49.5]]
    out_file = tmp_path / "test_traj.json"
    save_trajectory_records(records, out_file)
    assert out_file.exists()

    loaded = load_trajectory_records(out_file)
    assert loaded == records
    assert [rec.tick for rec in loaded] == [0, 1]

"""Offline unit and integration tests for the TAC harness at operation altitude.

Verifies:
- 3D math and BAM angle conversions
- Seam 2 dataclass serialization/deserialization
- MockTransport memory, framebuffer, palette, keystroke and retrace operations
- TacClient typed reads over a transport
- Hardware V-Sync trap 70 Hz -> 50 Hz tick deduplication
- TrajectoryStreamer 600-tick kinematics, unit quaternion invariant, zero matrix tearing,
  and position RMSE <= 0.01 m against the baseline fixture

Wire framing lives in test_tac_transport_framing.py, BDA boundaries in
test_tac_adversarial.py, and the capture session in test_tac_capture_session.py.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from stunt_reel.tac import (
    PORT_VGA_STATUS,
    VGA_REFRESH_HZ,
    ActorTransform,
    AudioCue,
    CameraTransform,
    FilmCapture,
    MockTransport,
    SceneHeader,
    StaticPropPlacement,
    TacClient,
    TrajectoryRecord,
    TrajectoryStreamer,
    VsyncTrap,
    compute_position_rmse,
    generate_intro_trajectory,
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
from stunt_reel.tac.palette import MODE_13H_PALETTE
from stunt_reel.tac.transport import FRAME_BYTES, parse_dac_palette
from stunt_reel.tac.vsync import DEFAULT_TICK_ADDRESS

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
    """Verify the vector subtraction the streamer's RMSE uses."""
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


def test_compute_position_rmse_matches_by_tick_value() -> None:
    """RMSE pairs records by tick value, not list position; unmatched oracle ticks are skipped."""
    oracle = load_trajectory_records(FIXTURE_PATH)
    shifted = [TrajectoryRecord.from_dict(r.to_dict()) for r in oracle]
    for rec in shifted:
        rec.tick += 1000
    assert compute_position_rmse(shifted, FIXTURE_PATH) == float("inf")
    assert compute_position_rmse(list(reversed(oracle)), FIXTURE_PATH) == 0.0
    assert compute_position_rmse(oracle[1:], FIXTURE_PATH) == 0.0


def test_models_file_save_and_load(tmp_path: Path) -> None:
    """Verify loading and saving trajectory records from JSON file."""
    records = generate_intro_trajectory(5)
    out_file = tmp_path / "test_traj.json"
    save_trajectory_records(records, out_file)
    assert out_file.exists()

    loaded = load_trajectory_records(out_file)
    assert len(loaded) == 5
    assert loaded[0].tick == 0
    assert loaded[0].camera.eye == [0.0, 10.0, 50.0]


# ==============================================================================
# 3. MockTransport Operations
# ==============================================================================


def test_mock_memory_operations() -> None:
    """Read and write virtual memory through the transport operations."""
    mock = MockTransport()
    mock.write_memory((0x0D51, 0x0100), bytes([0x12, 0x34, 0xAB, 0xCD]))
    assert mock.read_memory((0x0D51, 0x0100), 4) == bytes([0x12, 0x34, 0xAB, 0xCD])
    assert mock.read_memory((0x0D51, 0x0100), 0) == b""

    mock.write_u16(0x0D51, 0x0200, 0x1234)
    assert mock.read_u16(0x0D51, 0x0200) == 0x1234


def test_mock_framebuffer_and_palette_operations() -> None:
    """Serve framebuffer pages from bytes or a hook, and palettes with provenance."""
    mock = MockTransport()
    assert len(mock.dump_framebuffer()) == FRAME_BYTES
    assert mock.dump_framebuffer() == bytes(FRAME_BYTES)

    mock.framebuffer[0:4] = b"\x01\x02\x03\x04"
    assert mock.dump_framebuffer()[0:4] == b"\x01\x02\x03\x04"

    pages = [b"\x0a" * FRAME_BYTES, b"\x0b" * FRAME_BYTES]
    mock.dump_source = lambda: pages.pop(0)
    assert mock.dump_framebuffer() == b"\x0a" * FRAME_BYTES
    assert mock.dump_framebuffer() == b"\x0b" * FRAME_BYTES

    fallback, source = mock.read_palette()
    assert source == "fallback"
    assert fallback == [tuple(rgb) for rgb in MODE_13H_PALETTE]

    configured = ([(255, 0, 0)] * 256, "dacpal")
    mock.palette = configured
    assert mock.read_palette() == configured


def test_mock_inject_key_and_retrace_operations() -> None:
    """Queue a keystroke into the simulated BDA and advance the guest per retrace step."""
    mock = MockTransport()
    mock.inject_key((0x0D, 0x1C))
    assert mock.read_memory((0x0040, 0x001E), 2) == b"\x0d\x1c"
    assert mock.read_u16(0x0040, 0x001C) == 0x0020

    assert mock.current_tick == 0
    mock.step_to_retrace()
    assert mock.current_tick == 1
    assert mock.read_u16(*mock.tick_address) == 1

    mock.retrace_source = lambda: mock.set_sim_tick(7)
    mock.step_to_retrace()
    assert mock.current_tick == 7


def test_parse_dac_palette_scales_and_falls_back() -> None:
    """DACPAL lines scale 6-bit DAC channels to 8 bits; short listings fall back."""
    lines = [f"{row * 8:02X}: " + " ".join(["3F0000"] * 8) for row in range(32)]
    palette, source = parse_dac_palette(lines)
    assert source == "dacpal"
    assert palette == [(255, 0, 0)] * 256

    palette, source = parse_dac_palette(["00: 3F0000"])
    assert source == "fallback"
    assert palette == [tuple(rgb) for rgb in MODE_13H_PALETTE]


def test_mock_closed_operations_raise() -> None:
    """Every operation refuses after close."""
    mock = MockTransport()
    assert mock.is_connected()
    mock.close()
    assert not mock.is_connected()
    for operation in (
        lambda: mock.read_memory((0x0D51, 0x0100), 2),
        lambda: mock.write_memory((0x0D51, 0x0100), b"\x00"),
        mock.dump_framebuffer,
        mock.read_palette,
        lambda: mock.inject_key((0x0D, 0x1C)),
        mock.step_to_retrace,
    ):
        with pytest.raises(ConnectionError):
            operation()


# ==============================================================================
# 4. Client Typed Reads
# ==============================================================================


def test_tac_client_memory_helpers() -> None:
    """Verify TacClient typed reading helpers against MockTransport."""
    mock = MockTransport()
    with TacClient(mock) as client:
        mock.write_memory((0x0D51, 0x0200), bytes([0x78]))
        assert client.read_u8("0D51:0200") == 0x78

        mock.write_u16(0x0D51, 0x0202, 0x1234)
        assert client.read_u16("0D51:0202") == 0x1234
        assert client.read_i16("0D51:0202") == 0x1234

        mock.write_memory((0x0D51, 0x0204), (688128).to_bytes(4, "little", signed=True))
        assert math.isclose(client.read_fixed16_16("0D51:0204"), 10.5, abs_tol=1e-5)
        assert client.read_i32("0D51:0204") == 688128
        assert client.read_u32("0D51:0204") == 688128

        mock.write_memory((0x0D51, 0x0208), b"FOKKER\x00PADDING")
        assert client.read_string("0D51:0208") == "FOKKER"

        with pytest.raises(ValueError, match="Expected <seg>:<off>"):
            client.read_u16("0D510202")

        # A truncated read surfaces as the typed-read failure, not silent garbage.
        mock.memory = mock.memory[: (0x0D51 << 4) + 0x0200]
        with pytest.raises(RuntimeError, match="u16"):
            client.read_u16("0D51:0200")


# ==============================================================================
# 5. V-Sync Trap & Deduplication Unit Tests
# ==============================================================================


def test_vsync_trap_tick_deduplication() -> None:
    """Verify V-Sync trap deduplication downsampling 70 Hz frames to 50 Hz ticks."""
    assert PORT_VGA_STATUS == 0x03DA
    assert math.isclose(VGA_REFRESH_HZ, 70.087, rel_tol=1e-3)

    mock = MockTransport()
    trap = VsyncTrap(tick_address=DEFAULT_TICK_ADDRESS)

    # Simulate a 70 Hz VGA retrace: the sim tick advances only once every 3 steps.
    step_count = 0

    def mock_retrace() -> None:
        nonlocal step_count
        step_count += 1
        mock.set_sim_tick(step_count // 3)

    mock.retrace_source = mock_retrace

    assert trap.wait_next_sim_tick(mock) == 0
    assert trap.captured_frames == 1

    assert trap.wait_next_sim_tick(mock) == 1
    assert trap.captured_frames == 2
    assert trap.duplicate_frames_dropped > 0


def test_vsync_trap_timeout() -> None:
    """Verify VsyncTrap raises TimeoutError if simulation tick fails to advance."""
    mock = MockTransport()
    trap = VsyncTrap(max_spins_per_tick=5)
    trap.last_captured_tick = 0

    # Freeze tick counter at 0.
    mock.retrace_source = lambda: None

    with pytest.raises(TimeoutError):
        trap.wait_next_sim_tick(mock)


# ==============================================================================
# 6. Streamer & Golden Oracle Unit Tests
# ==============================================================================


def test_decode_camera_from_memory_direct() -> None:
    """Verify direct memory decoding of 32-byte camera rig structure [MEM-CAMERA-RIG]."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    eye_raw = [round(x * 65536.0) for x in [10.0, 20.0, 30.0]]
    tgt_raw = [round(x * 65536.0) for x in [0.0, 5.0, 0.0]]
    raw_cam = struct.pack(
        "<6iHHHH",
        eye_raw[0],
        eye_raw[1],
        eye_raw[2],
        tgt_raw[0],
        tgt_raw[1],
        tgt_raw[2],
        290,
        0x2000,
        1,
        0,
    )
    mock.write_bytes(0x0D51, 0x0C10, raw_cam)

    cam, decoded_mode = streamer.decode_camera_from_memory("0D51:0C10")
    assert pytest.approx(cam.eye, abs=1e-4) == [10.0, 20.0, 30.0]
    assert pytest.approx(cam.target, abs=1e-4) == [0.0, 5.0, 0.0]
    assert math.isclose(cam.fov_degrees, focal_to_fov_y(290.0), abs_tol=1e-4)
    assert math.isclose(cam.roll_radians, bam_to_radians(0x2000), abs_tol=1e-4)
    assert decoded_mode == 1
    assert cam.cut_from_previous is False

    cam2, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=[100.0, 20.0, 30.0])
    assert cam2.cut_from_previous is True

    cam3, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam.eye, last_mode=2)
    assert cam3.cut_from_previous is True


def test_decode_actor_from_memory_direct() -> None:
    """Verify direct memory decoding of 64-byte actor record [MEM-ACTOR-TABLE]."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    pos_raw = [round(x * 65536.0) for x in [5.0, 15.0, 25.0]]
    rot = quat_normalize([0.0, 0.0, 0.0, 1.0])
    raw_header = struct.pack(
        "<I8s3i4fHH",
        1,
        b"FOKKER\x00\x00",
        pos_raw[0],
        pos_raw[1],
        pos_raw[2],
        rot[0],
        rot[1],
        rot[2],
        rot[3],
        1,
        1,
    )
    joints_buf = bytearray(16)
    struct.pack_into("<HH", joints_buf, 0, 0, 0x4000)
    mock.write_bytes(0x0D51, 0x0CA0, raw_header + joints_buf + struct.pack("<HH", 0, 0))

    actor, next_addr = streamer.decode_actor_from_memory("0D51:0CA0")
    assert actor.actor_id == 1
    assert actor.model_name == "FOKKER"
    assert pytest.approx(actor.position_meters, abs=1e-4) == [5.0, 15.0, 25.0]
    assert quat_norm_diff(actor.rotation_quat) < 1e-6
    assert actor.state_mask == 1
    assert actor.joint_angles_bam == [(0, 0x4000)]
    assert next_addr is None


def test_decode_actors_linked_list() -> None:
    """Verify traversal of chained actors starting from dynamic heap pointer [MEM-ACTOR-TABLE]."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    raw_act1 = (
        struct.pack("<I8s3i4fHH", 1, b"FOKKER\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0)
        + bytearray(16)
        + struct.pack("<HH", 0x0CE0, 0x0D51)
    )
    mock.write_bytes(0x0D51, 0x0CA0, raw_act1)

    raw_act2 = (
        struct.pack("<I8s3i4fHH", 2, b"TARGET\x00\x00", 655360, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0)
        + bytearray(16)
        + struct.pack("<HH", 0x0000, 0x0000)
    )
    mock.write_bytes(0x0D51, 0x0CE0, raw_act2)

    mock.write_u16(0x0D51, 0x0C50, 0x0CA0)
    mock.write_u16(0x0D51, 0x0C52, 0x0D51)

    actors = streamer.decode_actors_from_memory("0D51:0C50")
    assert len(actors) == 2
    assert actors[0].actor_id == 1
    assert actors[0].model_name == "FOKKER"
    assert actors[1].actor_id == 2
    assert actors[1].model_name == "TARGET"


def test_streamer_generates_600_continuous_ticks() -> None:
    """Verify generation of exactly 600 continuous simulation ticks."""
    records = generate_intro_trajectory(600)
    assert len(records) == 600
    for idx, rec in enumerate(records):
        assert rec.tick == idx
        assert len(rec.actors) == 1
        assert rec.actors[0].model_name == "FOKKER"


def test_streamer_exact_match_against_baseline_fixture() -> None:
    """Verify exact match for initial ticks captured from memory against the baseline fixture."""
    mock = MockTransport()
    mock.load_trajectory(generate_intro_trajectory(2))
    streamer = TrajectoryStreamer(TacClient(mock))
    records = streamer.capture_ticks(2)

    assert FIXTURE_PATH.exists()
    baseline = load_trajectory_records(FIXTURE_PATH)

    assert records[0].tick == 0
    assert pytest.approx(records[0].camera.eye, abs=1e-4) == baseline[0].camera.eye
    assert pytest.approx(records[0].camera.target, abs=1e-4) == baseline[0].camera.target
    assert (
        pytest.approx(records[0].actors[0].position_meters, abs=1e-4)
        == baseline[0].actors[0].position_meters
    )
    assert (
        pytest.approx(records[0].actors[0].compute_world_matrix(), abs=1e-4)
        == baseline[0].actors[0].compute_world_matrix()
    )
    assert len(records[0].audio_cues) == 1
    assert records[0].audio_cues[0].sample_name == "ENGINE.VOC"

    assert records[1].tick == 1
    assert pytest.approx(records[1].camera.eye, abs=1e-4) == baseline[1].camera.eye
    assert (
        pytest.approx(records[1].actors[0].position_meters, abs=1e-4)
        == baseline[1].actors[0].position_meters
    )
    assert (
        pytest.approx(records[1].actors[0].compute_world_matrix(), abs=1e-4)
        == baseline[1].actors[0].compute_world_matrix()
    )
    assert len(records[1].audio_cues) == 0


def test_streamer_quaternion_normalization() -> None:
    """Verify | ||q|| - 1.0 | < 1e-4 across 600 ticks captured from memory."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))
    records = streamer.capture_ticks(600)

    assert len(records) == 600
    for rec in records:
        for actor in rec.actors:
            diff = quat_norm_diff(actor.rotation_quat)
            assert diff < 1e-4, f"Quaternion norm error at tick {rec.tick}: {diff}"


def test_streamer_position_rmse_threshold() -> None:
    """Verify position RMSE <= 0.01 m against baseline fixture for memory capture."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))
    records = streamer.capture_ticks(600)

    rmse = compute_position_rmse(records, FIXTURE_PATH)
    assert rmse <= 0.01, f"RMSE {rmse:.6f} m exceeds 0.01 m threshold"


def test_oracle_intro_trajectory_file_exists_and_valid(tmp_path: Path) -> None:
    """Verify a streamed oracle trajectory contains 600 valid ticks."""
    oracle_file = tmp_path / "intro_trajectory.json"
    TrajectoryStreamer.stream_oracle_intro(oracle_file)

    assert oracle_file.exists()
    records = load_trajectory_records(oracle_file)
    assert len(records) == 600
    assert records[0].tick == 0
    assert records[599].tick == 599

    rmse = compute_position_rmse(records, FIXTURE_PATH)
    assert rmse <= 0.01

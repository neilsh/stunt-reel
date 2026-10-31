"""Adversarial stress testing and empirical verification suite for TAC remediation.

Covers the parts of the harness that survive at the operation altitude:

1. BIOS Data Area keyboard buffer boundary conditions through Transport.inject_key:
   odd/out-of-range pointer normalization, ring wrapping, capacity, atomic overflow,
   and the dialog's keystroke sequence.
2. Direct memory decoding: camera and actor structures on synthetic RAM states,
   truncated reads, camera cuts, linked-list traversal, cycle and degenerate guards.
3. Invariant [I1] Euler kinematics: axis mapping, orthogonality, determinant, extremes.
4. Golden oracle and asset isolation over 600 ticks.

Wire framing, request ids and buffer recovery live in test_tac_transport_framing.py.
"""

from __future__ import annotations

import math
import random
import struct
import subprocess
from pathlib import Path

import pytest

from stunt_reel.tac import (
    DEFAULT_ORACLE_PATH,
    KEY_DOWN,
    KEY_ENTER,
    BdaInjector,
    MockTransport,
    TacClient,
    TrajectoryStreamer,
    char_to_key,
    compute_position_rmse,
    generate_intro_trajectory,
)
from stunt_reel.tac.dos_math import (
    compute_world_matrix,
    focal_to_fov_y,
    quat_from_euler,
    quat_norm,
    quat_norm_diff,
)
from stunt_reel.tac.playone import film_selection_keys

FIXTURE_PATH = Path("tests/fixtures/oracle_intro_trajectory.json")


def _bda_state(mock: MockTransport) -> tuple[int, int]:
    return BdaInjector.get_buffer_state(mock)


def _set_bda_pointers(mock: MockTransport, head: int, tail: int) -> None:
    mock.write_u16(0x0040, 0x001A, head)
    mock.write_u16(0x0040, 0x001C, tail)


# ==============================================================================
# 1. BDA Keyboard Buffer Boundary Conditions
# ==============================================================================


def test_bda_odd_tail_pointer_normalized_and_canary_safe() -> None:
    """Stress test: tail at odd 0x003D is normalized to 0x001E without corrupting Floppy status (0040:003E)."""
    mock = MockTransport()
    _set_bda_pointers(mock, 0x0024, 0x003D)

    canary = b"\xa5"
    mock.write_memory((0x0040, 0x003E), canary)

    mock.inject_key(KEY_ENTER)

    # 1. Canary byte at 0040:003E must be completely untouched
    assert mock.read_memory((0x0040, 0x003E), 1) == canary

    # 2. Tail was normalized from 0x003D to 0x001E, then advanced to 0x0020
    head, tail = _bda_state(mock)
    assert head == 0x0024
    assert tail == 0x0020

    # 3. Key was written at 0x001E
    raw_key = mock.read_memory((0x0040, 0x001E), 2)
    assert raw_key == bytes([KEY_ENTER[0], KEY_ENTER[1]])


def test_bda_odd_pointers_sweep() -> None:
    """Verify that every odd pointer in range [0x001D..0x003F] is normalized to 0x001E."""
    for odd_tail in range(0x001D, 0x0041, 2):
        mock = MockTransport()
        _set_bda_pointers(mock, 0x0024, odd_tail)

        mock.inject_key(KEY_ENTER)

        _head, tail = _bda_state(mock)
        assert tail == 0x0020


def test_bda_out_of_bounds_pointers() -> None:
    """Verify that pointers outside [0x001E..0x003C] are normalized to 0x001E."""
    oob_values = [0x0000, 0x001C, 0x003E, 0x0040, 0x1000, 0xFFFF]

    for oob in oob_values:
        mock = MockTransport()
        _set_bda_pointers(mock, oob, oob)

        mock.inject_key(KEY_ENTER)

        head, tail = _bda_state(mock)
        assert head == 0x001E
        assert tail == 0x0020


def test_bda_ring_buffer_wrapping() -> None:
    """Verify circular ring buffer wrapping when tail advances past 0040:003E."""
    mock = MockTransport()
    _set_bda_pointers(mock, 0x0028, 0x003C)

    mock.inject_key(KEY_ENTER)
    mock.inject_key(char_to_key("c"))

    _, new_tail = _bda_state(mock)
    assert new_tail == 0x0020


def test_bda_capacity_and_overflow_sweep() -> None:
    """Verify full buffer capacity: 15 keys max in empty 16-word ring buffer."""
    mock = MockTransport()
    _set_bda_pointers(mock, 0x001E, 0x001E)

    keys_15 = [char_to_key(chr(ord("a") + (i % 26))) for i in range(15)]
    for key in keys_15:
        mock.inject_key(key)

    _head, tail = _bda_state(mock)
    assert tail == 0x003C  # 0x001E + 30 = 0x003C

    # Buffer is now full: injecting 1 additional key must raise BufferError
    with pytest.raises(BufferError):
        mock.inject_key(KEY_ENTER)


def test_bda_atomic_overflow_preserves_memory() -> None:
    """Verify all-or-nothing atomicity: overflowing sequence writes ZERO bytes to RAM."""
    mock = MockTransport()
    # 1 slot available: head=0x0024, tail=0x0020
    _set_bda_pointers(mock, 0x0024, 0x0020)

    canary = b"\x77\x88\x99\xaa"
    mock.write_memory((0x0040, 0x0020), canary)

    # Attempt to inject 2 keys (only 1 slot available)
    with pytest.raises(BufferError):
        BdaInjector.inject_keys(mock, [char_to_key("x"), char_to_key("y")])

    assert mock.read_memory((0x0040, 0x0020), 4) == canary

    _head, tail = _bda_state(mock)
    assert tail == 0x0020


def test_bda_empty_film_prefix_defaults() -> None:
    """Verify the dialog key sequence falls back to the default film letter."""
    keys = film_selection_keys("")
    assert keys[0] == char_to_key("c")
    assert keys[1] == KEY_DOWN
    assert keys[2] == KEY_ENTER

    intro = film_selection_keys("INTRO.FLM")
    assert intro[0] == char_to_key("i")


def test_bda_char_to_key_comprehensive() -> None:
    """Verify char_to_key mapping for alphanumerics, punctuation, uppercase, and error cases."""
    assert char_to_key(".") == (ord("."), 0x34)
    assert char_to_key("-") == (ord("-"), 0x0C)
    assert char_to_key("_") == (ord("_"), 0x0C)
    assert char_to_key("A")[1] == char_to_key("a")[1]

    with pytest.raises(ValueError, match="char_to_key expects single character"):
        char_to_key("")

    with pytest.raises(ValueError, match="char_to_key expects single character"):
        char_to_key("two")


# ==============================================================================
# 2. Direct Memory Decoding
# ==============================================================================


def test_decode_camera_from_memory_synthetic_rig() -> None:
    """Verify decode_camera_from_memory on synthetic 32-byte binary rig structure."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    eye_raw = [round(-100.5 * 65536.0), round(25.25 * 65536.0), round(-50.75 * 65536.0)]
    tgt_raw = [round(10.0 * 65536.0), round(-5.0 * 65536.0), round(100.0 * 65536.0)]
    cam_bytes = struct.pack(
        "<6iHHHH",
        eye_raw[0],
        eye_raw[1],
        eye_raw[2],
        tgt_raw[0],
        tgt_raw[1],
        tgt_raw[2],
        290,
        0x4000,
        3,
        0,
    )
    mock.write_memory((0x0D51, 0x0C10), cam_bytes)

    cam, decoded_mode = streamer.decode_camera_from_memory("0D51:0C10")

    assert decoded_mode == 3
    assert math.isclose(cam.eye[0], -100.5, abs_tol=1e-4)
    assert math.isclose(cam.eye[1], 25.25, abs_tol=1e-4)
    assert math.isclose(cam.eye[2], -50.75, abs_tol=1e-4)
    assert math.isclose(cam.target[0], 10.0, abs_tol=1e-4)
    assert math.isclose(cam.target[1], -5.0, abs_tol=1e-4)
    assert math.isclose(cam.target[2], 100.0, abs_tol=1e-4)
    assert math.isclose(cam.fov_degrees, focal_to_fov_y(290.0), abs_tol=1e-3)
    assert math.isclose(cam.roll_radians, math.pi / 2.0, abs_tol=1e-4)
    assert not cam.cut_from_previous


def test_decode_camera_cut_displacement_and_mode() -> None:
    """Verify camera cut flag triggers when displacement > 50 m or mode changes."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    cam_bytes1 = struct.pack("<6iHHHH", 0, 0, 0, 0, 0, 0, 290, 0, 1, 0)
    mock.write_memory((0x0D51, 0x0C10), cam_bytes1)
    cam1, mode1 = streamer.decode_camera_from_memory("0D51:0C10")
    assert not cam1.cut_from_previous

    cam_bytes2 = struct.pack("<6iHHHH", 0, round(60.0 * 65536.0), 0, 0, 0, 0, 290, 0, 1, 0)
    mock.write_memory((0x0D51, 0x0C10), cam_bytes2)
    cam2, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam1.eye, last_mode=mode1)
    assert cam2.cut_from_previous

    cam_bytes3 = struct.pack("<6iHHHH", 0, round(5.0 * 65536.0), 0, 0, 0, 0, 290, 0, 2, 0)
    mock.write_memory((0x0D51, 0x0C10), cam_bytes3)
    cam3, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam1.eye, last_mode=mode1)
    assert cam3.cut_from_previous


def test_decode_camera_zero_focal_and_truncated() -> None:
    """Verify fallback for zero focal distance and error on truncated memory read."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    cam_bytes = struct.pack("<6iHHHH", 0, 0, 0, 0, 0, 0, 0, 0, 1, 0)
    mock.write_memory((0x0D51, 0x0C10), cam_bytes)
    cam, _ = streamer.decode_camera_from_memory("0D51:0C10")
    assert cam.fov_degrees == 45.0

    # Truncated read (< 32 bytes): shrink the virtual memory below the camera rig.
    rig_end = (0x0D51 << 4) + 0x0C10 + 16
    mock.memory = mock.memory[:rig_end]
    with pytest.raises(RuntimeError):
        streamer.decode_camera_from_memory("0D51:0C10")


def test_decode_actor_from_memory_synthetic() -> None:
    """Verify decode_actor_from_memory on synthetic 64-byte binary record."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    pos_raw = [round(-15.5 * 65536.0), round(30.25 * 65536.0), round(120.0 * 65536.0)]
    header = struct.pack(
        "<I8s3i4fHH",
        42,
        b"FOKKER\x00\x00",
        pos_raw[0],
        pos_raw[1],
        pos_raw[2],
        0.0,
        0.0,
        0.0,
        1.0,
        0x0005,
        2,
    )
    joints = struct.pack("<HHHH8x", 1, 0x1000, 2, 0x2000)
    next_ptr = struct.pack("<HH", 0x0CE0, 0x0D51)
    mock.write_memory((0x0D51, 0x0CA0), header + joints + next_ptr)

    actor, next_addr = streamer.decode_actor_from_memory("0D51:0CA0")

    assert actor.actor_id == 42
    assert actor.model_name == "FOKKER"
    assert math.isclose(actor.position_meters[0], -15.5, abs_tol=1e-4)
    assert math.isclose(actor.position_meters[1], 30.25, abs_tol=1e-4)
    assert math.isclose(actor.position_meters[2], 120.0, abs_tol=1e-4)
    assert actor.rotation_quat == [0.0, 0.0, 0.0, 1.0]
    assert actor.state_mask == 0x0005
    assert actor.joint_angles_bam == [(1, 0x1000), (2, 0x2000)]
    assert next_addr == "0D51:0CE0"


def test_decode_actors_linked_list_traversal() -> None:
    """Verify decode_actors_from_memory traverses linked chain of actors."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    offsets = [0x0CA0, 0x0CE0, 0x0D20]
    for idx, off in enumerate(offsets):
        act_id = idx + 1
        has_next = (idx + 1) < len(offsets)
        next_off = offsets[idx + 1] if has_next else 0
        next_seg = 0x0D51 if has_next else 0
        header = struct.pack(
            "<I8s3i4fHH",
            act_id,
            f"ACT_{act_id}".encode().ljust(8, b"\x00"),
            0,
            0,
            0,
            0.0,
            0.0,
            0.0,
            1.0,
            1,
            0,
        )
        next_ptr = struct.pack("<HH", next_off, next_seg)
        mock.write_memory((0x0D51, off), header + bytes(16) + next_ptr)

    mock.write_u16(0x0D51, 0x0C50, 0x0CA0)
    mock.write_u16(0x0D51, 0x0C52, 0x0D51)

    actors = streamer.decode_actors_from_memory("0D51:0C50")
    assert len(actors) == 3
    assert [a.actor_id for a in actors] == [1, 2, 3]


def test_decode_actors_circular_reference_protection() -> None:
    """Verify cycle detection in actor linked list prevents infinite loops."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    header1 = struct.pack(
        "<I8s3i4fHH", 1, b"ACT1\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0
    )
    mock.write_memory((0x0D51, 0x0CA0), header1 + bytes(16) + struct.pack("<HH", 0x0CE0, 0x0D51))

    header2 = struct.pack(
        "<I8s3i4fHH", 2, b"ACT2\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0
    )
    mock.write_memory((0x0D51, 0x0CE0), header2 + bytes(16) + struct.pack("<HH", 0x0CA0, 0x0D51))

    mock.write_u16(0x0D51, 0x0C50, 0x0CA0)
    mock.write_u16(0x0D51, 0x0C52, 0x0D51)

    actors = streamer.decode_actors_from_memory("0D51:0C50")
    assert len(actors) == 2
    assert [a.actor_id for a in actors] == [1, 2]


def test_decode_actor_degenerate_zero_quaternion() -> None:
    """Verify zero quaternion [0, 0, 0, 0] in RAM defaults safely to identity [0, 0, 0, 1]."""
    mock = MockTransport()
    streamer = TrajectoryStreamer(TacClient(mock))

    header = struct.pack(
        "<I8s3i4fHH", 1, b"ACT1\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 1, 0
    )
    mock.write_memory((0x0D51, 0x0CA0), header + bytes(20))

    actor, _ = streamer.decode_actor_from_memory("0D51:0CA0")
    assert actor.rotation_quat == [0.0, 0.0, 0.0, 1.0]
    assert math.isclose(quat_norm(actor.rotation_quat), 1.0, abs_tol=1e-6)


# ==============================================================================
# 3. Invariant [I1] Euler Kinematics
# ==============================================================================


def test_euler_pitch_tilts_y_toward_neg_z() -> None:
    """Verify Invariant [I1]: Positive pitch tilts +Y toward -Z while +X is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=0.0, pitch=rad, roll=0.0)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(x_prime[0], 1.0, abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)

        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[2], -math.sin(rad), abs_tol=1e-5)
        assert y_prime[2] < 0.0

        assert math.isclose(z_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[1], math.sin(rad), abs_tol=1e-5)
        assert math.isclose(z_prime[2], math.cos(rad), abs_tol=1e-5)
        assert z_prime[1] > 0.0


def test_euler_yaw_turns_x_toward_pos_z() -> None:
    """Verify Invariant [I1]: Positive yaw turns +X toward +Z while +Y is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=rad, pitch=0.0, roll=0.0)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], 1.0, abs_tol=1e-5)
        assert math.isclose(y_prime[2], 0.0, abs_tol=1e-5)

        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], math.sin(rad), abs_tol=1e-5)
        assert x_prime[2] > 0.0

        assert math.isclose(z_prime[0], -math.sin(rad), abs_tol=1e-5)
        assert math.isclose(z_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[2], math.cos(rad), abs_tol=1e-5)
        assert z_prime[0] < 0.0


def test_euler_roll_banks_x_toward_pos_y() -> None:
    """Verify Invariant [I1]: Positive roll banks +X toward +Y while +Z is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=0.0, pitch=0.0, roll=rad)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(z_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[2], 1.0, abs_tol=1e-5)

        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], math.sin(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)
        assert x_prime[1] > 0.0

        assert math.isclose(y_prime[0], -math.sin(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[1], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[2], 0.0, abs_tol=1e-5)
        assert y_prime[0] < 0.0


def test_euler_matrix_orthogonality_and_determinant_1000_samples() -> None:
    """Stress test 1,000 random Euler angles: verify orthogonality (M^T M = I) and det(M) = +1.0."""
    rng = random.Random(42)  # noqa: S311

    for _ in range(1000):
        yaw = rng.uniform(-math.pi, math.pi)
        pitch = rng.uniform(-0.49 * math.pi, 0.49 * math.pi)
        roll = rng.uniform(-math.pi, math.pi)

        q = quat_from_euler(yaw=yaw, pitch=pitch, roll=roll)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        r0 = [m[0], m[1], m[2]]
        r1 = [m[4], m[5], m[6]]
        r2 = [m[8], m[9], m[10]]

        assert math.isclose(sum(x * x for x in r0), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r1), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r2), 1.0, abs_tol=1e-5)

        assert math.isclose(sum(a * b for a, b in zip(r0, r1, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r0, r2, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r1, r2, strict=True)), 0.0, abs_tol=1e-5)

        cross = [
            r1[1] * r2[2] - r1[2] * r2[1],
            r1[2] * r2[0] - r1[0] * r2[2],
            r1[0] * r2[1] - r1[1] * r2[0],
        ]
        det = sum(a * b for a, b in zip(r0, cross, strict=True))
        assert math.isclose(det, 1.0, abs_tol=1e-5)


def test_euler_extreme_angles() -> None:
    """Verify stability at extreme boundary angles (0, 180, -180, 360, 720 degrees)."""
    for ang in [0.0, math.pi, -math.pi, 2.0 * math.pi, 4.0 * math.pi]:
        for q in (
            quat_from_euler(yaw=0.0, pitch=ang, roll=0.0),
            quat_from_euler(yaw=ang, pitch=0.0, roll=0.0),
            quat_from_euler(yaw=0.0, pitch=0.0, roll=ang),
        ):
            assert quat_norm_diff(q) < 1e-14


# ==============================================================================
# 4. Full Integration & Golden Oracle Validation
# ==============================================================================


def test_trajectory_streamer_600_ticks_complete() -> None:
    """Verify 600 continuous simulation ticks adhere strictly to all architectural invariants."""
    records = generate_intro_trajectory(600)
    assert len(records) == 600

    for rec in records:
        assert all(not math.isnan(x) and not math.isinf(x) for x in rec.camera.eye)
        assert all(not math.isnan(x) and not math.isinf(x) for x in rec.camera.target)
        assert 0.0 < rec.camera.fov_degrees < 180.0
        for actor in rec.actors:
            assert quat_norm_diff(actor.rotation_quat) < 1e-14

    if FIXTURE_PATH.exists():
        rmse = compute_position_rmse(records, FIXTURE_PATH)
        assert rmse <= 0.01


def test_default_oracle_is_a_gitignored_build_output() -> None:
    """The synthetic oracle is written under build/, which Git ignores, never into the corpus."""
    path = DEFAULT_ORACLE_PATH.as_posix()
    assert path.startswith("build/")
    res = subprocess.run(  # noqa: S603
        ["git", "check-ignore", path],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0

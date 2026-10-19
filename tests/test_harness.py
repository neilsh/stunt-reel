"""Comprehensive offline unit and integration test suite for the TAC harness.

Verifies:
- 3D math and BAM angle conversions
- Seam 2 dataclass serialization/deserialization
- MockTransport in-memory emulation and LiveSocketTransport framing
- TacClient memory reading, writing, and debugger commands
- BDA keystroke buffer ring arithmetic, wrapping, overflow, and modal dialog navigation
- Hardware V-Sync trap arming and 70 Hz -> 20/30 Hz tick deduplication
- TrajectoryStreamer 600-tick kinematics, unit quaternion invariant, zero matrix tearing,
  and position RMSE <= 0.01 m against baseline fixture
"""

from __future__ import annotations

import math
import socket
import struct
import threading
from pathlib import Path

import pytest

from stunt_reel.math import (
    bam_to_degrees,
    bam_to_radians,
    compute_world_matrix,
    degrees_to_bam,
    focal_to_fov_y,
    fov_y_to_focal,
    quat_from_direction_cosines,
    quat_from_euler,
    quat_norm,
    quat_norm_diff,
    quat_normalize,
    radians_to_bam,
    vec3_add,
    vec3_cross,
    vec3_displace,
    vec3_dot,
    vec3_length,
    vec3_normalize,
    vec3_scale,
    vec3_sub,
)
from stunt_reel.tac import (
    KEY_ENTER,
    PORT_VGA_STATUS,
    VGA_REFRESH_HZ,
    ActorTransform,
    AudioCue,
    BdaInjector,
    CameraTransform,
    FilmCapture,
    LiveSocketTransport,
    MockTransport,
    SceneHeader,
    StaticPropPlacement,
    TacClient,
    TrajectoryRecord,
    TrajectoryStreamer,
    VsyncTrap,
    char_to_key,
    compute_position_rmse,
    generate_intro_trajectory,
    load_trajectory_records,
    save_trajectory_records,
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

    assert radians_to_bam(0.0) == 0
    assert radians_to_bam(math.pi / 2.0) == 0x4000
    assert radians_to_bam(math.pi) == 0x8000

    assert bam_to_degrees(0x4000) == 90.0
    assert degrees_to_bam(90.0) == 0x4000
    assert degrees_to_bam(180.0) == 0x8000


def test_focal_to_fov_y_conversion() -> None:
    """Verify Stunt Island focal zoom to vertical FOV calculation."""
    # Standard focal distance ~289.777 gives exactly 45 degrees
    focal = 120.0 / math.tan(math.radians(22.5))
    fov = focal_to_fov_y(focal)
    assert math.isclose(fov, 45.0, abs_tol=1e-4)

    # Roundtrip check
    assert math.isclose(fov_y_to_focal(fov), focal, rel_tol=1e-5)

    with pytest.raises(ValueError, match="focal_dist must be positive"):
        focal_to_fov_y(0.0)
    with pytest.raises(ValueError, match="fov_degrees must be strictly between 0 and 180"):
        fov_y_to_focal(0.0)


def test_vector_operations_and_decal_displacement() -> None:
    """Verify vector arithmetic and Invariant [I5] coplanar decal offset."""
    v1 = [1.0, 2.0, 3.0]
    v2 = [4.0, 5.0, 6.0]

    assert vec3_add(v1, v2) == [5.0, 7.0, 9.0]
    assert vec3_sub(v2, v1) == [3.0, 3.0, 3.0]
    assert vec3_scale(v1, 2.0) == [2.0, 4.0, 6.0]
    assert vec3_dot(v1, v2) == 32.0

    # Cross product adhering to right-handed basis: +X cross +Y = +Z
    x_axis = [1.0, 0.0, 0.0]
    y_axis = [0.0, 1.0, 0.0]
    z_axis = vec3_cross(x_axis, y_axis)
    assert z_axis == [0.0, 0.0, 1.0]

    assert math.isclose(vec3_length([3.0, 4.0, 0.0]), 5.0)
    assert vec3_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]

    # Invariant [I5] coplanar decal displacement
    normal = [0.0, 1.0, 0.0]
    displaced = vec3_displace(v1, normal, eps=0.001)
    assert math.isclose(displaced[0], 1.0)
    assert math.isclose(displaced[1], 2.001)
    assert math.isclose(displaced[2], 3.0)


def test_quaternion_normalization_and_direction_cosines() -> None:
    """Verify unit quaternion calculation and direction cosine decomposition."""
    q_unnorm = [0.0, 0.0, 0.0, 2.0]
    q_norm = quat_normalize(q_unnorm)
    assert q_norm == [0.0, 0.0, 0.0, 1.0]
    assert quat_norm(q_norm) == 1.0
    assert quat_norm_diff(q_norm) < 1e-6

    # Identity rotation from direction cosines
    identity_mat = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    q_ident = quat_from_direction_cosines(identity_mat)
    assert math.isclose(q_ident[0], 0.0, abs_tol=1e-5)
    assert math.isclose(q_ident[1], 0.0, abs_tol=1e-5)
    assert math.isclose(q_ident[2], 0.0, abs_tol=1e-5)
    assert math.isclose(q_ident[3], 1.0, abs_tol=1e-5)
    assert quat_norm_diff(q_ident) < 1e-4

    # 90 deg rotation around Y axis
    rot_y_90 = [
        0.0,
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        -1.0,
        0.0,
        0.0,
    ]
    q_y = quat_from_direction_cosines(rot_y_90)
    assert quat_norm_diff(q_y) < 1e-4

    # Euler rotation to quaternion
    q_euler = quat_from_euler(yaw=0.0, pitch=math.radians(10.0), roll=0.0)
    assert quat_norm_diff(q_euler) < 1e-4


def test_quat_from_euler_invariant_i1_axes() -> None:
    """Verify quat_from_euler maps pitch to X, yaw to Y, and roll to Z per Invariant [I1]."""
    angle = math.radians(30.0)

    # 1. Pitch alone (+X Right): +Y rotates toward -Z, X remains unchanged
    q_pitch = quat_from_euler(yaw=0.0, pitch=angle, roll=0.0)
    assert quat_norm_diff(q_pitch) < 1e-6
    m_pitch = compute_world_matrix([0.0, 0.0, 0.0], q_pitch)
    col0_x = m_pitch[0:3]
    col1_y = m_pitch[4:7]
    assert pytest.approx(col0_x, abs=1e-5) == [1.0, 0.0, 0.0]
    assert pytest.approx(col1_y, abs=1e-5) == [0.0, math.cos(angle), -math.sin(angle)]

    # 2. Yaw alone (+Y Up): +X rotates toward +Z, Y remains unchanged
    q_yaw = quat_from_euler(yaw=angle, pitch=0.0, roll=0.0)
    assert quat_norm_diff(q_yaw) < 1e-6
    m_yaw = compute_world_matrix([0.0, 0.0, 0.0], q_yaw)
    col0_x = m_yaw[0:3]
    col1_y = m_yaw[4:7]
    assert pytest.approx(col1_y, abs=1e-5) == [0.0, 1.0, 0.0]
    assert pytest.approx(col0_x, abs=1e-5) == [math.cos(angle), 0.0, math.sin(angle)]

    # 3. Roll alone (+Z Backward): +X rotates toward +Y, Z remains unchanged
    q_roll = quat_from_euler(yaw=0.0, pitch=0.0, roll=angle)
    assert quat_norm_diff(q_roll) < 1e-6
    m_roll = compute_world_matrix([0.0, 0.0, 0.0], q_roll)
    col0_x = m_roll[0:3]
    col2_z = m_roll[8:11]
    assert pytest.approx(col2_z, abs=1e-5) == [0.0, 0.0, 1.0]
    assert pytest.approx(col0_x, abs=1e-5) == [math.cos(angle), math.sin(angle), 0.0]

    # 4. Identity
    q_id = quat_from_euler(0.0, 0.0, 0.0)
    assert q_id == [0.0, 0.0, 0.0, 1.0]


def test_compute_world_matrix() -> None:
    """Verify column-major 4x4 matrix computation matching Rust contract."""
    pos = [10.0, 20.0, 30.0]
    quat = [0.0, 0.0, 0.0, 1.0]  # Identity
    m = compute_world_matrix(pos, quat)
    expected = [
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
    assert m == expected


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
    cam_restored = CameraTransform.from_dict(cam_dict)
    assert cam_restored == cam

    actor = ActorTransform(
        actor_id=42,
        model_name="FOKKER",
        world_matrix=[1.0] * 16,
        rotation_quat=[0.0, 0.0, 0.0, 1.0],
        position_meters=[10.0, 20.0, 30.0],
        state_mask=0x0001,
        joint_angles_bam=[(0, 0x4000)],
    )
    actor_dict = actor.to_dict()
    actor_restored = ActorTransform.from_dict(actor_dict)
    assert actor_restored == actor
    assert actor.compute_world_matrix() == compute_world_matrix(
        actor.position_meters, actor.rotation_quat
    )

    cue = AudioCue(tick=10, sample_name="ENGINE.VOC", volume=0.8, pan=-0.5)
    cue_dict = cue.to_dict()
    assert AudioCue.from_dict(cue_dict) == cue

    record = TrajectoryRecord(
        tick=10,
        camera=cam,
        actors=[actor],
        audio_cues=[cue],
    )
    rec_dict = record.to_dict()
    assert TrajectoryRecord.from_dict(rec_dict) == record

    header = SceneHeader(
        film_name="INTRO",
        tick_rate_hz=20,
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
    cap_dict = capture.to_dict()
    assert FilmCapture.from_dict(cap_dict) == capture


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
# 3. Transport Unit Tests
# ==============================================================================


def test_mock_transport_operations() -> None:
    """Verify in-memory virtual RAM reading, writing, and debugger commands."""
    mock = MockTransport()
    assert mock.is_connected()

    # Test PING
    assert mock.send_command("PING") == ["PONG"]

    # Test Memory SM and D
    mock.send_command("SM 0D51:0100 12 34 AB CD")
    data = mock.read_bytes(0x0D51, 0x0100, 4)
    assert data == bytes([0x12, 0x34, 0xAB, 0xCD])

    dump_lines = mock.send_command("D 0D51:0100 4")
    assert len(dump_lines) >= 1
    assert "0D51:0100" in dump_lines[0]
    assert "12 34 AB CD" in dump_lines[0]

    # Test Breakpoint commands
    mock.send_command("BP 0D51:0C5E")
    assert "0D51:0C5E" in mock.breakpoints
    mock.send_command("BPIO 03DA")
    assert "03DA" in mock.io_breakpoints
    mock.send_command("BPDEL *")
    assert len(mock.breakpoints) == 0

    # Test RUN advancing tick
    assert mock.current_tick == 0
    mock.send_command("RUN")
    assert mock.current_tick == 1
    assert mock.read_u16(0x0D51, 0x0C60) == 1

    mock.close()
    assert not mock.is_connected()
    with pytest.raises(ConnectionError):
        mock.send_command("PING")


def test_live_socket_transport_wire_codec() -> None:
    """Verify wire framing protocol codec for LiveSocketTransport."""
    # Spin up mock TCP server on ephemeral port
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server_thread_fn() -> None:
        conn, _ = server_sock.accept()
        buf = ""
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break
            buf += chunk.decode("utf-8")
            if "\n" in buf:
                line, buf = buf.split("\n", 1)
                tokens = line.strip().split()
                if len(tokens) >= 3 and tokens[0] == "REQ":
                    req_id = tokens[1]
                    cmd = tokens[2]
                    if cmd == "PING":
                        conn.sendall(f"BEGIN {req_id} OK\nPONG\nEND {req_id}\n".encode())
                    elif cmd == "ERRTEST":
                        conn.sendall(f"BEGIN {req_id} ERR\nSyntax error\nEND {req_id}\n".encode())
        conn.close()
        server_sock.close()

    th = threading.Thread(target=server_thread_fn, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=2.0)
    transport.connect()
    assert transport.is_connected()

    # Success case
    resp = transport.send_command("PING")
    assert resp == ["PONG"]

    # Error case
    with pytest.raises(RuntimeError) as exc_info:
        transport.send_command("ERRTEST")
    assert "Syntax error" in str(exc_info.value)

    transport.close()
    assert not transport.is_connected()


def test_live_socket_request_id_collision_rejected() -> None:
    """Verify that BEGIN 10 OK is rejected when expecting BEGIN 1."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server_thread() -> None:
        conn, _ = server_sock.accept()
        _ = conn.recv(1024)
        conn.sendall(b"BEGIN 10 OK\nDATA\nEND 10\n")
        conn.close()
        server_sock.close()

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()
    with pytest.raises(RuntimeError) as exc_info:
        transport.send_command("PING")
    assert "Unexpected response header" in str(exc_info.value)
    transport.close()


def test_live_socket_buffer_flush_on_error() -> None:
    """Verify that after a malformed header, residual buffer bytes are flushed."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server_thread() -> None:
        conn, _ = server_sock.accept()
        _ = conn.recv(1024)
        conn.sendall(b"GARBAGE HEADER 1\nGARBAGE LINE 2\n")
        _ = conn.recv(1024)
        conn.sendall(b"BEGIN 2 OK\nPONG\nEND 2\n")
        conn.close()
        server_sock.close()

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()
    with pytest.raises(RuntimeError):
        transport.send_command("CMD1")

    # Second command should succeed because buffer was cleared
    lines = transport.send_command("CMD2")
    assert lines == ["PONG"]
    transport.close()


def test_live_socket_disconnect_cleanup() -> None:
    """Verify that premature disconnection marks transport as disconnected."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server_thread() -> None:
        conn, _ = server_sock.accept()
        _ = conn.recv(1024)
        # Drop connection abruptly
        conn.close()
        server_sock.close()

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()
    with pytest.raises(ConnectionResetError):
        transport.send_command("PING")
    assert not transport.is_connected()
    transport.close()


# ==============================================================================
# 4. Client Unit Tests
# ==============================================================================


def test_tac_client_memory_helpers() -> None:
    """Verify TacClient typed reading and writing helpers against MockTransport."""
    mock = MockTransport()
    with TacClient(mock) as client:
        assert client.ping() is True

        # Test write and read types
        client.write_memory("0D51:0200", bytes([0x78]))
        assert client.read_u8("0D51:0200") == 0x78

        client.write_u16("0D51:0202", 0x1234)
        assert client.read_u16("0D51:0202") == 0x1234

        # Fixed point 16.16 (e.g. 10.5 meters = 10 * 65536 + 32768 = 688128)
        client.write_memory("0D51:0204", (688128).to_bytes(4, "little", signed=True))
        assert math.isclose(client.read_fixed16_16("0D51:0204"), 10.5, abs_tol=1e-5)

        # Null-terminated string reading
        client.write_memory("0D51:0208", b"FOKKER\x00PADDING")
        assert client.read_string("0D51:0208") == "FOKKER"

        # Breakpoint helpers
        client.set_breakpoint("0D51:0C5E")
        assert "0D51:0C5E" in mock.breakpoints
        client.delete_breakpoints()
        assert len(mock.breakpoints) == 0


# ==============================================================================
# 5. BDA Injector Unit Tests
# ==============================================================================


def test_bda_char_to_key_mapping() -> None:
    """Verify character to BIOS scan code and ASCII mapping."""
    ascii_code, scan_code = char_to_key("i")
    assert ascii_code == ord("i")
    assert scan_code == 0x17

    ascii_code, scan_code = char_to_key("c")
    assert ascii_code == ord("c")
    assert scan_code == 0x2E

    with pytest.raises(ValueError, match="char_to_key expects single character"):
        char_to_key("multi")


def test_bda_keystroke_injection_and_modal_navigation() -> None:
    """Verify keystroke injection into BIOS Data Area circular ring buffer."""
    mock = MockTransport()
    client = TacClient(mock)

    # Initial state check
    head, tail = BdaInjector.get_buffer_state(client)
    assert head == 0x001E
    assert tail == 0x001E

    # Navigate modal dialog to INTRO.FLM ([Enter, 'i', Enter])
    BdaInjector.navigate_modal_dialog(client, "intro")

    new_head, new_tail = BdaInjector.get_buffer_state(client)
    assert new_head == 0x001E
    # 3 keystrokes * 2 bytes = 6 bytes advanced -> tail = 0x0024
    assert new_tail == 0x0024

    # Verify injected buffer bytes at 0040:001E
    raw_bda = client.read_memory("0040:001E", 6)
    # [Enter (0D 1C), 'i' (69 17), Enter (0D 1C)]
    expected = bytes([0x0D, 0x1C, 0x69, 0x17, 0x0D, 0x1C])
    assert raw_bda == expected


def test_bda_ring_buffer_wrapping() -> None:
    """Verify circular ring buffer wrapping when tail advances past 0040:003E."""
    mock = MockTransport()
    client = TacClient(mock)

    # Position tail at 0x003C (last 2-byte slot in buffer before wrap)
    # Position head at 0x0028 so there is plenty of space across the wrap
    client.write_u16("0040:001A", 0x0028)
    client.write_u16("0040:001C", 0x003C)

    # Inject 2 keys: first writes to 0x003C, second wraps to 0x001E
    keys = [KEY_ENTER, char_to_key("c")]
    BdaInjector.inject_keys(client, keys)

    _, new_tail = BdaInjector.get_buffer_state(client)
    # First key advanced tail from 0x003C to 0x001E, second key advanced to 0x0020
    assert new_tail == 0x0020


def test_bda_buffer_overflow() -> None:
    """Verify exception raised when injecting more than buffer capacity."""
    mock = MockTransport()
    client = TacClient(mock)

    # Try injecting 16 keys into empty buffer (capacity is 15 keys)
    keys = [KEY_ENTER] * 16
    with pytest.raises(BufferError):
        BdaInjector.inject_keys(client, keys)


def test_bda_odd_tail_pointer_normalized() -> None:
    """Verify that odd tail pointer 0x003D is normalized and does not touch 0040:003E."""
    mock = MockTransport()
    client = TacClient(mock)
    client.write_u16("0040:001A", 0x0024)
    client.write_u16("0040:001C", 0x003D)
    client.write_memory("0040:003E", b"\x00\x00")

    BdaInjector.inject_keys(client, [KEY_ENTER])
    # 0040:003E must remain 0x00 (Floppy status protected)
    floppy_byte = client.read_memory("0040:003E", 1)
    assert floppy_byte == b"\x00"

    # Tail should have reset from 0x003D to 0x001E, then advanced by 2 to 0x0020
    _, tail = BdaInjector.get_buffer_state(client)
    assert tail == 0x0020


def test_bda_atomic_overflow_preserves_memory() -> None:
    """Verify that overflowing BDA capacity does not leave partial writes in RAM."""
    mock = MockTransport()
    client = TacClient(mock)
    # Head at 0x0024, tail at 0x0020 -> exactly 1 slot available
    client.write_u16("0040:001A", 0x0024)
    client.write_u16("0040:001C", 0x0020)
    client.write_memory("0040:0020", b"\x00\x00")

    # Request 2 keys -> overflow
    with pytest.raises(BufferError):
        BdaInjector.inject_keys(client, [char_to_key("a"), char_to_key("b")])

    # Memory at 0040:0020 must remain unmodified
    assert client.read_memory("0040:0020", 2) == b"\x00\x00"
    _, tail = BdaInjector.get_buffer_state(client)
    assert tail == 0x0020


def test_bda_empty_film_prefix_defaults() -> None:
    """Verify that navigate_modal_dialog handles empty prefix without crashing."""
    mock = MockTransport()
    client = TacClient(mock)
    BdaInjector.navigate_modal_dialog(client, "")
    # Injected keystrokes should be [KEY_ENTER, 'i', KEY_ENTER]
    raw = client.read_memory("0040:001E", 6)
    assert raw == bytes([0x0D, 0x1C, 0x69, 0x17, 0x0D, 0x1C])


def test_bda_punctuation_scan_codes() -> None:
    """Verify scan codes for filename punctuation."""
    assert char_to_key(".") == (0x2E, 0x34)
    assert char_to_key("-") == (0x2D, 0x0C)
    assert char_to_key("_") == (0x5F, 0x0C)


# ==============================================================================
# 6. V-Sync Trap & Deduplication Unit Tests
# ==============================================================================


def test_vsync_trap_tick_deduplication() -> None:
    """Verify V-Sync trap deduplication downsampling 70 Hz frames to 20/30 Hz ticks."""
    assert PORT_VGA_STATUS == 0x03DA
    assert math.isclose(VGA_REFRESH_HZ, 70.087, rel_tol=1e-3)

    mock = MockTransport()
    client = TacClient(mock)
    trap = VsyncTrap(post_retrace_bp="0D51:0C5E", tick_addr="0D51:0C60")

    # Custom handler simulating 70 Hz VGA retrace:
    # Sim tick advances only once every 3 RUN calls!
    run_count = 0

    def mock_run_handler(_args: list[str]) -> list[str]:
        nonlocal run_count
        run_count += 1
        sim_tick = run_count // 3
        mock.set_sim_tick(sim_tick)
        return ["Breakpoint hit"]

    mock.register_handler("RUN", mock_run_handler)

    trap.arm(client)
    assert "0D51:0C5E" in mock.breakpoints

    # First call: steps through until sim tick is observed (tick 0)
    tick0 = trap.wait_next_sim_tick(client)
    assert tick0 == 0
    assert trap.captured_frames == 1

    # Second call: steps through duplicate 70 Hz frames until sim tick advances to 1
    tick1 = trap.wait_next_sim_tick(client)
    assert tick1 == 1
    assert trap.captured_frames == 2
    assert trap.duplicate_frames_dropped > 0

    trap.disarm(client)
    assert len(mock.breakpoints) == 0


def test_vsync_trap_timeout() -> None:
    """Verify VsyncTrap raises TimeoutError if simulation tick fails to advance."""
    mock = MockTransport()
    client = TacClient(mock)
    trap = VsyncTrap(max_spins_per_tick=5)
    # Set last_captured_tick to 0 so wait_next_sim_tick requires tick > 0
    trap.last_captured_tick = 0

    # Freeze tick counter at 0
    mock.register_handler("RUN", lambda _args: ["Breakpoint hit"])

    with pytest.raises(TimeoutError):
        trap.wait_next_sim_tick(client)


# ==============================================================================
# 7. Streamer & Golden Oracle Unit Tests
# ==============================================================================


def test_decode_camera_from_memory_direct() -> None:
    """Verify direct memory decoding of 32-byte camera rig structure [MEM-CAMERA-RIG]."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    eye_raw = [round(x * 65536.0) for x in [10.0, 20.0, 30.0]]
    tgt_raw = [round(x * 65536.0) for x in [0.0, 5.0, 0.0]]
    focal_u16 = 290  # ~45 deg FOV
    roll_bam = 0x2000  # 45 deg roll
    mode_id = 1
    raw_cam = struct.pack(
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
    mock.write_bytes(0x0D51, 0x0C10, raw_cam)

    cam, decoded_mode = streamer.decode_camera_from_memory("0D51:0C10")
    assert pytest.approx(cam.eye, abs=1e-4) == [10.0, 20.0, 30.0]
    assert pytest.approx(cam.target, abs=1e-4) == [0.0, 5.0, 0.0]
    assert math.isclose(cam.fov_degrees, focal_to_fov_y(290.0), abs_tol=1e-4)
    assert math.isclose(cam.roll_radians, bam_to_radians(0x2000), abs_tol=1e-4)
    assert decoded_mode == 1
    assert cam.cut_from_previous is False

    # Test camera cut detection on distance > 50 m
    cam2, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=[100.0, 20.0, 30.0])
    assert cam2.cut_from_previous is True

    # Test camera cut detection on mode change
    cam3, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam.eye, last_mode=2)
    assert cam3.cut_from_previous is True


def test_decode_actor_from_memory_direct() -> None:
    """Verify direct memory decoding of 64-byte actor record [MEM-ACTOR-TABLE]."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    pos_raw = [round(x * 65536.0) for x in [5.0, 15.0, 25.0]]
    name_bytes = b"FOKKER\x00\x00"
    rot = quat_normalize([0.0, 0.0, 0.0, 1.0])
    raw_header = struct.pack(
        "<I8s3i4fHH",
        1,
        name_bytes,
        pos_raw[0],
        pos_raw[1],
        pos_raw[2],
        rot[0],
        rot[1],
        rot[2],
        rot[3],
        1,  # state_mask
        1,  # joint_count
    )
    joints_buf = bytearray(16)
    struct.pack_into("<HH", joints_buf, 0, 0, 0x4000)
    next_ptr = struct.pack("<HH", 0, 0)
    mock.write_bytes(0x0D51, 0x0CA0, raw_header + joints_buf + next_ptr)

    actor, next_addr = streamer.decode_actor_from_memory("0D51:0CA0")
    assert actor.actor_id == 1
    assert actor.model_name == "FOKKER"
    assert pytest.approx(actor.position_meters, abs=1e-4) == [5.0, 15.0, 25.0]
    assert quat_norm_diff(actor.rotation_quat) < 1e-6
    assert actor.state_mask == 1
    assert actor.joint_angles_bam == [(0, 0x4000)]
    assert actor.world_matrix == actor.compute_world_matrix()
    assert next_addr is None


def test_decode_actors_linked_list() -> None:
    """Verify traversal of chained actors starting from dynamic heap pointer [MEM-ACTOR-TABLE]."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Actor 1 at 0D51:0CA0 points to 0D51:0CE0
    name1 = b"FOKKER\x00\x00"
    raw_act1 = (
        struct.pack(
            "<I8s3i4fHH",
            1,
            name1,
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
        + bytearray(16)
        + struct.pack("<HH", 0x0CE0, 0x0D51)
    )
    mock.write_bytes(0x0D51, 0x0CA0, raw_act1)

    # Actor 2 at 0D51:0CE0 is terminal (next pointer 0x0000:0x0000)
    name2 = b"TARGET\x00\x00"
    raw_act2 = (
        struct.pack(
            "<I8s3i4fHH",
            2,
            name2,
            655360,
            0,
            0,
            0.0,
            0.0,
            0.0,
            1.0,
            1,
            0,
        )
        + bytearray(16)
        + struct.pack("<HH", 0x0000, 0x0000)
    )
    mock.write_bytes(0x0D51, 0x0CE0, raw_act2)

    # Set heap pointer at 0D51:0C50 -> 0D51:0CA0
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
    """Verify exact match for initial ticks captured from memory against tests/fixtures/oracle_intro_trajectory.json."""
    mock = MockTransport()
    mock.load_trajectory(generate_intro_trajectory(2))
    client = TacClient(mock)
    trap = VsyncTrap()
    streamer = TrajectoryStreamer(client, trap)
    records = streamer.capture_ticks(2)

    assert FIXTURE_PATH.exists()
    baseline = load_trajectory_records(FIXTURE_PATH)

    # Tick 0
    assert records[0].tick == 0
    assert pytest.approx(records[0].camera.eye, abs=1e-4) == baseline[0].camera.eye
    assert pytest.approx(records[0].camera.target, abs=1e-4) == baseline[0].camera.target
    assert (
        pytest.approx(records[0].actors[0].position_meters, abs=1e-4)
        == baseline[0].actors[0].position_meters
    )
    assert (
        pytest.approx(records[0].actors[0].world_matrix, abs=1e-4)
        == baseline[0].actors[0].world_matrix
    )
    assert len(records[0].audio_cues) == 1
    assert records[0].audio_cues[0].sample_name == "ENGINE.VOC"

    # Tick 1
    assert records[1].tick == 1
    assert pytest.approx(records[1].camera.eye, abs=1e-4) == baseline[1].camera.eye
    assert (
        pytest.approx(records[1].actors[0].position_meters, abs=1e-4)
        == baseline[1].actors[0].position_meters
    )
    assert (
        pytest.approx(records[1].actors[0].world_matrix, abs=1e-4)
        == baseline[1].actors[0].world_matrix
    )
    assert len(records[1].audio_cues) == 0


def test_streamer_quaternion_normalization_and_zero_matrix_tearing() -> None:
    """Verify | ||q|| - 1.0 | < 1e-4 and zero matrix tearing across 600 ticks captured from memory."""
    mock = MockTransport()
    client = TacClient(mock)
    trap = VsyncTrap()
    streamer = TrajectoryStreamer(client, trap)
    records = streamer.capture_ticks(600)

    assert len(records) == 600
    for rec in records:
        for actor in rec.actors:
            # Quaternion invariant
            diff = quat_norm_diff(actor.rotation_quat)
            assert diff < 1e-4, f"Quaternion norm error at tick {rec.tick}: {diff}"

            # Zero matrix tearing: world matrix matches position and quaternion
            expected_matrix = actor.compute_world_matrix()
            for m_act, m_exp in zip(actor.world_matrix, expected_matrix, strict=True):
                assert math.isclose(m_act, m_exp, abs_tol=1e-4), (
                    f"Matrix tearing at tick {rec.tick}"
                )


def test_streamer_position_rmse_threshold() -> None:
    """Verify position RMSE <= 0.01 m against baseline fixture for memory capture."""
    mock = MockTransport()
    client = TacClient(mock)
    trap = VsyncTrap()
    streamer = TrajectoryStreamer(client, trap)
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

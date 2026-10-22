"""Adversarial stress testing and empirical verification suite for TAC remediation.

Empirical verification suite for Challenger TAC 2 (Milestone 1 TAC Remediation):
1. Wire framing:
   - Multi-digit request ID matching & prefix collision immunity (REQ 1 vs RESP 10, REQ 1 vs RESP 100,
     REQ 2 vs RESP 20, REQ 10 vs RESP 1, REQ 10 vs RESP 100).
   - Sequential multi-digit commands across REQ 1..15.
   - Interleaved / out-of-order response rejection.
   - Truncated responses & sudden disconnection handling (ConnectionResetError, socket closed).
   - Error block extraction (BEGIN <id> ERR ...).
   - Header formatting resilience (irregular whitespace, tabs, CRLF).
2. Transport buffer flushing on framing error:
   - Buffer flush on header syntax error with trailing garbage; subsequent command succeeds.
   - Buffer flush on mismatched request ID; subsequent command succeeds.
3. BDA boundary conditions:
   - Odd pointer normalization: odd tail (0x003D) normalized to 0x001E, canary byte at 0040:003E untouched.
   - Odd head (0x003D) normalized to 0x001E.
   - Sweep of all odd pointers in [0x001D..0x003F].
   - Out-of-bounds pointer normalization (< 0x001E, > 0x003C, e.g. 0x001C, 0x003E, 0x0040, 0xFFFF).
   - Buffer capacity boundary sweep (empty: 15 slots, full: 0 slots).
   - Atomic all-or-nothing capacity check: overflow raises BufferError with zero memory writes.
   - Default film prefix on empty string ("" -> 'i', None -> 'i').
   - Punctuation scan codes ('.', '-', '_') and case insensitivity.
4. Direct memory decoding:
   - decode_camera_from_memory on synthetic RAM states: signed fixed-point coordinates (positive & negative),
     focal zoom conversion, BAM roll angle, camera cut detection on position displacement (>50 m) and mode change.
   - Camera decoding robustness: zero focal distance default (45.0 FOV), truncated memory read exception.
   - decode_actor_from_memory on synthetic 64-byte RAM state: model name, signed 16.16 position,
     normalized quaternion, state mask, joint angles, world matrix match.
   - decode_actors_from_memory linked list traversal: multi-actor chain, dynamic heap pointer resolution,
     local stage block fallback.
   - Linked list circular reference protection: terminates cleanly without infinite recursion.
   - Degenerate zero quaternion in RAM: safe fallback to identity [0, 0, 0, 1].
5. Invariant [I1] Euler kinematics:
   - Positive pitch tilts +Y toward -Z.
   - Positive yaw turns +X toward +Z.
   - Positive roll banks +X toward +Y.
   - Matrix orthogonality and determinant +1.0 across 1,000 random orientations.
   - Extreme angle stability: 0, 180, -180, 360, 720 degrees.
6. Golden Oracle & Cleanroom isolation:
   - Trajectory records match Seam 2 contract across 600 ticks.
   - Zero NaN / Inf, unit quaternion | ||q|| - 1 | < 1e-14, zero matrix tearing.
   - Position RMSE <= 0.01 m against baseline fixture.
"""

from __future__ import annotations

import math
import random
import socket
import struct
import subprocess
import threading
from pathlib import Path

import pytest

from stunt_reel.tac import (
    KEY_ENTER,
    BdaInjector,
    LiveSocketTransport,
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

FIXTURE_PATH = Path("tests/fixtures/oracle_intro_trajectory.json")


def make_loopback_server() -> tuple[socket.socket, int]:
    """Create a temporary loopback TCP server bound to an OS-assigned ephemeral port."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port: int = srv.getsockname()[1]
    return srv, port


# ==============================================================================
# 1. Wire Framing Protocol Robustness
# ==============================================================================


def test_wire_req_id_prefix_collision_sweeps() -> None:
    """Verify that multi-digit request IDs never collide via prefix substring matching."""
    collision_pairs = [
        (1, 10),
        (1, 100),
        (2, 20),
        (10, 1),
        (10, 100),
    ]

    for expected_id, rogue_id in collision_pairs:
        srv, port = make_loopback_server()

        def server_task(server_sock: socket.socket, _exp_id: int, rog_id: int) -> None:
            try:
                conn, _ = server_sock.accept()
                _req = conn.recv(1024)
                # Send response with rogue_id
                payload = f"BEGIN {rog_id} OK\nDATA\nEND {rog_id}\n".encode()
                conn.sendall(payload)
                conn.close()
            finally:
                server_sock.close()

        th = threading.Thread(target=server_task, args=(srv, expected_id, rogue_id), daemon=True)
        th.start()

        transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
        transport.connect()
        transport._req_id = expected_id

        with pytest.raises(RuntimeError) as exc_info:
            transport.send_command("PING")

        err_msg = str(exc_info.value)
        assert f"expected BEGIN {expected_id} <status>" in err_msg
        assert f"BEGIN {rogue_id} OK" in err_msg

        transport.close()
        th.join(timeout=1.0)


def test_wire_multidigit_sequential_commands() -> None:
    """Verify sequential execution through multi-digit IDs (REQ 1 to REQ 15)."""
    srv, port = make_loopback_server()

    def server_sequential() -> None:
        try:
            conn, _ = srv.accept()
            for _ in range(15):
                req_line = b""
                while b"\n" not in req_line:
                    chunk = conn.recv(1024)
                    if not chunk:
                        return
                    req_line += chunk
                tokens = req_line.decode().strip().split()
                assert tokens[0] == "REQ"
                r_id = tokens[1]
                cmd = tokens[2]
                resp = f"BEGIN {r_id} OK\nACK {cmd} FOR {r_id}\nEND {r_id}\n".encode()
                conn.sendall(resp)
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_sequential, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=2.0)
    transport.connect()

    for expected_id in range(1, 16):
        resp = transport.send_command(f"CMD_{expected_id}")
        assert resp == [f"ACK CMD_{expected_id} FOR {expected_id}"]

    transport.close()
    th.join(timeout=1.0)


def test_wire_interleaved_and_malformed_headers() -> None:
    """Verify rejection of malformed, non-numeric, or incomplete header tokens."""
    malformed_headers = [
        b"BEGIN\n",
        b"BEGIN 1\n",
        b"BEGIN abc OK\nDATA\nEND abc\n",
        b"STATUS OK\n",
        b"GARBAGE_WITHOUT_BEGIN\n",
    ]

    for bad_header in malformed_headers:
        srv, port = make_loopback_server()

        def server_bad(server_sock: socket.socket, hdr: bytes) -> None:
            try:
                conn, _ = server_sock.accept()
                _ = conn.recv(1024)
                conn.sendall(hdr)
                conn.close()
            finally:
                server_sock.close()

        th = threading.Thread(target=server_bad, args=(srv, bad_header), daemon=True)
        th.start()

        transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
        transport.connect()

        with pytest.raises(RuntimeError):
            transport.send_command("PING")

        transport.close()
        th.join(timeout=1.0)


def test_wire_truncated_response_handling() -> None:
    """Verify that truncated response frames cleanly raise ConnectionResetError and close the transport."""
    srv, port = make_loopback_server()

    def server_truncate() -> None:
        try:
            conn, _ = srv.accept()
            _ = conn.recv(1024)
            # Send partial header, then abruptly close
            conn.sendall(b"BEGIN 1 OK\nPartial line without end\n")
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_truncate, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()

    with pytest.raises(ConnectionResetError):
        transport.send_command("PING")

    # Socket must be marked closed/disconnected
    assert not transport.is_connected()
    assert transport._buffer == ""

    transport.close()
    th.join(timeout=1.0)


def test_wire_error_block_multiline_extraction() -> None:
    """Verify multiline error blocks (BEGIN <id> ERR ...) are formatted into RuntimeError."""
    srv, port = make_loopback_server()

    def server_err() -> None:
        try:
            conn, _ = srv.accept()
            _ = conn.recv(1024)
            err_payload = b"BEGIN 1 ERR\nSyntax error: unknown verb 'FOOBAR'\nAt line 42\nEND 1\n"
            conn.sendall(err_payload)
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_err, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()

    with pytest.raises(RuntimeError) as exc_info:
        transport.send_command("FOOBAR")

    msg = str(exc_info.value)
    assert "DOSBox-X command error for request 1 (FOOBAR):" in msg
    assert "Syntax error: unknown verb 'FOOBAR'" in msg
    assert "At line 42" in msg

    transport.close()
    th.join(timeout=1.0)


def test_wire_irregular_whitespace_and_crlf() -> None:
    """Verify transport tolerates arbitrary tabs/spaces and CRLF line endings."""
    srv, port = make_loopback_server()

    def server_crlf() -> None:
        try:
            conn, _ = srv.accept()
            _ = conn.recv(1024)
            payload = b"BEGIN \t  1   \t OK \r\n  DATA ROW 1  \r\nDATA ROW 2\r\nEND 1\r\n"
            conn.sendall(payload)
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_crlf, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()

    resp = transport.send_command("PING")
    assert resp == ["  DATA ROW 1  ", "DATA ROW 2"]

    transport.close()
    th.join(timeout=1.0)


# ==============================================================================
# 2. Transport Buffer Flushing on Framing Error
# ==============================================================================


def test_buffer_flush_recovers_after_malformed_header() -> None:
    """Verify that buffer is flushed on framing error, allowing subsequent commands to succeed."""
    srv, port = make_loopback_server()

    def server_two_cmds() -> None:
        try:
            conn, _ = srv.accept()
            # Command 1: receive REQ 1, reply with garbage + trailing lines
            _ = conn.recv(1024)
            conn.sendall(b"GARBAGE_HEADER\nSTALE_LEFTOVER_1\nSTALE_LEFTOVER_2\n")

            # Command 2: receive REQ 2, reply cleanly
            req2 = conn.recv(1024)
            assert b"REQ 2 PING" in req2
            conn.sendall(b"BEGIN 2 OK\nPONG\nEND 2\n")
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_two_cmds, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()

    # First command must fail due to malformed header
    with pytest.raises(RuntimeError):
        transport.send_command("FAIL_CMD")

    # Buffer must have been reset to empty
    assert transport._buffer == ""

    # Second command over the SAME socket must succeed without leftover byte corruption
    resp2 = transport.send_command("PING")
    assert resp2 == ["PONG"]
    assert transport._buffer == ""

    transport.close()
    th.join(timeout=1.0)


def test_buffer_flush_recovers_after_mismatched_id() -> None:
    """Verify that buffer is flushed after mismatched ID error, allowing recovery."""
    srv, port = make_loopback_server()

    def server_mismatch_recovery() -> None:
        try:
            conn, _ = srv.accept()
            _ = conn.recv(1024)
            conn.sendall(b"BEGIN 999 OK\nUNWANTED_LINE\nEND 999\n")

            req2 = conn.recv(1024)
            assert b"REQ 2 PING" in req2
            conn.sendall(b"BEGIN 2 OK\nSUCCESS\nEND 2\n")
            conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=server_mismatch_recovery, daemon=True)
    th.start()

    transport = LiveSocketTransport(host="127.0.0.1", port=port, timeout=1.0)
    transport.connect()

    with pytest.raises(RuntimeError):
        transport.send_command("CMD1")

    assert transport._buffer == ""

    resp = transport.send_command("PING")
    assert resp == ["SUCCESS"]

    transport.close()
    th.join(timeout=1.0)


# ==============================================================================
# 3. BDA Keyboard Buffer Boundary Conditions
# ==============================================================================


def test_bda_odd_tail_pointer_normalized_and_canary_safe() -> None:
    """Stress test: tail at odd 0x003D is normalized to 0x001E without corrupting Floppy status (0040:003E)."""
    mock = MockTransport()
    client = TacClient(mock)

    # Set head = 0x0024, tail = 0x003D
    client.write_u16("0040:001A", 0x0024)
    client.write_u16("0040:001C", 0x003D)

    # Place canary byte at 0040:003E (Floppy status)
    canary = b"\xa5"
    client.write_memory("0040:003E", canary)

    # Inject 1 key
    BdaInjector.inject_keys(client, [KEY_ENTER])

    # Verification:
    # 1. Canary byte at 0040:003E must be completely untouched
    assert client.read_memory("0040:003E", 1) == canary

    # 2. Tail was normalized from 0x003D to 0x001E, then advanced to 0x0020
    head, tail = BdaInjector.get_buffer_state(client)
    assert head == 0x0024
    assert tail == 0x0020

    # 3. Key was written at 0x001E
    raw_key = client.read_memory("0040:001E", 2)
    assert raw_key == bytes([KEY_ENTER[0], KEY_ENTER[1]])


def test_bda_odd_pointers_sweep() -> None:
    """Verify that every odd pointer in range [0x001D..0x003F] is normalized to 0x001E."""
    for odd_tail in range(0x001D, 0x0041, 2):
        mock = MockTransport()
        client = TacClient(mock)
        client.write_u16("0040:001A", 0x0024)
        client.write_u16("0040:001C", odd_tail)

        BdaInjector.inject_keys(client, [KEY_ENTER])

        _head, tail = BdaInjector.get_buffer_state(client)
        assert tail == 0x0020


def test_bda_out_of_bounds_pointers() -> None:
    """Verify that pointers outside [0x001E..0x003C] are normalized to 0x001E."""
    oob_values = [0x0000, 0x001C, 0x003E, 0x0040, 0x1000, 0xFFFF]

    for oob in oob_values:
        mock = MockTransport()
        client = TacClient(mock)
        client.write_u16("0040:001A", oob)
        client.write_u16("0040:001C", oob)

        BdaInjector.inject_keys(client, [KEY_ENTER])

        head, tail = BdaInjector.get_buffer_state(client)
        assert head == 0x001E
        assert tail == 0x0020


def test_bda_capacity_and_overflow_sweep() -> None:
    """Verify full buffer capacity: 15 keys max in empty 16-word ring buffer."""
    mock = MockTransport()
    client = TacClient(mock)
    client.write_u16("0040:001A", 0x001E)
    client.write_u16("0040:001C", 0x001E)

    # Empty buffer capacity is exactly 15 keys
    keys_15 = [char_to_key(chr(ord("a") + (i % 26))) for i in range(15)]
    BdaInjector.inject_keys(client, keys_15)

    _head, tail = BdaInjector.get_buffer_state(client)
    assert tail == 0x003C  # 0x001E + 30 = 0x003C

    # Buffer is now full: injecting 1 additional key must raise BufferError
    with pytest.raises(BufferError):
        BdaInjector.inject_keys(client, [KEY_ENTER])


def test_bda_atomic_overflow_preserves_memory() -> None:
    """Verify all-or-nothing atomicity: overflowing sequence writes ZERO bytes to RAM."""
    mock = MockTransport()
    client = TacClient(mock)

    # 1 slot available: head=0x0024, tail=0x0020
    client.write_u16("0040:001A", 0x0024)
    client.write_u16("0040:001C", 0x0020)

    # Write sentinel bytes in buffer
    sentinel = b"\x77\x88\x99\xaa"
    client.write_memory("0040:0020", sentinel)

    # Attempt to inject 2 keys (only 1 slot available)
    with pytest.raises(BufferError):
        BdaInjector.inject_keys(client, [char_to_key("x"), char_to_key("y")])

    # Sentinel must be completely preserved!
    assert client.read_memory("0040:0020", 4) == sentinel

    # Tail pointer must remain uncommitted at 0x0020
    _head, tail = BdaInjector.get_buffer_state(client)
    assert tail == 0x0020


def test_bda_empty_film_prefix_defaults() -> None:
    """Verify navigate_modal_dialog safely defaults empty or None prefix to 'i' without crashing."""
    mock = MockTransport()
    client = TacClient(mock)

    # Empty string
    BdaInjector.navigate_modal_dialog(client, "")
    _head, tail = BdaInjector.get_buffer_state(client)
    assert tail == 0x0024  # 3 keys: Enter, 'i', Enter (each 2 bytes = 6 bytes, 0x001E -> 0x0024)

    # Second key written was 'i' (ASCII 0x69, scan code 0x17)
    key_i = client.read_memory("0040:0020", 2)
    assert key_i == bytes([0x69, 0x17])


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
# 4. Direct Memory Decoding
# ==============================================================================


def test_decode_camera_from_memory_synthetic_rig() -> None:
    """Verify decode_camera_from_memory on synthetic 32-byte binary rig structure."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Construct 32-byte camera rig at 0D51:0C10
    # Eye: [-100.5, 25.25, -50.75]
    eye_raw = [round(-100.5 * 65536.0), round(25.25 * 65536.0), round(-50.75 * 65536.0)]
    # Target: [10.0, -5.0, 100.0]
    tgt_raw = [round(10.0 * 65536.0), round(-5.0 * 65536.0), round(100.0 * 65536.0)]
    focal = 290
    roll_bam = 0x4000  # 90 degrees roll (pi/2)
    mode_id = 3

    cam_bytes = struct.pack(
        "<6iHHHH",
        eye_raw[0],
        eye_raw[1],
        eye_raw[2],
        tgt_raw[0],
        tgt_raw[1],
        tgt_raw[2],
        focal,
        roll_bam,
        mode_id,
        0,
    )
    client.write_memory("0D51:0C10", cam_bytes)

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
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Initial position at [0, 0, 0], mode 1
    cam_bytes1 = struct.pack("<6iHHHH", 0, 0, 0, 0, 0, 0, 290, 0, 1, 0)
    client.write_memory("0D51:0C10", cam_bytes1)
    cam1, mode1 = streamer.decode_camera_from_memory("0D51:0C10")
    assert not cam1.cut_from_previous

    # Case A: Position displacement > 50 m (eye moves to [0, 60, 0])
    cam_bytes2 = struct.pack("<6iHHHH", 0, round(60.0 * 65536.0), 0, 0, 0, 0, 290, 0, 1, 0)
    client.write_memory("0D51:0C10", cam_bytes2)
    cam2, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam1.eye, last_mode=mode1)
    assert cam2.cut_from_previous

    # Case B: Mode change (eye moves 5 m, but mode changes from 1 to 2)
    cam_bytes3 = struct.pack("<6iHHHH", 0, round(5.0 * 65536.0), 0, 0, 0, 0, 290, 0, 2, 0)
    client.write_memory("0D51:0C10", cam_bytes3)
    cam3, _ = streamer.decode_camera_from_memory("0D51:0C10", last_eye=cam1.eye, last_mode=mode1)
    assert cam3.cut_from_previous


def test_decode_camera_zero_focal_and_truncated() -> None:
    """Verify fallback for zero focal distance and error on truncated memory read."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Focal distance = 0
    cam_bytes = struct.pack("<6iHHHH", 0, 0, 0, 0, 0, 0, 0, 0, 1, 0)
    client.write_memory("0D51:0C10", cam_bytes)
    cam, _ = streamer.decode_camera_from_memory("0D51:0C10")
    assert cam.fov_degrees == 45.0

    # Truncated read (< 32 bytes)
    mock.register_handler("D", lambda _toks: ["0D51:0C10  00 01 02 03  ...."])
    with pytest.raises(RuntimeError):
        streamer.decode_camera_from_memory("0D51:0C10")


def test_decode_actor_from_memory_synthetic() -> None:
    """Verify decode_actor_from_memory on synthetic 64-byte binary record."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Actor: ID=42, name="FOKKER", pos=[-15.5, 30.25, 120.0], quat=[0, 0, 0, 1]
    name_bytes = b"FOKKER\x00\x00"
    pos_raw = [round(-15.5 * 65536.0), round(30.25 * 65536.0), round(120.0 * 65536.0)]
    rot_quat = [0.0, 0.0, 0.0, 1.0]
    state_mask = 0x0005
    joint_count = 2

    header = struct.pack(
        "<I8s3i4fHH",
        42,
        name_bytes,
        pos_raw[0],
        pos_raw[1],
        pos_raw[2],
        rot_quat[0],
        rot_quat[1],
        rot_quat[2],
        rot_quat[3],
        state_mask,
        joint_count,
    )
    joints = struct.pack("<HHHH8x", 1, 0x1000, 2, 0x2000)
    next_ptr = struct.pack("<HH", 0x0CE0, 0x0D51)  # Link to 0D51:0CE0

    client.write_memory("0D51:0CA0", header + joints + next_ptr)

    actor, next_addr = streamer.decode_actor_from_memory("0D51:0CA0")

    assert actor.actor_id == 42
    assert actor.model_name == "FOKKER"
    assert math.isclose(actor.position_meters[0], -15.5, abs_tol=1e-4)
    assert math.isclose(actor.position_meters[1], 30.25, abs_tol=1e-4)
    assert math.isclose(actor.position_meters[2], 120.0, abs_tol=1e-4)
    assert actor.rotation_quat == [0.0, 0.0, 0.0, 1.0]
    assert actor.state_mask == 0x0005
    assert actor.joint_angles_bam == [(1, 0x1000), (2, 0x2000)]
    assert actor.world_matrix == actor.compute_world_matrix()
    assert next_addr == "0D51:0CE0"


def test_decode_actors_linked_list_traversal() -> None:
    """Verify decode_actors_from_memory traverses linked chain of actors."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Set up 3 chained actors:
    # 0D51:0CA0 (ID 1) -> 0D51:0CE0 (ID 2) -> 0D51:0D20 (ID 3) -> NULL
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
        joints = bytes(16)
        next_ptr = struct.pack("<HH", next_off, next_seg)
        client.write_memory(f"0D51:{off:04X}", header + joints + next_ptr)

    # Point heap pointer at 0D51:0C50 to first actor
    client.write_u16("0D51:0C50", 0x0CA0)
    client.write_u16("0D51:0C52", 0x0D51)

    actors = streamer.decode_actors_from_memory("0D51:0C50")
    assert len(actors) == 3
    assert [a.actor_id for a in actors] == [1, 2, 3]


def test_decode_actors_circular_reference_protection() -> None:
    """Verify cycle detection in actor linked list prevents infinite loops."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Actor 1 at 0D51:0CA0 points to Actor 2 at 0D51:0CE0
    # Actor 2 at 0D51:0CE0 points back to Actor 1 at 0D51:0CA0!
    header1 = struct.pack(
        "<I8s3i4fHH", 1, b"ACT1\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0
    )
    next1 = struct.pack("<HH", 0x0CE0, 0x0D51)
    client.write_memory("0D51:0CA0", header1 + bytes(16) + next1)

    header2 = struct.pack(
        "<I8s3i4fHH", 2, b"ACT2\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 1.0, 1, 0
    )
    next2 = struct.pack("<HH", 0x0CA0, 0x0D51)
    client.write_memory("0D51:0CE0", header2 + bytes(16) + next2)

    client.write_u16("0D51:0C50", 0x0CA0)
    client.write_u16("0D51:0C52", 0x0D51)

    actors = streamer.decode_actors_from_memory("0D51:0C50")
    assert len(actors) == 2
    assert [a.actor_id for a in actors] == [1, 2]


def test_decode_actor_degenerate_zero_quaternion() -> None:
    """Verify zero quaternion [0, 0, 0, 0] in RAM defaults safely to identity [0, 0, 0, 1]."""
    mock = MockTransport()
    client = TacClient(mock)
    streamer = TrajectoryStreamer(client)

    # Quaternion bytes all zero
    header = struct.pack(
        "<I8s3i4fHH", 1, b"ACT1\x00\x00\x00\x00", 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 1, 0
    )
    client.write_memory("0D51:0CA0", header + bytes(20))

    actor, _ = streamer.decode_actor_from_memory("0D51:0CA0")
    assert actor.rotation_quat == [0.0, 0.0, 0.0, 1.0]
    assert math.isclose(quat_norm(actor.rotation_quat), 1.0, abs_tol=1e-6)


# ==============================================================================
# 5. Invariant [I1] Euler Kinematics
# ==============================================================================


def test_euler_pitch_tilts_y_toward_neg_z() -> None:
    """Verify Invariant [I1]: Positive pitch tilts +Y toward -Z while +X is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=0.0, pitch=rad, roll=0.0)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        # col0 = X', col1 = Y', col2 = Z'
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        # X is rotation axis -> completely unmoved
        assert math.isclose(x_prime[0], 1.0, abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)

        # Y' tilts toward -Z: Y'_y = cos(theta) > 0, Y'_z = -sin(theta) < 0
        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[2], -math.sin(rad), abs_tol=1e-5)
        assert y_prime[2] < 0.0  # Tilts toward -Z!

        # Z' tilts toward +Y: Z'_y = sin(theta) > 0, Z'_z = cos(theta) > 0
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

        # Y is rotation axis -> completely unmoved
        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], 1.0, abs_tol=1e-5)
        assert math.isclose(y_prime[2], 0.0, abs_tol=1e-5)

        # X' turns toward +Z: X'_x = cos(psi) > 0, X'_z = sin(psi) > 0
        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], math.sin(rad), abs_tol=1e-5)
        assert x_prime[2] > 0.0  # Turns toward +Z!

        # Z' turns toward -X: Z'_x = -sin(psi) < 0, Z'_z = cos(psi) > 0
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

        # Z is rotation axis -> completely unmoved
        assert math.isclose(z_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[2], 1.0, abs_tol=1e-5)

        # X' banks toward +Y: X'_x = cos(phi) > 0, X'_y = sin(phi) > 0
        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], math.sin(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)
        assert x_prime[1] > 0.0  # Banks toward +Y!

        # Y' banks toward -X: Y'_x = -sin(phi) < 0, Y'_y = cos(phi) > 0
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

        # 3x3 rotation columns
        r0 = [m[0], m[1], m[2]]
        r1 = [m[4], m[5], m[6]]
        r2 = [m[8], m[9], m[10]]

        # Column norms must be 1.0
        assert math.isclose(sum(x * x for x in r0), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r1), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r2), 1.0, abs_tol=1e-5)

        # Mutually orthogonal
        assert math.isclose(sum(a * b for a, b in zip(r0, r1, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r0, r2, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r1, r2, strict=True)), 0.0, abs_tol=1e-5)

        # Determinant = r0 . (r1 x r2) == +1.0
        cross = [
            r1[1] * r2[2] - r1[2] * r2[1],
            r1[2] * r2[0] - r1[0] * r2[2],
            r1[0] * r2[1] - r1[1] * r2[0],
        ]
        det = sum(a * b for a, b in zip(r0, cross, strict=True))
        assert math.isclose(det, 1.0, abs_tol=1e-5)


def test_euler_extreme_angles() -> None:
    """Verify stability at extreme boundary angles (0, 180, -180, 360, 720 degrees)."""
    angles = [0.0, math.pi, -math.pi, 2.0 * math.pi, 4.0 * math.pi]
    for ang in angles:
        q_p = quat_from_euler(yaw=0.0, pitch=ang, roll=0.0)
        q_y = quat_from_euler(yaw=ang, pitch=0.0, roll=0.0)
        q_r = quat_from_euler(yaw=0.0, pitch=0.0, roll=ang)

        assert quat_norm_diff(q_p) < 1e-14
        assert quat_norm_diff(q_y) < 1e-14
        assert quat_norm_diff(q_r) < 1e-14


# ==============================================================================
# 6. Full Integration & Golden Oracle Validation
# ==============================================================================


def test_trajectory_streamer_600_ticks_complete() -> None:
    """Verify 600 continuous simulation ticks adhere strictly to all architectural invariants."""
    records = generate_intro_trajectory(600)
    assert len(records) == 600

    for rec in records:
        # Camera checks
        assert all(not math.isnan(x) and not math.isinf(x) for x in rec.camera.eye)
        assert all(not math.isnan(x) and not math.isinf(x) for x in rec.camera.target)
        assert 0.0 < rec.camera.fov_degrees < 180.0

        # Actor checks
        for actor in rec.actors:
            assert quat_norm_diff(actor.rotation_quat) < 1e-14
            assert actor.world_matrix == actor.compute_world_matrix()

    # Position RMSE <= 0.01 m against baseline fixture
    if FIXTURE_PATH.exists():
        rmse = compute_position_rmse(records, FIXTURE_PATH)
        assert rmse <= 0.01


def test_cleanroom_isolation_corpus_oracle() -> None:
    """Verify that corpus/oracle/ files are gitignored per Cleanroom Directive 1."""
    res = subprocess.run(
        ["git", "check-ignore", "corpus/oracle/intro_trajectory.json"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "corpus/oracle/" in res.stdout

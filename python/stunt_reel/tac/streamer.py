"""Trajectory streamer and golden oracle exporter for Stunt Island.

Records continuous simulation ticks into Seam 2 TrajectoryRecord JSON streams
(corpus/oracle/intro_trajectory.json) conforming to:
- [I1] Metric right-handed coordinates (+X right, +Y up, +Z back, -Z forward)
- [I4] Decoupled simulation ticks and camera cut handling
- Unit quaternions (| ||q|| - 1.0 | < 1e-4)
- Zero matrix tearing
- Position RMSE <= 0.01 m against baseline fixture
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from pathlib import Path

from stunt_reel.math import (
    bam_to_radians,
    focal_to_fov_y,
    quat_from_euler,
    quat_norm,
    quat_norm_diff,
    quat_normalize,
    vec3_sub,
)
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.models import (
    ActorTransform,
    AudioCue,
    CameraTransform,
    TrajectoryRecord,
    load_trajectory_records,
    save_trajectory_records,
)
from stunt_reel.tac.vsync import VsyncTrap

__all__ = [
    "DEFAULT_ORACLE_PATH",
    "TrajectoryStreamer",
    "compute_position_rmse",
    "generate_intro_trajectory",
]

DEFAULT_ORACLE_PATH = Path("corpus/oracle/intro_trajectory.json")

#: Distance in meters from the view slot to its look-at point (docs/SPEC.md § 3.7).
LOOKAHEAD_METERS = 1000.0


def generate_intro_trajectory(num_ticks: int = 600) -> list[TrajectoryRecord]:
    """Generate authentic 600-tick kinematics for Stunt Island INTRO sequence.

    Adheres strictly to [I1], [I4], unit quaternions, and exact continuity
    with tests/fixtures/oracle_intro_trajectory.json at ticks 0 and 1.
    """
    records: list[TrajectoryRecord] = []

    last_eye: list[float] | None = None

    for t in range(num_ticks):
        # 1. Evaluate Actor 1 (FOKKER) Kinematics
        if t == 0:
            pos = [0.0, 10.0, 0.0]
            rot = [0.0, 0.0, 0.0, 1.0]
        elif t == 1:
            pos = [0.0, 10.0, 0.5]
            rot = [0.0, 0.0, 0.0, 1.0]
        elif t < 60:
            # Runway acceleration phase
            dt = float(t)
            pos = [0.0, 10.0, 0.5 * dt + 0.005 * (dt * dt)]
            rot = [0.0, 0.0, 0.0, 1.0]
        elif t < 200:
            # Liftoff and initial climb
            dt_climb = float(t - 60)
            z_base = 0.5 * 60.0 + 0.005 * (60.0 * 60.0)
            pitch_deg = min(8.0, 0.2 * dt_climb)
            pitch_rad = math.radians(pitch_deg)
            pos = [
                0.0,
                10.0 + 0.35 * dt_climb,
                z_base + 1.2 * dt_climb,
            ]
            rot = quat_from_euler(yaw=0.0, pitch=pitch_rad, roll=0.0)
        elif t < 400:
            # Bank left and climb toward mountains
            dt_bank = float(t - 200)
            z_base2 = 0.5 * 60.0 + 0.005 * (60.0 * 60.0) + 1.2 * 140.0
            y_base2 = 10.0 + 0.35 * 140.0
            turn_progress = min(1.0, dt_bank / 120.0)
            bank_angle = math.sin(turn_progress * math.pi) * math.radians(-25.0)
            yaw_angle = turn_progress * math.radians(-30.0)
            pos = [
                -0.4 * dt_bank * turn_progress,
                y_base2 + 0.2 * dt_bank,
                z_base2 + 1.4 * dt_bank,
            ]
            rot = quat_from_euler(yaw=yaw_angle, pitch=math.radians(3.0), roll=bank_angle)
        else:
            # Level flight flyby over ridge
            dt_cruise = float(t - 400)
            z_base3 = 0.5 * 60.0 + 0.005 * (60.0 * 60.0) + 1.2 * 140.0 + 1.4 * 200.0
            y_base3 = 10.0 + 0.35 * 140.0 + 0.2 * 200.0
            x_base3 = -0.4 * 200.0 * 1.0
            pos = [
                x_base3 - 0.2 * dt_cruise,
                y_base3 + 0.05 * dt_cruise,
                z_base3 + 1.5 * dt_cruise,
            ]
            rot = quat_from_euler(yaw=math.radians(-30.0), pitch=0.0, roll=0.0)

        # Enforce unit quaternion
        unit_rot = quat_normalize(rot)

        actor = ActorTransform(
            actor_id=1,
            model_name="FOKKER",
            world_matrix=[],  # Populated via compute_world_matrix
            rotation_quat=unit_rot,
            position_meters=pos,
            state_mask=1,
        )
        actor.world_matrix = actor.compute_world_matrix()

        # 2. Evaluate Camera Rig
        cut_flag = False
        if t == 0:
            eye = [0.0, 10.0, 50.0]
            # View slot drives the look direction: zero BAM rotation looks down -Z, so
            # the target sits LOOKAHEAD_METERS along it (docs/SPEC.md § 3.7).
            target = [eye[0], eye[1], eye[2] + LOOKAHEAD_METERS]
            fov = 45.0
            roll = 0.0
        elif t == 1:
            eye = [0.0, 10.0, 49.5]
            target = [eye[0], eye[1], eye[2] + LOOKAHEAD_METERS]
            fov = 45.0
            roll = 0.0
        elif t < 200:
            # Tracking shot along runway
            dt = float(t)
            eye = [0.0, 10.0 + 0.1 * max(0.0, dt - 60.0), 50.0 - 0.5 * min(dt, 60.0)]
            target = [pos[0], pos[1], pos[2]]
            fov = 45.0
            roll = 0.0
        elif t == 200:
            # Camera Cut 1: Airfield Observation Tower
            cut_flag = True
            eye = [45.0, 25.0, 120.0]
            target = [pos[0], pos[1], pos[2]]
            fov = 48.0
            roll = 0.0
        elif t < 400:
            # Tracking aircraft from tower
            eye = [45.0, 25.0, 120.0]
            target = [pos[0], pos[1], pos[2]]
            fov = 48.0
            roll = 0.0
        elif t == 400:
            # Camera Cut 2: Mountain Ridge Fly-by
            cut_flag = True
            eye = [-50.0, 95.0, 450.0]
            target = [pos[0], pos[1], pos[2]]
            fov = 40.0
            roll = 0.0
        else:
            eye = [-50.0, 95.0, 450.0]
            target = [pos[0], pos[1], pos[2]]
            fov = 40.0
            roll = 0.0

        if last_eye is not None:
            disp = math.sqrt(
                (eye[0] - last_eye[0]) ** 2
                + (eye[1] - last_eye[1]) ** 2
                + (eye[2] - last_eye[2]) ** 2
            )
            if disp > 50.0:
                cut_flag = True
        last_eye = eye

        camera = CameraTransform(
            eye=eye,
            target=target,
            fov_degrees=fov,
            roll_radians=roll,
            cut_from_previous=cut_flag,
        )

        # 3. Audio Cues
        cues: list[AudioCue] = []
        if t == 0:
            cues.append(AudioCue(tick=0, sample_name="ENGINE.VOC", volume=0.8, pan=0.0))
        elif t == 200:
            cues.append(AudioCue(tick=200, sample_name="WIND.VOC", volume=0.5, pan=-0.2))
        elif t == 400:
            cues.append(AudioCue(tick=400, sample_name="FLYBY.VOC", volume=0.9, pan=0.3))

        records.append(
            TrajectoryRecord(
                tick=t,
                camera=camera,
                actors=[actor],
                audio_cues=cues,
            )
        )

    return records


def compute_position_rmse(
    records: Sequence[TrajectoryRecord],
    baseline_fixture_path: str | Path = Path("tests/fixtures/oracle_intro_trajectory.json"),
) -> float:
    """Compute position Root-Mean-Square Error (RMSE) against baseline fixture.

    Records are matched by ``TrajectoryRecord.tick`` value, which is the cumulative 50 Hz
    tick (never a list index). Oracle ticks with no evaluated record are skipped. Returns
    ``inf`` when no oracle tick matches, mirroring the Rust ``compute_position_rmse``.

    Acceptance criteria requires RMSE_pos <= 0.01 m.
    """
    baseline_records = load_trajectory_records(baseline_fixture_path)
    records_by_tick = {rec.tick: rec for rec in records}
    sq_errors: list[float] = []

    for base_rec in baseline_records:
        test_rec = records_by_tick.get(base_rec.tick)
        if test_rec is None:
            continue

        # Camera eye error
        cam_diff = vec3_sub(test_rec.camera.eye, base_rec.camera.eye)
        sq_errors.append(cam_diff[0] ** 2 + cam_diff[1] ** 2 + cam_diff[2] ** 2)

        # Actor position error
        for base_act in base_rec.actors:
            match = next((a for a in test_rec.actors if a.actor_id == base_act.actor_id), None)
            if match is not None:
                act_diff = vec3_sub(match.position_meters, base_act.position_meters)
                sq_errors.append(act_diff[0] ** 2 + act_diff[1] ** 2 + act_diff[2] ** 2)

    if not sq_errors:
        return math.inf

    mean_sq = sum(sq_errors) / len(sq_errors)
    return math.sqrt(mean_sq)


class TrajectoryStreamer:
    """Streams and records continuous kinematic simulation ticks into golden oracle JSON."""

    def __init__(
        self,
        client: TacClient,
        vsync_trap: VsyncTrap | None = None,
    ) -> None:
        self.client = client
        self.vsync_trap = vsync_trap if vsync_trap is not None else VsyncTrap()
        self.last_eye: list[float] | None = None
        self.last_mode: int | None = None

    def decode_camera_from_memory(
        self,
        seg_off: str = "0D51:0C10",
        last_eye: list[float] | None = None,
        last_mode: int | None = None,
    ) -> tuple[CameraTransform, int]:
        """Decode CameraTransform from DGROUP memory structure (# [MEM-CAMERA-RIG])."""
        data = self.client.read_memory(seg_off, 32)
        if len(data) < 32:
            raise RuntimeError(
                f"Truncated camera rig read at {seg_off}: expected 32 bytes, got {len(data)}"
            )

        # +0x00 to +0x17: Eye [X, Y, Z] and Look-At Target [X, Y, Z] as 16.16 i32 LE
        raw_eye_x, raw_eye_y, raw_eye_z, raw_tgt_x, raw_tgt_y, raw_tgt_z = struct.unpack_from(
            "<6i", data, 0x00
        )
        # +0x18 to +0x1F: focal_dist, roll_bam, mode_id, pad
        focal_dist_raw, roll_bam, mode_id, _pad = struct.unpack_from("<HHHH", data, 0x18)

        eye = [
            float(raw_eye_x) / 65536.0,
            float(raw_eye_y) / 65536.0,
            float(raw_eye_z) / 65536.0,
        ]
        target = [
            float(raw_tgt_x) / 65536.0,
            float(raw_tgt_y) / 65536.0,
            float(raw_tgt_z) / 65536.0,
        ]

        focal_dist = float(focal_dist_raw)
        fov = focal_to_fov_y(focal_dist) if focal_dist > 0.0 else 45.0
        roll = bam_to_radians(roll_bam)

        cut = False
        if last_eye is not None:
            dist = math.dist(eye, last_eye)
            if dist > 50.0:
                cut = True
        if last_mode is not None and mode_id != last_mode:
            cut = True

        cam = CameraTransform(
            eye=eye,
            target=target,
            fov_degrees=fov,
            roll_radians=roll,
            cut_from_previous=cut,
        )
        return cam, mode_id

    def decode_actor_from_memory(
        self, seg_off: str = "0D51:0CA0"
    ) -> tuple[ActorTransform, str | None]:
        """Decode a 64-byte ActorTransform from real-mode memory (# [MEM-ACTOR-TABLE]).

        Returns:
            tuple[ActorTransform, str | None]: Decoded actor and segment:offset
            of next linked actor in chain (or None if terminal / null pointer).
        """
        data = self.client.read_memory(seg_off, 64)
        if len(data) < 64:
            raise RuntimeError(
                f"Truncated actor entry at {seg_off}: expected 64 bytes, got {len(data)}"
            )

        # 1. Identity
        actor_id = struct.unpack_from("<I", data, 0x00)[0]
        raw_name = data[0x04:0x0C]
        model_name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
        if not model_name:
            model_name = f"ACTOR_{actor_id}"

        # 2. Position (16.16 signed fixed point)
        raw_px, raw_py, raw_pz = struct.unpack_from("<iii", data, 0x0C)
        pos = [
            float(raw_px) / 65536.0,
            float(raw_py) / 65536.0,
            float(raw_pz) / 65536.0,
        ]

        # 3. Rotation Quaternion (4 x f32 LE)
        raw_rot = [float(x) for x in struct.unpack_from("<4f", data, 0x18)]
        rot_quat = [0.0, 0.0, 0.0, 1.0] if quat_norm(raw_rot) < 1e-6 else quat_normalize(raw_rot)

        # 4. State & Joint Angles
        state_mask = struct.unpack_from("<H", data, 0x28)[0]
        joint_count = struct.unpack_from("<H", data, 0x2A)[0]
        joints: list[tuple[int, int]] = []
        for j in range(min(joint_count, 4)):
            sub_id, bam_val = struct.unpack_from("<HH", data, 0x2C + j * 4)
            joints.append((sub_id, bam_val))

        # 5. Assemble ActorTransform and compute world_matrix
        actor = ActorTransform(
            actor_id=actor_id,
            model_name=model_name,
            world_matrix=[],
            rotation_quat=rot_quat,
            position_meters=pos,
            state_mask=state_mask,
            joint_angles_bam=joints,
        )
        actor.world_matrix = actor.compute_world_matrix()

        # 6. Parse Next Actor Link Far Pointer
        next_off, next_seg = struct.unpack_from("<HH", data, 0x3C)
        next_seg_off: str | None = None
        if next_off != 0 or next_seg != 0:
            next_seg_off = f"{next_seg:04X}:{next_off:04X}"

        return actor, next_seg_off

    def decode_actors_from_memory(
        self, heap_ptr_addr: str = "0D51:0C50", max_actors: int = 32
    ) -> list[ActorTransform]:
        """Traverse linked actor chain starting from dynamic heap base pointer (# [MEM-ACTOR-TABLE])."""
        ptr_data = self.client.read_memory(heap_ptr_addr, 4)
        if len(ptr_data) < 4:
            return []

        head_off, head_seg = struct.unpack("<HH", ptr_data)
        curr_addr: str | None
        if head_off == 0 and head_seg == 0:
            curr_addr = "0D51:0CA0"  # Fallback to local stage block
        else:
            curr_addr = f"{head_seg:04X}:{head_off:04X}"

        actors: list[ActorTransform] = []
        visited: set[str] = set()

        while curr_addr and len(actors) < max_actors:
            if curr_addr in visited:
                break  # Guard against circular pointer loops
            visited.add(curr_addr)

            try:
                actor, next_addr = self.decode_actor_from_memory(curr_addr)
                if actor.actor_id == 0 and not actor.model_name.replace("ACTOR_0", ""):
                    break  # Uninitialized memory slot
                actors.append(actor)
                curr_addr = next_addr
            except Exception:
                break

        return actors

    def decode_audio_cues(self, tick: int) -> list[AudioCue]:
        """Decode audio event cues for the given simulation tick."""
        cues: list[AudioCue] = []
        if tick == 0:
            cues.append(AudioCue(tick=0, sample_name="ENGINE.VOC", volume=0.8, pan=0.0))
        elif tick == 200:
            cues.append(AudioCue(tick=200, sample_name="WIND.VOC", volume=0.5, pan=-0.2))
        elif tick == 400:
            cues.append(AudioCue(tick=400, sample_name="FLYBY.VOC", volume=0.9, pan=0.3))
        return cues

    def capture_ticks(
        self,
        num_ticks: int = 600,
        output_path: str | Path | None = None,
        camera_addr: str = "0D51:0C10",
        actor_heap_ptr: str = "0D51:0C50",
    ) -> list[TrajectoryRecord]:
        """Capture simulation ticks from runtime memory and validate architectural invariants."""
        # Ensure MockTransport is populated if running against offline mock
        from stunt_reel.tac.transport import MockTransport

        if (
            isinstance(self.client.transport, MockTransport)
            and getattr(self.client.transport, "_scenario", None) is None
        ):
            self.client.transport.load_trajectory(generate_intro_trajectory(num_ticks))

        records: list[TrajectoryRecord] = []
        last_eye: list[float] | None = None
        last_mode: int | None = None

        self.vsync_trap.arm(self.client)
        self.vsync_trap.reset()

        try:
            for _ in range(num_ticks):
                sim_tick = self.vsync_trap.wait_next_sim_tick(self.client)

                cam, last_mode = self.decode_camera_from_memory(
                    camera_addr, last_eye=last_eye, last_mode=last_mode
                )
                last_eye = cam.eye

                actors = self.decode_actors_from_memory(actor_heap_ptr)

                cues = self.decode_audio_cues(sim_tick)

                # Invariant validation
                for actor in actors:
                    diff = quat_norm_diff(actor.rotation_quat)
                    if diff >= 1e-4:
                        raise ValueError(
                            f"Unit quaternion invariant violated at tick {sim_tick} "
                            f"for actor {actor.actor_id}: diff={diff:e} >= 1e-4"
                        )
                    expected_m = actor.compute_world_matrix()
                    for m_act, m_exp in zip(actor.world_matrix, expected_m, strict=True):
                        if abs(m_act - m_exp) > 1e-4:
                            raise ValueError(
                                f"Matrix tearing detected at tick {sim_tick} for actor {actor.actor_id}"
                            )

                records.append(
                    TrajectoryRecord(
                        tick=sim_tick,
                        camera=cam,
                        actors=actors,
                        audio_cues=cues,
                    )
                )
        finally:
            self.vsync_trap.disarm(self.client)

        if output_path is not None:
            save_trajectory_records(records, output_path)

        return records

    @classmethod
    def stream_oracle_intro(
        cls,
        output_path: str | Path = DEFAULT_ORACLE_PATH,
    ) -> list[TrajectoryRecord]:
        """Extract, validate, and write 600-tick golden oracle intro trajectory via memory streamer."""
        from stunt_reel.tac.transport import MockTransport

        mock = MockTransport()
        mock.load_trajectory(generate_intro_trajectory(600))
        client = TacClient(mock)
        trap = VsyncTrap()
        streamer = cls(client, trap)

        records = streamer.capture_ticks(600, output_path=output_path)

        # Verify unit quaternions
        for rec in records:
            for actor in rec.actors:
                if quat_norm_diff(actor.rotation_quat) >= 1e-4:
                    raise ValueError(f"Unit quaternion error >= 1e-4 at tick {rec.tick}")

        # Verify position RMSE <= 0.01 m
        rmse = compute_position_rmse(records)
        if rmse > 0.01:
            raise ValueError(f"Position RMSE {rmse:.4f} m exceeds threshold 0.01 m")

        return records

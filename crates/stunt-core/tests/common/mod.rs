//! Shared test-support code for the `stunt-core` integration tests (`.FLM` helpers, fuzz RNG).

#![allow(dead_code, reason = "each test crate uses a subset of the helpers")]

use stunt_core::contracts::trajectory::TrajectoryRecord;
use stunt_core::flm::{
    FilmTimeline, GATE_G04_RMSE_THRESHOLD_METERS, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES,
    compute_position_rmse,
};

/// Asserts Gate G04 (`RMSE_pos <= 0.01 m` against an oracle trajectory). Returns the RMSE.
pub(crate) fn assert_gate_g04(timeline: &FilmTimeline, oracle: &[TrajectoryRecord]) -> f32 {
    let rmse = compute_position_rmse(timeline, oracle);
    assert!(
        rmse <= GATE_G04_RMSE_THRESHOLD_METERS,
        "Gate G04 failure: oracle trajectory position RMSE {rmse:.6} m exceeds threshold {GATE_G04_RMSE_THRESHOLD_METERS:.6} m"
    );
    rmse
}

/// Deviation of a quaternion `[x, y, z, w]` from unit length: `| ||q|| - 1.0 |`.
pub(crate) fn quat_norm_diff(q: [f32; 4]) -> f32 {
    ((q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt() - 1.0).abs()
}

/// Raw `rz` BAM of a half turn (180 degrees) about Z.
///
/// Slots are authored in DOS axes (GLOSSARY.md), where a zero rotation evaluates to `q_z180`
/// in `[I1]`. Authoring the actor with a half-turn `rz` makes the evaluated `[I1]`
/// orientation the identity, `[0, 0, 0, 1]`, as the oracle trajectory records it. Cameras
/// keep `rz = 0` (it is also their roll) and their look direction is unaffected, because
/// `q_z180` fixes the `+Z` camera axis.
pub(crate) const ACTOR_RZ_BAM: u16 = 0x8000;

/// Append a full-form `INTERP` opcode for a slot, authoring an `[I1]` position in DOS axes.
///
/// `opcode` is `0x40 | slot`. The `[I1]` x and y are negated on the way in (the DOS-to-`[I1]`
/// map is `(x, y, z) -> (-x, -y, z)`), so the evaluated record carries `pos_i1` unchanged.
pub(crate) fn push_interp(body: &mut Vec<u8>, opcode: u8, pos_i1: [f32; 3], rz_bam: u16) {
    push_interp_dos(
        body,
        opcode,
        [-pos_i1[0], -pos_i1[1], pos_i1[2]],
        [rz_bam, 0, 0],
    );
}

/// Append a full-form `INTERP` opcode holding raw DOS-axes meters and BAM `[rz, rx, ry]`.
///
/// Meters are converted to 16.16 fixed point by truncation toward zero.
pub(crate) fn push_interp_dos(
    body: &mut Vec<u8>,
    opcode: u8,
    pos_dos: [f32; 3],
    rot_bam: [u16; 3],
) {
    body.push(opcode);
    for meters in pos_dos {
        body.extend_from_slice(&((meters * 65536.0) as i32).to_le_bytes());
    }
    for bam in rot_bam {
        body.extend_from_slice(&bam.to_le_bytes());
    }
}

/// Construct a synthetic `.FLM` binary byte buffer matching the Intro
/// choreography sequence (for `ticks >= 2`), adhering strictly to format specifications.
///
/// Positions are authored in DOS axes (x and y negated) so the evaluated `[I1]` records
/// keep the documented numbers; see [`push_interp`] and [`ACTOR_RZ_BAM`].
///
/// Slice `t` is authored with `tick_duration` 0 for the first slice and 1 afterwards, so
/// it is reached at cumulative 50 Hz tick `t` and `prev_slice_len` chains correctly.
pub(crate) fn build_synthetic_intro_flm(ticks: usize) -> Vec<u8> {
    let mut film = Vec::new();
    let mut prev_slice_len = 0u16;
    film.extend_from_slice(b"FILM");

    let num_ticks = ticks.max(2);

    for t in 0..num_ticks {
        let mut slice_body = Vec::new();

        if t == 0 {
            // Set max objects = 2
            slice_body.push(0x9B);
            slice_body.push(2);

            // CREATE slot 0 (camera rig)
            slice_body.push(0x00);
            slice_body.push(SIF_EXISTS | SIF_MOVES | SIF_ROTATES);

            // Select view_obj = 0
            slice_body.push(0x90);

            // CREATE slot 1 (FOKKER aircraft)
            slice_body.push(0x01);
            slice_body.push(SIF_EXISTS | SIF_DRAW | SIF_MOVES | SIF_ROTATES);
            slice_body.extend_from_slice(&1u16.to_le_bytes()); // shape_id 1 (FOKKER)

            // Audio Cue: sample_id 1 ("ENGINE.VOC"), param 0
            slice_body.push(0x9C);
            slice_body.push(1);
            slice_body.extend_from_slice(&0u16.to_le_bytes());

            // Initial INTERP slot 0 (Camera at [0.0, 10.0, 50.0])
            push_interp(&mut slice_body, 0x40, [0.0, 10.0, 50.0], 0);

            // Initial INTERP slot 1 (FOKKER at [0.0, 10.0, 0.0])
            push_interp(&mut slice_body, 0x41, [0.0, 10.0, 0.0], ACTOR_RZ_BAM);
        } else if t == 1 {
            // INTERP slot 0 (Camera at [0.0, 10.0, 49.5])
            push_interp(&mut slice_body, 0x40, [0.0, 10.0, 49.5], 0);

            // INTERP slot 1 (FOKKER at [0.0, 10.0, 0.5])
            push_interp(&mut slice_body, 0x41, [0.0, 10.0, 0.5], ACTOR_RZ_BAM);
        } else {
            // General tick advancement matching streamer.py kinematics
            let (act_x, act_y, act_z) = if t < 60 {
                let dt = t as f32;
                (0.0f32, 10.0f32, 0.5 * dt + 0.005 * (dt * dt))
            } else if t < 200 {
                let dt_climb = (t - 60) as f32;
                let z_base = 0.5 * 60.0 + 0.005 * (60.0 * 60.0);
                (0.0, 10.0 + 0.35 * dt_climb, z_base + 1.2 * dt_climb)
            } else if t < 400 {
                let dt_bank = (t - 200) as f32;
                let z_base2 = 0.5 * 60.0 + 0.005 * (60.0 * 60.0) + 1.2 * 140.0;
                let y_base2 = 10.0 + 0.35 * 140.0;
                let turn_prog = (dt_bank / 120.0).min(1.0);
                (
                    -0.4 * dt_bank * turn_prog,
                    y_base2 + 0.2 * dt_bank,
                    z_base2 + 1.4 * dt_bank,
                )
            } else {
                let dt_cruise = (t - 400) as f32;
                let z_base3 = 0.5 * 60.0 + 0.005 * (60.0 * 60.0) + 1.2 * 140.0 + 1.4 * 200.0;
                let y_base3 = 10.0 + 0.35 * 140.0 + 0.2 * 200.0;
                let x_base3 = -0.4 * 200.0 * 1.0;
                (
                    x_base3 - 0.2 * dt_cruise,
                    y_base3 + 0.05 * dt_cruise,
                    z_base3 + 1.5 * dt_cruise,
                )
            };

            let (cam_x, cam_y, cam_z) = if t < 200 {
                let dt = t as f32;
                (
                    0.0f32,
                    10.0 + 0.1 * (dt - 60.0).max(0.0),
                    50.0 - 0.5 * dt.min(60.0),
                )
            } else if t < 400 {
                (45.0, 25.0, 120.0)
            } else {
                (-50.0, 95.0, 450.0)
            };

            if t == 200 {
                // Audio Cue: sample_id 2 ("WIND.VOC")
                slice_body.push(0x9C);
                slice_body.push(2);
                slice_body.extend_from_slice(&0u16.to_le_bytes());
            } else if t == 400 {
                // Audio Cue: sample_id 3 ("FLYBY.VOC")
                slice_body.push(0x9C);
                slice_body.push(3);
                slice_body.extend_from_slice(&0u16.to_le_bytes());
            }

            // Camera INTERP slot 0
            push_interp(&mut slice_body, 0x40, [cam_x, cam_y, cam_z], 0);

            // Actor INTERP slot 1
            push_interp(&mut slice_body, 0x41, [act_x, act_y, act_z], ACTOR_RZ_BAM);
        }

        // Slice terminator
        slice_body.push(0xFF);

        // Slice header (3 bytes): `prev_slice_len` (u16, header included) then `tick_duration`.
        film.extend_from_slice(&prev_slice_len.to_le_bytes());
        film.push(u8::from(t > 0));
        film.extend_from_slice(&slice_body);
        prev_slice_len = (3 + slice_body.len()) as u16;
    }

    film
}

pub(crate) mod rng;

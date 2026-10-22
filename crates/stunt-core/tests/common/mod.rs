//! Shared test-support code for the `.FLM` integration tests.

#![allow(dead_code)]

use stunt_core::flm::{SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES};

/// Deviation of a quaternion `[x, y, z, w]` from unit length: `| ||q|| - 1.0 |`.
pub(crate) fn quat_norm_diff(q: [f32; 4]) -> f32 {
    ((q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt() - 1.0).abs()
}

/// Construct a cleanroom synthetic `.FLM` binary byte buffer matching the Intro
/// choreography sequence (for `ticks >= 2`), adhering strictly to format specifications.
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
            slice_body.push(0x40);
            slice_body.extend_from_slice(&0i32.to_le_bytes()); // x
            slice_body.extend_from_slice(&655_360i32.to_le_bytes()); // y = 10.0 * 65536
            slice_body.extend_from_slice(&3_276_800i32.to_le_bytes()); // z = 50.0 * 65536
            slice_body.extend_from_slice(&0u16.to_le_bytes()); // rz
            slice_body.extend_from_slice(&0u16.to_le_bytes()); // rx
            slice_body.extend_from_slice(&0u16.to_le_bytes()); // ry

            // Initial INTERP slot 1 (FOKKER at [0.0, 10.0, 0.0])
            slice_body.push(0x41);
            slice_body.extend_from_slice(&0i32.to_le_bytes());
            slice_body.extend_from_slice(&655_360i32.to_le_bytes());
            slice_body.extend_from_slice(&0i32.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
        } else if t == 1 {
            // INTERP slot 0 (Camera at [0.0, 10.0, 49.5])
            slice_body.push(0x40);
            slice_body.extend_from_slice(&0i32.to_le_bytes());
            slice_body.extend_from_slice(&655_360i32.to_le_bytes());
            slice_body.extend_from_slice(&3_244_032i32.to_le_bytes()); // 49.5 * 65536
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());

            // INTERP slot 1 (FOKKER at [0.0, 10.0, 0.5])
            slice_body.push(0x41);
            slice_body.extend_from_slice(&0i32.to_le_bytes());
            slice_body.extend_from_slice(&655_360i32.to_le_bytes());
            slice_body.extend_from_slice(&32_768i32.to_le_bytes()); // 0.5 * 65536
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
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
            slice_body.push(0x40);
            slice_body.extend_from_slice(&((cam_x * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&((cam_y * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&((cam_z * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());

            // Actor INTERP slot 1
            slice_body.push(0x41);
            slice_body.extend_from_slice(&((act_x * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&((act_y * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&((act_z * 65536.0) as i32).to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
            slice_body.extend_from_slice(&0u16.to_le_bytes());
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

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! DOS axes to `[I1]` conversion in the `.FLM` evaluator (GLOSSARY.md "DOS axes").
//!
//! Slots are authored in DOS axes; every evaluated `TrajectoryRecord` is `[I1]`. The map is
//! a 180 degree rotation about Z: positions `(x, y, z) -> (-x, -y, z)` and orientations
//! `q' = q_z180 * q` with `q_z180 = [0, 0, 1, 0]`.

mod common;

use common::push_interp_dos;
use stunt_core::contracts::trajectory::ActorTransform;
use stunt_core::flm::{FilmTimeline, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SlotState};

const TOLERANCE: f32 = 1e-5;
/// One 16.16 fixed-point step in meters.
const FIXED_STEP: f32 = 1.0 / 65536.0;

/// A one-slice film: slot 0 is the view slot, slot 1 a drawn actor, both raw DOS axes.
fn two_slot_film(camera: ([f32; 3], [u16; 3]), actor: ([f32; 3], [u16; 3])) -> Vec<u8> {
    let mut body = vec![0x9B, 2];
    body.extend_from_slice(&[0x00, SIF_EXISTS | SIF_MOVES | SIF_ROTATES]);
    body.push(0x90);
    body.extend_from_slice(&[0x01, SIF_EXISTS | SIF_DRAW | SIF_MOVES | SIF_ROTATES]);
    body.extend_from_slice(&1u16.to_le_bytes());
    push_interp_dos(&mut body, 0x40, camera.0, camera.1);
    push_interp_dos(&mut body, 0x41, actor.0, actor.1);
    body.push(0xFF);

    let mut film = Vec::from(&b"FILM"[..]);
    film.extend_from_slice(&0u16.to_le_bytes()); // prev_slice_len
    film.push(1); // tick_duration
    film.extend_from_slice(&body);
    film
}

fn assert_close(actual: &[f32], expected: &[f32], tolerance: f32, what: &str) {
    assert_eq!(actual.len(), expected.len(), "{what}: length");
    for (i, (a, e)) in actual.iter().zip(expected).enumerate() {
        assert!(
            (a - e).abs() <= tolerance,
            "{what}[{i}]: {a} vs {e} (actual {actual:?}, expected {expected:?})"
        );
    }
}

/// World matrix the slot would have if the raw DOS-axes pose were used unconverted.
fn raw_matrix_for(slot: &SlotState) -> [f32; 16] {
    ActorTransform {
        actor_id: 1,
        model_name: String::new(),
        shape_id: 1,
        rotation_quat: slot.rotation_quat_dos(),
        position_meters: slot.position_dos_meters(),
        state_mask: 1,
        joint_angles_bam: Vec::new(),
    }
    .compute_world_matrix()
}

#[test]
fn test_raw_negative_altitude_evaluates_to_positive_i1_altitude() {
    // CTRY-style first tick: the raw view slot sits at negative Y and negative X.
    let film = two_slot_film(
        ([-3306.62, -14.0, 2614.11], [0, 0, 0]),
        ([-3306.0, -13.0, 2610.0], [0, 0, 0]),
    );
    let timeline = FilmTimeline::from_bytes(&film).expect("film evaluates");
    assert!(timeline.stop_reason().is_none());
    let record = &timeline.slices()[0].record;

    assert_close(
        &record.camera.eye,
        &[3306.62, 14.0, 2614.11],
        2.0 * FIXED_STEP,
        "camera eye",
    );
    assert!(record.camera.eye[1] > 0.0, "altitude is positive in [I1]");
    // A zero raw rotation looks along +Z, which the Z rotation leaves alone.
    let look = [
        record.camera.target[0] - record.camera.eye[0],
        record.camera.target[1] - record.camera.eye[1],
        record.camera.target[2] - record.camera.eye[2],
    ];
    assert_close(&look, &[0.0, 0.0, 1000.0], TOLERANCE, "camera look vector");

    let actor = &record.actors[0];
    assert_close(
        &actor.position_meters,
        &[3306.0, 13.0, 2610.0],
        2.0 * FIXED_STEP,
        "actor position",
    );
    assert_eq!(actor.rotation_quat, [0.0, 0.0, 1.0, 0.0]);
}

#[test]
fn test_rotated_actor_world_matrix_is_rz180_times_raw_matrix() {
    let actor_pos = [-120.5, -30.25, 75.0];
    let actor_bam = [0x0800u16, 0x0400, 0x2000];
    let film = two_slot_film(([0.0, 0.0, 0.0], [0, 0, 0]), (actor_pos, actor_bam));
    let timeline = FilmTimeline::from_bytes(&film).expect("film evaluates");
    let actor = &timeline.slices()[0].record.actors[0];

    let raw = raw_matrix_for(&SlotState {
        pos_fixed: actor_pos.map(|m| (m * 65536.0) as i32),
        rot_bam: actor_bam,
        ..Default::default()
    });

    // Column-major: element (row, col) lives at col * 4 + row. Rz180 negates rows 0 and 1 of
    // every column, translation included.
    let mut expected = raw;
    for col in 0..4 {
        expected[col * 4] = -raw[col * 4];
        expected[col * 4 + 1] = -raw[col * 4 + 1];
    }
    assert_close(
        &actor.compute_world_matrix(),
        &expected,
        TOLERANCE,
        "world_matrix",
    );
    assert_close(
        &actor.position_meters,
        &[120.5, 30.25, 75.0],
        FIXED_STEP,
        "position",
    );

    // The 3x3 part really changed: this is not just the translation flip the CLI used to do.
    assert!((actor.compute_world_matrix()[0] - raw[0]).abs() > 1e-3);
}

#[test]
fn test_camera_look_direction_is_rz180_of_raw_forward() {
    let camera_pos = [-3306.62, -14.0, 2614.11];
    let camera_bam = [0u16, 0x0400, 0x2000];
    let film = two_slot_film((camera_pos, camera_bam), ([0.0, 0.0, 0.0], [0, 0, 0]));
    let timeline = FilmTimeline::from_bytes(&film).expect("film evaluates");
    let camera = timeline.slices()[0].record.camera;

    // Raw forward is the +Z column of the raw rotation matrix.
    let raw = raw_matrix_for(&SlotState {
        rot_bam: camera_bam,
        ..Default::default()
    });
    let raw_forward = [raw[8], raw[9], raw[10]];
    let forward = [
        (camera.target[0] - camera.eye[0]) / 1000.0,
        (camera.target[1] - camera.eye[1]) / 1000.0,
        (camera.target[2] - camera.eye[2]) / 1000.0,
    ];
    assert_close(
        &forward,
        &[-raw_forward[0], -raw_forward[1], raw_forward[2]],
        TOLERANCE,
        "look direction",
    );
    assert!(
        forward[0].abs() > 0.1,
        "the raw yaw must actually turn the camera"
    );
    assert_eq!(camera.roll_radians, 0.0, "roll is camera-local");
}

#[test]
fn test_half_turn_about_z_authors_the_identity() {
    // A raw half-turn about Z cancels q_z180 exactly, which is how fixtures author an
    // upright [I1] actor.
    let slot = SlotState {
        rot_bam: [0x8000, 0, 0],
        ..Default::default()
    };
    assert_eq!(slot.rotation_quat(), [0.0, 0.0, 0.0, 1.0]);
}

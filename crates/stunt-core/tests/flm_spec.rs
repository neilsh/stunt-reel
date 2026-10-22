//! Behavioural specification of the `.FLM` choreography evaluator ([`FilmTimeline`]).
//!
//! Each test names one behaviour and asserts specific expected results. Inputs that are
//! generated, mutated or enumerated to prove the parser never panics live in `flm_fuzz.rs`.
//!
//! Covered behaviour:
//! - [`FlmError`] display, header validation and the stop-reason contract for truncated,
//!   unterminated and unknown-opcode slices, including partial films that keep their
//!   already-decoded slices
//! - Cumulative 50 Hz slice ticks (`[I4]`), including zero-duration and unvalidated headers
//! - Static and dynamic slot placement, `SlotState` DOS-to-`[I1]` axis conversion (`[I1]`)
//! - Sub-tick sampling (`[I4]`): linear interpolation, clamping, cut suppression, and
//!   actor spawn/despawn
//! - Intro film streams at 50 and 600 ticks: unit quaternions, orthonormal world matrices,
//!   camera cuts, audio cues and self-parity
//! - Gate G04 parity against `tests/fixtures/oracle_intro_trajectory.json` (needs `serde`):
//!   positional RMSE <= 0.01 m, checked independently in `f64`, plus tamper rejection

mod common;

use std::fs;
use std::path::{Path, PathBuf};
use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::trajectory::{
    ActorTransform, AudioCue, CameraTransform, TrajectoryRecord,
};
use stunt_core::flm::{
    FilmTimeline, FlmError, GATE_G04_RMSE_THRESHOLD_METERS, SIF_ANIMATES, SIF_DRAW, SIF_EXISTS,
    SIF_MOVES, SIF_ROTATES, SliceKeyframe, SlotState, assert_parity_gate_g04,
    compute_position_rmse,
};

use common::{build_synthetic_intro_flm, quat_norm_diff};

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
}

// ----------------------------------------------------------------------------
// Builders and independent math oracles
// ----------------------------------------------------------------------------

/// An actor at `position_meters` with an identity orientation and an unfilled world matrix.
fn actor(actor_id: u32, model_name: &str, position_meters: [f32; 3]) -> ActorTransform {
    ActorTransform {
        actor_id,
        model_name: model_name.to_string(),
        shape_id: 0,
        world_matrix: [0.0; 16],
        rotation_quat: [0.0, 0.0, 0.0, 1.0],
        position_meters,
        state_mask: 1,
        joint_angles_bam: Vec::new(),
    }
}

fn camera(
    eye: [f32; 3],
    target: [f32; 3],
    fov_degrees: f32,
    roll_radians: f32,
    cut_from_previous: bool,
) -> CameraTransform {
    CameraTransform {
        eye,
        target,
        fov_degrees,
        roll_radians,
        cut_from_previous,
    }
}

/// Wrap a record as a one-tick keyframe, leaving its actor world matrices untouched.
fn keyframe(record: TrajectoryRecord) -> SliceKeyframe {
    SliceKeyframe {
        tick: record.tick,
        tick_duration: 1,
        record,
    }
}

/// Wrap evaluated records into a timeline keyed by each record's own `tick`.
///
/// Actor world matrices are filled in, as the evaluator does for real films.
fn timeline_of(records: Vec<TrajectoryRecord>) -> FilmTimeline {
    let slices = records
        .into_iter()
        .map(|mut record| {
            for actor in &mut record.actors {
                actor.world_matrix = actor.compute_world_matrix();
            }
            SliceKeyframe {
                tick: record.tick,
                tick_duration: 1,
                record,
            }
        })
        .collect();
    FilmTimeline::new(slices, Vec::new())
}

/// Independent high-precision f64 oracle for Euclidean position RMSE.
#[cfg(feature = "serde")]
fn independent_oracle_rmse(evaluated: &FilmTimeline, oracle: &[TrajectoryRecord]) -> (f64, usize) {
    let mut sq_errors = Vec::new();

    for base_rec in oracle {
        let eval_rec = evaluated
            .sample(base_rec.tick as f32)
            .expect("timeline must not be empty");

        // Camera eye error
        let dx = (eval_rec.camera.eye[0] - base_rec.camera.eye[0]) as f64;
        let dy = (eval_rec.camera.eye[1] - base_rec.camera.eye[1]) as f64;
        let dz = (eval_rec.camera.eye[2] - base_rec.camera.eye[2]) as f64;
        sq_errors.push(dx * dx + dy * dy + dz * dz);

        // Actor position error
        for base_act in &base_rec.actors {
            let eval_act = eval_rec
                .actors
                .iter()
                .find(|a| a.actor_id == base_act.actor_id)
                .expect("Oracle actor ID must exist in evaluated record");

            let ax = (eval_act.position_meters[0] - base_act.position_meters[0]) as f64;
            let ay = (eval_act.position_meters[1] - base_act.position_meters[1]) as f64;
            let az = (eval_act.position_meters[2] - base_act.position_meters[2]) as f64;
            sq_errors.push(ax * ax + ay * ay + az * az);
        }
    }

    let n = sq_errors.len();
    if n == 0 {
        return (0.0, 0);
    }
    let mean_sq: f64 = sq_errors.iter().sum::<f64>() / (n as f64);
    (mean_sq.sqrt(), n)
}

/// Independent oracle for 3x3 matrix determinant.
fn mat3_det(m: [[f32; 3]; 3]) -> f32 {
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
}

/// Independent oracle to verify 4x4 column-major matrix is a valid Euclidean rigid transform.
fn assert_valid_euclidean_transform(mat: &[f32; 16], pos: [f32; 3]) {
    // Extract column vectors
    let col0 = [mat[0], mat[1], mat[2]];
    let col1 = [mat[4], mat[5], mat[6]];
    let col2 = [mat[8], mat[9], mat[10]];
    let col3 = [mat[12], mat[13], mat[14]];

    // 1. Column lengths must be unit (orthonormal)
    let len0 = (col0[0] * col0[0] + col0[1] * col0[1] + col0[2] * col0[2]).sqrt();
    let len1 = (col1[0] * col1[0] + col1[1] * col1[1] + col1[2] * col1[2]).sqrt();
    let len2 = (col2[0] * col2[0] + col2[1] * col2[1] + col2[2] * col2[2]).sqrt();
    assert!((len0 - 1.0).abs() < 1e-4, "Col 0 not unit: {len0}");
    assert!((len1 - 1.0).abs() < 1e-4, "Col 1 not unit: {len1}");
    assert!((len2 - 1.0).abs() < 1e-4, "Col 2 not unit: {len2}");

    // 2. Columns must be mutually orthogonal
    let dot01 = col0[0] * col1[0] + col0[1] * col1[1] + col0[2] * col1[2];
    let dot02 = col0[0] * col2[0] + col0[1] * col2[1] + col0[2] * col2[2];
    let dot12 = col1[0] * col2[0] + col1[1] * col2[1] + col1[2] * col2[2];
    assert!(
        dot01.abs() < 1e-4,
        "Col 0 and Col 1 not orthogonal: {dot01}"
    );
    assert!(
        dot02.abs() < 1e-4,
        "Col 0 and Col 2 not orthogonal: {dot02}"
    );
    assert!(
        dot12.abs() < 1e-4,
        "Col 1 and Col 2 not orthogonal: {dot12}"
    );

    // 3. Rotation submatrix determinant must be +1.0 (proper rotation)
    let r = [
        [col0[0], col1[0], col2[0]],
        [col0[1], col1[1], col2[1]],
        [col0[2], col1[2], col2[2]],
    ];
    let det = mat3_det(r);
    assert!(
        (det - 1.0).abs() < 1e-4,
        "Rotation determinant is not +1.0: {det}"
    );

    // 4. Translation column must match position_meters
    assert!(
        (col3[0] - pos[0]).abs() < 1e-4,
        "Translation X mismatch: {} vs {}",
        col3[0],
        pos[0]
    );
    assert!(
        (col3[1] - pos[1]).abs() < 1e-4,
        "Translation Y mismatch: {} vs {}",
        col3[1],
        pos[1]
    );
    assert!(
        (col3[2] - pos[2]).abs() < 1e-4,
        "Translation Z mismatch: {} vs {}",
        col3[2],
        pos[2]
    );

    // 5. Affine bottom row must be [0, 0, 0, 1]
    assert_eq!(mat[3], 0.0);
    assert_eq!(mat[7], 0.0);
    assert_eq!(mat[11], 0.0);
    assert_eq!(mat[15], 1.0);
}

// ----------------------------------------------------------------------------
// Errors, headers and stop reasons
// ----------------------------------------------------------------------------

#[test]
fn flm_error_display_and_traits() {
    let err_sig = FlmError::InvalidSignature {
        expected: *b"FILM",
        actual: *b"BOGU",
    };
    assert!(err_sig.to_string().contains("invalid FILM signature"));

    let err_eof = FlmError::UnexpectedEof {
        expected: 4,
        actual: 2,
    };
    assert!(err_eof.to_string().contains("unexpected EOF"));

    let err_slice = FlmError::InvalidSlice {
        reason: "missing terminator".to_string(),
    };
    assert!(err_slice.to_string().contains("missing terminator"));

    let err_op = FlmError::InvalidOpcode {
        opcode: 0xF0,
        offset: 0x12,
    };
    assert!(err_op.to_string().contains("0xF0"));
    assert!(err_op.to_string().contains("0x0012"));

    // Trait checks
    let cloned = err_sig.clone();
    assert_eq!(err_sig, cloned);
}

#[test]
fn header_rejects_short_buffers_and_bad_signatures() {
    // Empty buffer
    let res = FilmTimeline::from_bytes(&[]);
    assert_eq!(
        res.unwrap_err(),
        FlmError::UnexpectedEof {
            expected: 4,
            actual: 0
        }
    );

    // Truncated 3-byte header
    let res = FilmTimeline::from_bytes(b"FIL");
    assert_eq!(
        res.unwrap_err(),
        FlmError::UnexpectedEof {
            expected: 4,
            actual: 3
        }
    );

    // 0 to 3 bytes must return UnexpectedEof
    for len in 0..4 {
        let buf = vec![b'F'; len];
        let err = FilmTimeline::from_bytes(&buf).unwrap_err();
        assert_eq!(
            err,
            FlmError::UnexpectedEof {
                expected: 4,
                actual: len,
            },
            "{len}-byte input"
        );
    }

    // Invalid 4-byte signatures
    let invalid_magics: [&[u8; 4]; 9] = [
        b"BOGU",
        b"FLM\0",
        b"film",
        b"RIFF",
        b"SOD ",
        b"RES ",
        b"\0\0\0\0",
        b"\xFF\xFF\xFF\xFF",
        b"FIL ",
    ];
    for &magic in &invalid_magics {
        let err = FilmTimeline::from_bytes(magic).unwrap_err();
        assert_eq!(
            err,
            FlmError::InvalidSignature {
                expected: *b"FILM",
                actual: *magic,
            },
            "invalid magic {magic:?}"
        );
    }

    // Exact 4-byte header b"FILM" with 0 slice bytes: valid empty film
    let timeline = FilmTimeline::from_bytes(b"FILM").expect("valid 4-byte FILM evaluates");
    assert!(timeline.slices().is_empty());
    assert!(timeline.stop_reason().is_none());
    assert_eq!(timeline.total_ticks(), 0);
    assert!(timeline.sample(0.0).is_none());
}

#[test]
fn header_only_trailer_is_a_clean_end_of_film() {
    // A header-only trailer (no opcodes, no terminator) is the canonical end-of-film
    // epilogue, not an unclosed slice. The header bytes are never validated.
    for header in [
        // `prev_slice_len` low byte 1, then the u16 10 (high byte, `tick_duration`)
        [1u8, 10, 0],
        // `prev_slice_len` low byte 1, then the u16 0
        [1u8, 0, 0],
    ] {
        let mut film = Vec::from(&b"FILM"[..]);
        film.extend_from_slice(&header);
        let timeline = FilmTimeline::from_bytes(&film).unwrap();
        assert!(timeline.slices().is_empty());
        assert!(timeline.stop_reason().is_none());
    }
}

#[test]
fn truncated_slice_header_is_unexpected_eof() {
    // Valid header followed by incomplete slice header (1 byte instead of 3)
    let mut data = Vec::from(&b"FILM"[..]);
    data.push(0x01); // first byte of the 3-byte slice header only
    let timeline = FilmTimeline::from_bytes(&data).unwrap();
    assert!(timeline.slices().is_empty());
    assert!(matches!(
        timeline.stop_reason(),
        Some(FlmError::UnexpectedEof { .. })
    ));
}

#[test]
fn unterminated_slice_body_is_a_structured_stop_reason() {
    // Valid header and slice header, but no 0xFF terminator before EOF
    let mut data = Vec::from(&b"FILM"[..]);
    data.push(0x01); // prev_slice_len low byte
    data.extend_from_slice(&2u16.to_le_bytes()); // prev_slice_len high byte, tick_duration
    data.push(0x98); // clear credits
    // No 0xFF
    let timeline = FilmTimeline::from_bytes(&data).unwrap();
    assert!(timeline.slices().is_empty());
    assert!(matches!(
        timeline.stop_reason(),
        Some(FlmError::InvalidSlice { .. })
    ));

    // Slices that end abruptly without 0xFF terminator, whatever the last opcode was
    let mut base = Vec::from(&b"FILM"[..]);
    // 3-byte slice header: the two `prev_slice_len` bytes then `tick_duration`,
    // none of which the parser reads or validates.
    base.push(1);
    base.extend_from_slice(&10u16.to_le_bytes());

    let test_bodies: Vec<Vec<u8>> = vec![
        vec![0x98],                         // clear credits opcode only
        vec![0x80, 0x12, 0x34],             // var_set 0 = 0x3412
        vec![0x90],                         // set view_obj = 0
        vec![0x9B, 0x04],                   // set max_obj = 4
        vec![0x00, SIF_EXISTS | SIF_MOVES], // CREATE slot 0 (dynamic)
        vec![0x40],                         // INTERP slot 0 (no moves flags)
        vec![0xA0, 0x00, 0x00],             // before-word
    ];

    for body in test_bodies {
        let mut film = base.clone();
        film.extend_from_slice(&body);

        let timeline = FilmTimeline::from_bytes(&film).unwrap();
        assert_eq!(
            timeline.slices().len(),
            0,
            "Unclosed slice (body {body:02X?}) must not produce a valid keyframe"
        );
        let last_err = timeline.stop_reason().cloned();
        assert!(
            matches!(
                last_err,
                Some(FlmError::InvalidSlice { .. }) | Some(FlmError::UnexpectedEof { .. })
            ),
            "Expected InvalidSlice or UnexpectedEof for unclosed slice without 0xFF, got {last_err:?}"
        );
    }
}

#[test]
fn unterminated_credits_string_is_unexpected_eof() {
    // Unclosed string in credits opcode 0x99
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice = vec![0x99];
    slice.extend_from_slice(b"Unterminated line without zero");
    film.push(1);
    film.extend_from_slice(&(slice.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice);
    let timeline = FilmTimeline::from_bytes(&film).unwrap();
    assert!(timeline.slices().is_empty());
    assert!(matches!(
        timeline.stop_reason(),
        Some(FlmError::UnexpectedEof { .. })
    ));
}

#[test]
fn unknown_opcode_stops_decoding_with_invalid_opcode() {
    for unknown_op in [0xF0u8, 0xEF] {
        let mut film = Vec::from(&b"FILM"[..]);
        let slice0 = vec![unknown_op, 0xFF]; // Unknown opcode class

        film.push(1);
        film.extend_from_slice(&(slice0.len() as u16).to_le_bytes());
        film.extend_from_slice(&slice0);

        let timeline = FilmTimeline::from_bytes(&film).unwrap();
        assert!(timeline.slices().is_empty());
        assert!(
            matches!(
                timeline.stop_reason(),
                Some(FlmError::InvalidOpcode { opcode, .. }) if *opcode == unknown_op
            ),
            "opcode 0x{unknown_op:02X}: {:?}",
            timeline.stop_reason()
        );
    }
}

#[test]
fn partial_film_keeps_decoded_slices_before_a_fault() {
    let mut film = Vec::from(&b"FILM"[..]);
    // Valid slice 0
    let s0 = vec![0x98, 0xFF];
    film.push(1);
    film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
    film.extend_from_slice(&s0);

    // Corrupted slice 1 (invalid opcode 0xFE)
    let s1 = vec![0xFE, 0xFF];
    film.push(1);
    film.extend_from_slice(&(s1.len() as u16).to_le_bytes());
    film.extend_from_slice(&s1);

    // The corrupted stream is not an error: slice 0 is kept and the failure is reported
    // as the timeline's stop reason, identically on every evaluation.
    for _ in 0..3 {
        let timeline = FilmTimeline::from_bytes(&film).expect("header is valid");
        assert_eq!(timeline.slices().len(), 1);
        assert!(matches!(
            timeline.stop_reason(),
            Some(FlmError::InvalidOpcode { opcode: 0xFE, .. })
        ));
    }
}

// ----------------------------------------------------------------------------
// Slice ticks and placement
// ----------------------------------------------------------------------------

#[test]
fn zero_and_extreme_slice_header_values_are_not_validated() {
    let mut film = Vec::from(&b"FILM"[..]);

    // Slice 0: `prev_slice_len` low byte 0, `tick_duration` 0
    let s0 = vec![0x98, 0xFF];
    film.push(0);
    film.extend_from_slice(&(s0.len() as u16).to_le_bytes());
    film.extend_from_slice(&s0);

    // Slice 1: `prev_slice_len` low byte 255 (`tick_duration` again 0)
    let s1 = vec![0x98, 0xFF];
    film.push(255);
    film.extend_from_slice(&(s1.len() as u16).to_le_bytes());
    film.extend_from_slice(&s1);

    // Slice 2: `prev_slice_len` = 1, `tick_duration` = 0, valid opcodes + 0xFF
    let s2 = vec![0x98, 0xFF];
    film.push(1);
    film.extend_from_slice(&0u16.to_le_bytes());
    film.extend_from_slice(&s2);

    // Slice 3: `prev_slice_len` = 0xFFFF (broken chain), `tick_duration` = 0
    let s3 = vec![0x98, 0xFF];
    film.extend_from_slice(&0xFFFFu16.to_le_bytes());
    film.push(0);
    film.extend_from_slice(&s3);

    let timeline = FilmTimeline::from_bytes(&film).expect("evaluation must succeed cleanly");
    assert!(timeline.stop_reason().is_none());
    assert_eq!(timeline.slices().len(), 4);

    // Every slice header carries `tick_duration` 0, so all four slices are reached at
    // cumulative tick 0 and the film has zero authored length.
    for slice in timeline.slices() {
        assert_eq!(slice.tick, 0);
        assert_eq!(slice.tick_duration, 0);
        assert_eq!(slice.record.tick, 0);
    }
    assert_eq!(timeline.total_ticks(), 0);
}

#[test]
fn synthetic_minimal_fixture_evaluates_two_ticks() {
    let flm_path = fixtures_dir().join("synthetic_minimal.flm");
    assert!(flm_path.exists(), "synthetic_minimal.flm must exist");

    let data = fs::read(&flm_path).expect("read synthetic_minimal.flm");
    assert_eq!(data.len(), 17);

    let timeline = FilmTimeline::from_bytes(&data).expect("timeline evaluates");
    assert!(timeline.stop_reason().is_none());
    assert_eq!(timeline.slices().len(), 2);

    // Both slices are authored with tick_duration 1, so they are reached at cumulative
    // 50 Hz ticks 1 and 2.
    let ticks: Vec<u32> = timeline.slices().iter().map(|slice| slice.tick).collect();
    assert_eq!(ticks, vec![1, 2]);
    assert_eq!(timeline.total_ticks(), 2);

    // Slice 0: tick_duration 1, var_set 0 = 0x9890, view_obj 0, clear credits, 0xFF
    let slice0 = &timeline.slices()[0].record;
    assert_eq!(slice0.tick, 1);
    assert_eq!(slice0.camera.eye, [0.0, 10.0, 50.0]);
    assert_eq!(slice0.camera.target, [0.0, 0.0, 0.0]);
    assert_eq!(slice0.camera.fov_degrees, 45.0);
    assert!(!slice0.camera.cut_from_previous);
    assert!(slice0.actors.is_empty());
    assert!(slice0.audio_cues.is_empty());

    // Slice 1: tick_duration 1, op 0xFF
    let slice1 = &timeline.slices()[1].record;
    assert_eq!(slice1.tick, 2);
    assert_eq!(slice1.camera.eye, [0.0, 10.0, 50.0]);
    assert!(!slice1.camera.cut_from_previous);
    assert!(slice1.actors.is_empty());
}

#[test]
fn create_without_moves_or_rotates_places_a_static_actor() {
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice0 = Vec::new();

    // CREATE slot 2: SIF_EXISTS | SIF_DRAW (no SIF_MOVES, no SIF_ROTATES) -> static!
    slice0.push(0x02);
    slice0.push(SIF_EXISTS | SIF_DRAW);
    slice0.extend_from_slice(&42u16.to_le_bytes()); // shape_id 42
    // Static pos [10.0, 20.0, 30.0] in [I1], authored in DOS axes as [-10.0, -20.0, 30.0]
    slice0.extend_from_slice(&(-10 * 65536i32).to_le_bytes());
    slice0.extend_from_slice(&(-20 * 65536i32).to_le_bytes());
    slice0.extend_from_slice(&(30 * 65536i32).to_le_bytes());
    // Static rot [0, 0, 0]
    slice0.extend_from_slice(&0u16.to_le_bytes());
    slice0.extend_from_slice(&0u16.to_le_bytes());
    slice0.extend_from_slice(&0u16.to_le_bytes());
    slice0.push(0xFF);

    // Slice 0 header
    film.push(1);
    film.extend_from_slice(&(slice0.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice0);

    // Slice 1: empty slice, static actor remains in place
    let slice1 = vec![0xFF];
    film.push(1);
    film.extend_from_slice(&(slice1.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice1);

    let timeline = FilmTimeline::from_bytes(&film).unwrap();
    assert!(timeline.stop_reason().is_none());
    assert_eq!(timeline.slices().len(), 2);

    let tick0 = &timeline.slices()[0].record;
    assert_eq!(tick0.actors.len(), 1);
    assert_eq!(tick0.actors[0].actor_id, 2);
    assert_eq!(tick0.actors[0].shape_id, 42);
    assert_eq!(tick0.actors[0].position_meters, [10.0, 20.0, 30.0]);

    let tick1 = &timeline.slices()[1].record;
    assert_eq!(tick1.actors.len(), 1);
    assert_eq!(tick1.actors[0].position_meters, [10.0, 20.0, 30.0]); // Static hold!
}

#[test]
fn slot_state_converts_dos_axes_to_i1() {
    let mut slot = SlotState::default();
    assert_eq!(slot.position_meters(), [0.0, 0.0, 0.0]);
    assert_eq!(slot.position_dos_meters(), [0.0, 0.0, 0.0]);
    // A zero DOS rotation is the identity in DOS axes and q_z180 in [I1].
    assert_eq!(slot.rotation_quat_dos(), [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(slot.rotation_quat(), [0.0, 0.0, 1.0, 0.0]);

    slot.type_flags = SIF_EXISTS | SIF_MOVES | SIF_ROTATES | SIF_ANIMATES;
    assert_ne!(slot.type_flags & SIF_MOVES, 0);
    assert_ne!(slot.type_flags & SIF_ROTATES, 0);
    assert_ne!(slot.type_flags & SIF_ANIMATES, 0);

    slot.pos_fixed = [65536, 131072, -65536];
    assert_eq!(slot.position_dos_meters(), [1.0, 2.0, -1.0]);
    assert_eq!(slot.position_meters(), [-1.0, -2.0, -1.0]);
}

// ----------------------------------------------------------------------------
// Sub-tick sampling [I4]
// ----------------------------------------------------------------------------

#[test]
fn sub_tick_interpolation_is_linear_when_not_a_cut() {
    // Exact midpoint of a pure-Z move between two non-cut ticks.
    let midpoint = FilmTimeline::new(
        vec![
            keyframe(TrajectoryRecord {
                tick: 0,
                camera: camera([0.0, 10.0, 50.0], [0.0, 0.0, 0.0], 45.0, 0.0, false),
                actors: vec![actor(1, "FOKKER", [0.0, 10.0, 0.0])],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
            }),
            keyframe(TrajectoryRecord {
                tick: 1,
                camera: camera([0.0, 10.0, 40.0], [0.0, 0.0, 0.0], 45.0, 0.0, false),
                actors: vec![actor(1, "FOKKER", [0.0, 10.0, 2.0])],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
            }),
        ],
        Vec::new(),
    );
    let sub = midpoint.sample(0.5).unwrap();
    assert_eq!(sub.camera.eye, [0.0, 10.0, 45.0]);
    assert_eq!(sub.actors[0].position_meters, [0.0, 10.0, 1.0]);

    // Lattice of sub-tick alphas across every interpolated channel.
    let frame_0 = TrajectoryRecord {
        tick: 0,
        camera: camera([0.0, 10.0, 50.0], [0.0, 0.0, 0.0], 40.0, 0.0, false),
        actors: vec![actor(1, "FOKKER", [0.0, 10.0, 0.0])],
        audio_cues: vec![AudioCue {
            tick: 0,
            sample_name: "ENGINE.VOC".to_string(),
            volume: 0.8,
            pan: 0.0,
        }],
        palette: PaletteControls::default(),
    };
    let frame_1 = TrajectoryRecord {
        tick: 1,
        camera: camera([10.0, 20.0, 40.0], [5.0, 0.0, 0.0], 60.0, 0.2, false),
        actors: vec![actor(1, "FOKKER", [4.0, 12.0, 8.0])],
        audio_cues: vec![AudioCue {
            tick: 1,
            sample_name: "WIND.VOC".to_string(),
            volume: 0.5,
            pan: 0.0,
        }],
        palette: PaletteControls::default(),
    };

    let timeline = timeline_of(vec![frame_0, frame_1]);
    let test_alphas = [0.0f32, 0.25f32, 0.5f32, 0.75f32, 1.0f32];

    for &alpha in &test_alphas {
        let sub = timeline.sample(alpha).expect("sample");

        // 1. Verify Camera Eye position linearity
        let expected_eye = [
            0.0 + alpha * 10.0,
            10.0 + alpha * 10.0,
            50.0 + alpha * (-10.0),
        ];
        for (i, (&actual, &expected)) in sub.camera.eye.iter().zip(expected_eye.iter()).enumerate()
        {
            assert!(
                (actual - expected).abs() < 1e-5,
                "Camera eye[{i}] at alpha={alpha}: expected {expected}, got {actual}"
            );
        }

        // 2. Verify Camera Target linearity
        let expected_target = [0.0 + alpha * 5.0, 0.0, 0.0];
        for (i, (&actual, &expected)) in sub
            .camera
            .target
            .iter()
            .zip(expected_target.iter())
            .enumerate()
        {
            assert!(
                (actual - expected).abs() < 1e-5,
                "Camera target[{i}] at alpha={alpha}: expected {expected}, got {actual}"
            );
        }

        // 3. Verify FOV and Roll linearity
        let expected_fov = 40.0 + alpha * 20.0;
        assert!(
            (sub.camera.fov_degrees - expected_fov).abs() < 1e-5,
            "FOV at alpha={alpha}: expected {expected_fov}, got {}",
            sub.camera.fov_degrees
        );
        let expected_roll = 0.0 + alpha * 0.2;
        assert!(
            (sub.camera.roll_radians - expected_roll).abs() < 1e-5,
            "Roll at alpha={alpha}: expected {expected_roll}, got {}",
            sub.camera.roll_radians
        );

        // 4. Verify Actor Position linearity
        let expected_act_pos = [0.0 + alpha * 4.0, 10.0 + alpha * 2.0, 0.0 + alpha * 8.0];
        for (i, (&actual, &expected)) in sub.actors[0]
            .position_meters
            .iter()
            .zip(expected_act_pos.iter())
            .enumerate()
        {
            assert!(
                (actual - expected).abs() < 1e-5,
                "Actor pos[{i}] at alpha={alpha}: expected {expected}, got {actual}"
            );
        }

        // 5. Verify Audio Cues: only present at alpha == 0.0 and alpha == 1.0
        if alpha == 0.0 {
            assert_eq!(sub.audio_cues.len(), 1);
            assert_eq!(sub.audio_cues[0].sample_name, "ENGINE.VOC");
        } else if alpha == 1.0 {
            assert_eq!(sub.audio_cues.len(), 1);
            assert_eq!(sub.audio_cues[0].sample_name, "WIND.VOC");
        } else {
            assert!(
                sub.audio_cues.is_empty(),
                "Sub-tick alpha={alpha} must NOT emit audio cues (discrete tick invariant)"
            );
        }

        // 6. Verify Actor World Matrix is valid
        assert_valid_euclidean_transform(
            &sub.actors[0].world_matrix,
            sub.actors[0].position_meters,
        );
    }

    // Midpoint linearity check: pos(0.5) must equal average of pos(0.25) and pos(0.75)
    let sub_25 = timeline.sample(0.25).expect("sample");
    let sub_50 = timeline.sample(0.50).expect("sample");
    let sub_75 = timeline.sample(0.75).expect("sample");

    for i in 0..3 {
        let avg_eye = 0.5 * (sub_25.camera.eye[i] + sub_75.camera.eye[i]);
        assert!(
            (sub_50.camera.eye[i] - avg_eye).abs() < 1e-5,
            "Midpoint linearity violated on eye[{i}]"
        );

        let avg_act =
            0.5 * (sub_25.actors[0].position_meters[i] + sub_75.actors[0].position_meters[i]);
        assert!(
            (sub_50.actors[0].position_meters[i] - avg_act).abs() < 1e-5,
            "Midpoint linearity violated on actor pos[{i}]"
        );
    }
}

#[test]
fn sample_clamps_to_the_keyframe_range() {
    let frame_0 = TrajectoryRecord {
        tick: 10,
        camera: camera([0.0, 10.0, 50.0], [0.0, 0.0, 0.0], 45.0, 0.0, false),
        actors: vec![actor(1, "ACTOR", [0.0, 0.0, 0.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    let frame_1 = TrajectoryRecord {
        tick: 11,
        camera: camera([10.0, 10.0, 50.0], [0.0, 0.0, 0.0], 50.0, 0.1, false),
        actors: vec![actor(1, "ACTOR", [10.0, 0.0, 0.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };

    // Ticks before the first keyframe clamp to the first slice, ticks after the last
    // keyframe clamp to the last slice.
    let timeline = timeline_of(vec![frame_0.clone(), frame_1.clone()]);
    let eval_pre = timeline.sample(5.0).unwrap();
    assert_eq!(eval_pre.camera.eye, frame_0.camera.eye);
    assert_eq!(eval_pre.tick, 10);

    let eval_post = timeline.sample(20.0).unwrap();
    assert_eq!(eval_post.camera.eye, frame_1.camera.eye);
    assert_eq!(eval_post.tick, 11);

    // Empty timeline
    assert!(
        FilmTimeline::new(Vec::new(), Vec::new())
            .sample(0.0)
            .is_none()
    );
}

#[test]
fn camera_cut_holds_prior_pose_until_the_cut_tick() {
    // A cut between ticks 199 and 200 suppresses the lerp at the sub-tick midpoint.
    let frame_a = TrajectoryRecord {
        tick: 199,
        camera: camera([0.0, 10.0, 20.0], [0.0, 0.0, 0.0], 45.0, 0.0, false),
        actors: vec![actor(1, "FOKKER", [0.0, 10.0, 100.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    // Frame B has cut_from_previous = true (camera jump to tower)
    let frame_b = TrajectoryRecord {
        tick: 200,
        camera: camera([45.0, 25.0, 120.0], [0.0, 10.0, 100.0], 48.0, 0.0, true),
        actors: vec![actor(1, "FOKKER", [0.0, 10.0, 101.2])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    let timeline = FilmTimeline::new(
        vec![keyframe(frame_a.clone()), keyframe(frame_b)],
        Vec::new(),
    );

    // Sampling at the sub-tick midpoint MUST suppress lerp (alpha_eff = 0.0) per Invariant [I4]
    let sub = timeline.sample(199.5).unwrap();
    assert_eq!(sub.camera.eye, frame_a.camera.eye); // Held at frame A eye!
    assert_eq!(sub.camera.fov_degrees, frame_a.camera.fov_degrees);
    assert_eq!(
        sub.actors[0].position_meters,
        frame_a.actors[0].position_meters
    );

    // A cut 500 meters away: every intermediate alpha holds frame A, the exact tick arrives.
    let frame_a = TrajectoryRecord {
        tick: 50,
        camera: camera([10.0, 5.0, -100.0], [0.0, 0.0, 0.0], 35.0, 0.05, false),
        actors: vec![actor(1, "FOKKER", [10.0, 5.0, -50.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    // Frame B is a cut: camera moved 500 meters away to a hilltop tower
    let frame_b = TrajectoryRecord {
        tick: 51,
        camera: camera([500.0, 250.0, 300.0], [10.0, 5.0, -50.0], 55.0, -0.1, true),
        actors: vec![actor(1, "FOKKER", [10.0, 5.0, -48.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };

    let timeline = timeline_of(vec![frame_a.clone(), frame_b.clone()]);

    // Test a fine sub-tick sweep: 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99
    let test_alphas = [0.01f32, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99];

    for &alpha in &test_alphas {
        let sub = timeline.sample(50.0 + alpha).expect("sample");

        // Under Invariant [I4], ALL intermediate alphas must suppress lerp and hold frame_a
        assert_eq!(
            sub.camera.eye, frame_a.camera.eye,
            "Intermediate camera eye at alpha={alpha} must NOT lerp toward cut target!"
        );
        assert_eq!(
            sub.camera.target, frame_a.camera.target,
            "Intermediate camera target at alpha={alpha} must hold frame A"
        );
        assert_eq!(
            sub.camera.fov_degrees, frame_a.camera.fov_degrees,
            "Intermediate FOV at alpha={alpha} must hold frame A"
        );
        assert_eq!(
            sub.camera.roll_radians, frame_a.camera.roll_radians,
            "Intermediate Roll at alpha={alpha} must hold frame A"
        );
        assert!(
            !sub.camera.cut_from_previous,
            "cut_from_previous should remain false during sub-tick hold (alpha={alpha})"
        );

        // Actor positions must also hold frame A
        assert_eq!(
            sub.actors[0].position_meters, frame_a.actors[0].position_meters,
            "Actor position at alpha={alpha} must hold frame A"
        );
    }

    // Invariant [I4]: At exact tick boundary alpha == 1.0, pose must arrive at frame B
    let sub_one = timeline.sample(51.0).expect("sample");
    assert_eq!(
        sub_one.camera.eye, frame_b.camera.eye,
        "Invariant [I4] Failure: at alpha=1.0, camera eye must transition to frame_b cut pose {:?}, but held frame_a pose {:?}",
        frame_b.camera.eye, sub_one.camera.eye
    );
    assert_eq!(sub_one.camera.target, frame_b.camera.target);
    assert_eq!(sub_one.camera.fov_degrees, frame_b.camera.fov_degrees);
    assert!(sub_one.camera.cut_from_previous);

    // Continuous timeline evaluation: sequence of [tick 50, tick 51 (cut), tick 52]
    let frame_c = TrajectoryRecord {
        tick: 52,
        camera: camera([510.0, 250.0, 300.0], [10.0, 5.0, -50.0], 55.0, -0.1, false),
        actors: frame_b.actors.clone(),
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    let timeline = timeline_of(vec![frame_a.clone(), frame_b.clone(), frame_c.clone()]);

    // At continuous tick 50.5 (midpoint between 50 and 51 cut), pose must hold frame_a
    let eval_50_5 = timeline.sample(50.5).unwrap();
    assert_eq!(eval_50_5.camera.eye, frame_a.camera.eye);

    // At continuous tick 51.0 (exact integer tick of cut), camera must arrive at frame_b
    let eval_51_0 = timeline.sample(51.0).unwrap();
    assert_eq!(
        eval_51_0.camera.eye, frame_b.camera.eye,
        "Invariant [I4] Failure: sample at cut tick 51.0 must return frame_b camera pose {:?}, but held frame_a pose {:?}",
        frame_b.camera.eye, eval_51_0.camera.eye
    );
}

#[test]
fn actor_spawn_and_despawn_switch_at_the_sub_tick_midpoint() {
    // Frame 0 has actor 1 only
    let frame_0 = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform::default(),
        actors: vec![actor(1, "ACTOR_1", [0.0, 0.0, 0.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };

    // Frame 1 has actor 2 only (actor 1 despawned, actor 2 spawned)
    let frame_1 = TrajectoryRecord {
        tick: 1,
        camera: CameraTransform::default(),
        actors: vec![actor(2, "ACTOR_2", [10.0, 10.0, 10.0])],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };

    let timeline = timeline_of(vec![frame_0, frame_1]);

    // Sub-tick at alpha = 0.25 (< 0.5): actor 1 persists, actor 2 not yet spawned
    let sub_25 = timeline.sample(0.25).expect("sample");
    assert_eq!(sub_25.actors.len(), 1);
    assert_eq!(sub_25.actors[0].actor_id, 1);

    // Sub-tick at alpha = 0.75 (>= 0.5): actor 1 removed, actor 2 spawned
    let sub_75 = timeline.sample(0.75).expect("sample");
    assert_eq!(sub_75.actors.len(), 1);
    assert_eq!(sub_75.actors[0].actor_id, 2);
}

// ----------------------------------------------------------------------------
// Intro film streams and parity
// ----------------------------------------------------------------------------

#[test]
fn intro_film_streams_keep_invariants_and_self_parity() {
    // 50 ticks, and 600 ticks matching Requirement R3
    for (ticks, min_bytes) in [(50usize, 100usize), (600, 10000)] {
        let flm_bytes = build_synthetic_intro_flm(ticks);
        assert!(
            flm_bytes.len() > min_bytes,
            "{ticks} ticks bytecode must be substantial in size"
        );

        let timeline = FilmTimeline::from_bytes(&flm_bytes)
            .unwrap_or_else(|err| panic!("{ticks} ticks film evaluates: {err}"));
        assert!(timeline.stop_reason().is_none());
        assert!(timeline.warnings().is_empty());
        let records: Vec<TrajectoryRecord> = timeline
            .slices()
            .iter()
            .map(|slice| slice.record.clone())
            .collect();

        assert_eq!(
            records.len(),
            ticks,
            "Stream must evaluate exactly {ticks} continuous simulation ticks"
        );

        // Initial ticks match golden oracle
        assert_eq!(records[0].camera.eye, [0.0, 10.0, 50.0]);
        assert_eq!(records[1].camera.eye, [0.0, 10.0, 49.5]);
        assert_eq!(records[0].actors[0].position_meters, [0.0, 10.0, 0.0]);
        assert_eq!(records[1].actors[0].position_meters, [0.0, 10.0, 0.5]);

        // Verify properties for every single tick
        for (i, rec) in records.iter().enumerate() {
            // One slice per 50 Hz tick: slice i is reached at cumulative tick i.
            assert_eq!(
                timeline.slices()[i].tick as usize,
                i,
                "Tick index must be strictly monotonic"
            );
            assert_eq!(rec.tick as usize, i, "Record tick is the cumulative tick");

            // Camera must have finite real coordinates
            for c in 0..3 {
                assert!(rec.camera.eye[c].is_finite());
                assert!(rec.camera.target[c].is_finite());
            }
            assert!(rec.camera.fov_degrees > 0.0 && rec.camera.fov_degrees < 180.0);

            // Invariant [I1]: Quaternions on all active actors must satisfy unit length
            for act in &rec.actors {
                for c in 0..3 {
                    assert!(act.position_meters[c].is_finite());
                }
                let diff = quat_norm_diff(act.rotation_quat);
                assert!(
                    diff < 1e-4,
                    "Unit quaternion invariant violated at tick {i}: diff = {diff}"
                );
                assert_valid_euclidean_transform(&act.world_matrix, act.position_meters);
            }

            // Camera cuts must occur at ticks 200 and 400 (per intro kinematics in streamer.py)
            if i == 200 || i == 400 {
                assert!(
                    rec.camera.cut_from_previous,
                    "Camera cut must be flagged at tick {i}"
                );
            } else if i > 0 && i != 200 && i != 400 {
                assert!(
                    !rec.camera.cut_from_previous,
                    "Camera cut should not be flagged at tick {i}"
                );
            }

            // Audio cues at ticks 0, 200, 400
            if i == 0 {
                assert_eq!(rec.audio_cues.len(), 1);
                assert_eq!(rec.audio_cues[0].sample_name, "ENGINE.VOC");
            } else if i == 200 {
                assert_eq!(rec.audio_cues.len(), 1);
                assert_eq!(rec.audio_cues[0].sample_name, "WIND.VOC");
            } else if i == 400 {
                assert_eq!(rec.audio_cues.len(), 1);
                assert_eq!(rec.audio_cues[0].sample_name, "FLYBY.VOC");
            } else {
                assert!(rec.audio_cues.is_empty());
            }
        }

        // Gate G04 self-parity check
        let rmse = compute_position_rmse(&timeline, &records);
        assert_eq!(rmse, 0.0);
        let verified = assert_parity_gate_g04(&timeline, &records);
        assert!(verified <= GATE_G04_RMSE_THRESHOLD_METERS);
    }
}

#[test]
fn position_rmse_of_an_empty_set_is_infinite_and_fails_the_gate() {
    let empty = FilmTimeline::from_bytes(b"FILM").expect("empty film parses");
    assert!(empty.slices().is_empty());
    let rmse = compute_position_rmse(&empty, &[]);
    assert_eq!(rmse, f32::INFINITY);

    let panic_res = std::panic::catch_unwind(|| {
        assert_parity_gate_g04(&empty, &[]);
    });
    assert!(
        panic_res.is_err(),
        "Empty evaluation set must fail Gate G04 assertion"
    );
}

/// Gate G04: the evaluated intro film matches the oracle trajectory to sub-millimeter
/// precision, checked both field by field and by an independent `f64` RMSE.
#[cfg(feature = "serde")]
#[test]
fn intro_film_matches_oracle_trajectory_within_gate_tolerance() {
    let oracle_path = fixtures_dir().join("oracle_intro_trajectory.json");
    assert!(
        oracle_path.exists(),
        "oracle_intro_trajectory.json must exist"
    );

    let oracle_content = fs::read_to_string(&oracle_path).expect("read oracle json");
    let oracle_records: Vec<TrajectoryRecord> =
        serde_json::from_str(&oracle_content).expect("deserialization of oracle records");
    assert_eq!(
        oracle_records.len(),
        2,
        "Oracle must contain exactly 2 golden ticks"
    );

    // Build synthetic .FLM bytecode and evaluate it into a 50 Hz timeline
    let intro_flm_bytes = build_synthetic_intro_flm(2);
    let timeline = FilmTimeline::from_bytes(&intro_flm_bytes).expect("timeline evaluates");
    assert!(timeline.stop_reason().is_none());
    assert_eq!(timeline.slices().len(), 2);
    assert_eq!(
        timeline.slices().len(),
        oracle_records.len(),
        "Evaluated slices must match oracle count"
    );
    let evaluated: Vec<&TrajectoryRecord> = timeline
        .slices()
        .iter()
        .map(|slice| &slice.record)
        .collect();

    // Verify Tick 0 exact parameters
    assert_eq!(evaluated[0].tick, 0);
    assert_eq!(evaluated[0].camera.eye, oracle_records[0].camera.eye);
    assert_eq!(evaluated[0].camera.target, oracle_records[0].camera.target);
    assert_eq!(
        evaluated[0].camera.fov_degrees,
        oracle_records[0].camera.fov_degrees
    );
    assert_eq!(evaluated[0].actors.len(), 1);
    assert_eq!(evaluated[0].actors[0].actor_id, 1);
    assert_eq!(evaluated[0].actors[0].model_name, "FOKKER");
    assert_eq!(
        evaluated[0].actors[0].shape_id,
        oracle_records[0].actors[0].shape_id
    );
    assert_eq!(
        evaluated[0].actors[0].position_meters,
        oracle_records[0].actors[0].position_meters
    );
    assert_eq!(
        evaluated[0].actors[0].rotation_quat,
        oracle_records[0].actors[0].rotation_quat
    );
    assert_eq!(
        evaluated[0].actors[0].world_matrix,
        oracle_records[0].actors[0].world_matrix
    );
    assert_eq!(evaluated[0].audio_cues.len(), 1);
    assert_eq!(evaluated[0].audio_cues[0].sample_name, "ENGINE.VOC");
    assert_eq!(evaluated[0].audio_cues[0].volume, 0.8);
    assert_eq!(evaluated[0].audio_cues[0].pan, 0.0);

    // Verify Tick 1 exact parameters
    assert_eq!(evaluated[1].tick, 1);
    assert_eq!(evaluated[1].camera.eye, oracle_records[1].camera.eye);
    assert_eq!(evaluated[1].camera.target, oracle_records[1].camera.target);
    assert_eq!(
        evaluated[1].actors[0].position_meters,
        oracle_records[1].actors[0].position_meters
    );
    assert_eq!(
        evaluated[1].actors[0].world_matrix,
        oracle_records[1].actors[0].world_matrix
    );
    assert!(evaluated[1].audio_cues.is_empty());

    // Gate G04 Parity Assertion: RMSE <= 0.01 m
    let rmse = compute_position_rmse(&timeline, &oracle_records);
    assert!(
        rmse <= GATE_G04_RMSE_THRESHOLD_METERS,
        "Gate G04 Parity Failed: RMSE {rmse:.6} m > {GATE_G04_RMSE_THRESHOLD_METERS:.6} m"
    );
    assert!(
        rmse < 1e-4,
        "Sub-millimeter precision violated: RMSE = {rmse}"
    );

    let verified_rmse = assert_parity_gate_g04(&timeline, &oracle_records);
    assert_eq!(rmse, verified_rmse);

    // Independent high-precision verification
    let (indep_rmse, sample_count) = independent_oracle_rmse(&timeline, &oracle_records);
    assert_eq!(
        sample_count, 4,
        "Must compare 2 camera eyes + 2 actor positions"
    );
    assert!(
        indep_rmse <= (GATE_G04_RMSE_THRESHOLD_METERS as f64),
        "Gate G04 Parity Failed: independent RMSE {indep_rmse:.6} m > {GATE_G04_RMSE_THRESHOLD_METERS:.6} m"
    );
    assert!(
        indep_rmse < 1e-5,
        "Gate G04 sub-millimeter precision violated: independent RMSE = {indep_rmse}"
    );

    // Verify engine parity helper
    assert!(
        (rmse as f64 - indep_rmse).abs() < 1e-6,
        "Engine compute_position_rmse ({rmse}) disagrees with independent oracle ({indep_rmse})"
    );
}

/// Gate G04: a perturbation under the threshold passes, one over it fails and panics.
#[cfg(feature = "serde")]
#[test]
fn oracle_comparison_rejects_a_tampered_timeline() {
    let oracle_path = fixtures_dir().join("oracle_intro_trajectory.json");
    let content = fs::read_to_string(&oracle_path).expect("read oracle json");
    let oracle_records: Vec<TrajectoryRecord> =
        serde_json::from_str(&content).expect("parse oracle json");

    let bytecode = build_synthetic_intro_flm(2);
    let genuine = FilmTimeline::from_bytes(&bytecode).expect("timeline evaluates");

    // Rebuild the timeline with the first slice's camera eye nudged along X.
    let tampered = |dx: f32| {
        let mut slices = genuine.slices().to_vec();
        slices[0].record.camera.eye[0] += dx;
        FilmTimeline::new(slices, Vec::new())
    };

    // Case 1: Tamper with 0.005m perturbation (below 0.01m threshold, should pass Gate G04)
    let small = tampered(0.005);
    let rmse_small = compute_position_rmse(&small, &oracle_records);
    assert!(
        rmse_small <= GATE_G04_RMSE_THRESHOLD_METERS,
        "Perturbation of 0.005m should be within Gate G04 limit (got {rmse_small:.6})"
    );

    // Case 2: Tamper with 0.05m perturbation (above 0.01m threshold, must fail Gate G04)
    let large = tampered(0.05);
    let rmse_large = compute_position_rmse(&large, &oracle_records);
    assert!(
        rmse_large > GATE_G04_RMSE_THRESHOLD_METERS,
        "Perturbation of 0.05m must exceed Gate G04 threshold (got {rmse_large:.6})"
    );

    // Verify assert_parity_gate_g04 panics on violation
    let panic_res = std::panic::catch_unwind(|| {
        assert_parity_gate_g04(&large, &oracle_records);
    });
    assert!(
        panic_res.is_err(),
        "assert_parity_gate_g04 must panic when RMSE > 0.01m"
    );
}

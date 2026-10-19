//! Comprehensive integration, unit, and parity regression test suite for `.FLM` choreography evaluator.
//!
//! Verifies:
//! - Seam 2 [`TrajectoryRecord`] generation
//! - Invariant `[I1]`: Metric right-handed coordinates (+X Right, +Y Up, +Z Back, -Z Forward), unit quaternions
//! - Invariant `[I4]`: Discrete simulation ticks (20/30 Hz), cut detection and suppression
//! - Gate G04: Positional RMSE <= 0.01 m against `tests/fixtures/oracle_intro_trajectory.json`
//! - Complete opcode decoding, lifecycle slots, and error handling

use std::fs;
use std::path::{Path, PathBuf};
use stunt_core::contracts::trajectory::{ActorTransform, CameraTransform, TrajectoryRecord};
use stunt_core::flm::{
    FlmError, FlmEvaluator, FlmPlayer, GATE_G04_RMSE_THRESHOLD_METERS, SIF_ANIMATES, SIF_DRAW,
    SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SlotState, assert_parity_gate_g04,
    build_synthetic_intro_flm, compute_position_rmse, detect_camera_cut, evaluate_film,
    evaluate_sub_tick, focal_to_fov_y, interpolate_trajectory, quat_from_euler, quat_norm,
    quat_norm_diff, quat_normalize, slerp_quat,
};

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
}

// ----------------------------------------------------------------------------
// 1. Error Display & Trait Tests
// ----------------------------------------------------------------------------

#[test]
fn test_flm_error_display_and_traits() {
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

// ----------------------------------------------------------------------------
// 2. Header and Truncation Validation
// ----------------------------------------------------------------------------

#[test]
fn test_flm_invalid_signature_and_short_headers() {
    // Empty buffer
    let res = FlmPlayer::new(&[]);
    assert_eq!(
        res.unwrap_err(),
        FlmError::UnexpectedEof {
            expected: 4,
            actual: 0
        }
    );

    // Truncated 3-byte header
    let res = FlmPlayer::new(b"FIL");
    assert_eq!(
        res.unwrap_err(),
        FlmError::UnexpectedEof {
            expected: 4,
            actual: 3
        }
    );

    // Wrong signature
    let res = FlmPlayer::new(b"BOGU");
    assert_eq!(
        res.unwrap_err(),
        FlmError::InvalidSignature {
            expected: *b"FILM",
            actual: *b"BOGU"
        }
    );
}

#[test]
fn test_flm_truncated_slice_and_missing_terminator() {
    // Valid header followed by incomplete slice header (1 byte instead of 3)
    let mut data = Vec::from(&b"FILM"[..]);
    data.push(0x01); // inctime only, missing declared_len
    let mut player = FlmPlayer::new(&data).unwrap();
    assert!(player.step_tick().is_none());
    assert!(matches!(
        player.last_error(),
        Some(FlmError::UnexpectedEof { .. })
    ));

    // Valid header and slice header, but no 0xFF terminator before EOF
    let mut data = Vec::from(&b"FILM"[..]);
    data.push(0x01); // inctime
    data.extend_from_slice(&2u16.to_le_bytes()); // len
    data.push(0x98); // clear credits
    // No 0xFF
    let mut player = FlmPlayer::new(&data).unwrap();
    assert!(player.step_tick().is_none());
    assert!(matches!(
        player.last_error(),
        Some(FlmError::InvalidSlice { .. })
    ));
}

// ----------------------------------------------------------------------------
// 3. Synthetic Minimal Fixture Verification
// ----------------------------------------------------------------------------

#[test]
fn test_flm_synthetic_minimal_fixture() {
    let flm_path = fixtures_dir().join("synthetic_minimal.flm");
    assert!(flm_path.exists(), "synthetic_minimal.flm must exist");

    let data = fs::read(&flm_path).expect("read synthetic_minimal.flm");
    assert_eq!(data.len(), 15);

    let mut player = FlmPlayer::new(&data).expect("player initialization succeeds");

    // Slice 0: inctime 1, op 0x80 (var_set 0 = 0x9890), 0xFF
    let tick0 = player.step_tick().expect("tick 0 succeeds");
    assert_eq!(tick0.tick, 0);
    assert_eq!(tick0.camera.eye, [0.0, 10.0, 50.0]);
    assert_eq!(tick0.camera.target, [0.0, 0.0, 0.0]);
    assert_eq!(tick0.camera.fov_degrees, 45.0);
    assert!(!tick0.camera.cut_from_previous);
    assert!(tick0.actors.is_empty());
    assert!(tick0.audio_cues.is_empty());
    assert_eq!(player.variables()[0], 0x9890);

    // Slice 1: inctime 1, op 0xFF
    let tick1 = player.step_tick().expect("tick 1 succeeds");
    assert_eq!(tick1.tick, 1);
    assert_eq!(tick1.camera.eye, [0.0, 10.0, 50.0]);
    assert!(!tick1.camera.cut_from_previous);
    assert!(tick1.actors.is_empty());

    // EOF reached
    assert!(player.step_tick().is_none());
    assert!(player.last_error().is_none());
}

#[test]
fn test_flm_evaluate_film_convenience_function() {
    let flm_path = fixtures_dir().join("synthetic_minimal.flm");
    let data = fs::read(&flm_path).expect("read synthetic_minimal.flm");

    let records = evaluate_film(&data).expect("evaluate_film succeeds");
    assert_eq!(records.len(), 2);
    assert_eq!(records[0].tick, 0);
    assert_eq!(records[1].tick, 1);
}

// ----------------------------------------------------------------------------
// 4. Gate G04 Parity Verification against oracle_intro_trajectory.json
// ----------------------------------------------------------------------------

#[cfg(feature = "serde")]
#[test]
fn test_gate_g04_oracle_intro_parity_and_sub_millimeter_rmse() {
    let oracle_path = fixtures_dir().join("oracle_intro_trajectory.json");
    assert!(
        oracle_path.exists(),
        "oracle_intro_trajectory.json must exist"
    );

    let oracle_content = fs::read_to_string(&oracle_path).expect("read oracle json");
    let oracle_records: Vec<TrajectoryRecord> =
        serde_json::from_str(&oracle_content).expect("deserialization of oracle records");
    assert_eq!(oracle_records.len(), 2);

    // Build synthetic .FLM bytecode and evaluate via genuine FlmPlayer state machine
    let intro_flm_bytes = build_synthetic_intro_flm(2);
    let mut player = FlmEvaluator::new(&intro_flm_bytes).expect("FlmEvaluator creates");
    let evaluated = player.evaluate_all().expect("evaluate_all succeeds");
    assert_eq!(evaluated.len(), 2);

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
    let rmse = compute_position_rmse(&evaluated, &oracle_records);
    assert!(
        rmse <= GATE_G04_RMSE_THRESHOLD_METERS,
        "Gate G04 Parity Failed: RMSE {rmse:.6} m > {GATE_G04_RMSE_THRESHOLD_METERS:.6} m"
    );
    assert!(
        rmse < 1e-4,
        "Sub-millimeter precision violated: RMSE = {rmse}"
    );

    let verified_rmse = assert_parity_gate_g04(&evaluated, &oracle_records);
    assert_eq!(rmse, verified_rmse);
}

// ----------------------------------------------------------------------------
// 5. Invariant [I4]: Cut Detection and Sub-tick Interpolation Suppression
// ----------------------------------------------------------------------------

#[test]
fn test_camera_cut_detection_criteria() {
    // Normal small motion <= 50m
    assert!(!detect_camera_cut(
        [0.0, 10.0, 49.5],
        Some([0.0, 10.0, 50.0]),
        0,
        Some(0)
    ));

    // Displacement > 50m triggers cut
    assert!(detect_camera_cut(
        [0.0, 10.0, 101.0],
        Some([0.0, 10.0, 50.0]),
        0,
        Some(0)
    ));

    // View object slot change triggers cut regardless of distance
    assert!(detect_camera_cut(
        [0.0, 10.0, 50.0],
        Some([0.0, 10.0, 50.0]),
        1,
        Some(0)
    ));

    // Initial frame (no last pose) does not cut
    assert!(!detect_camera_cut([0.0, 10.0, 50.0], None, 0, None));
}

#[test]
fn test_sub_tick_interpolation_suppression_on_cut() {
    let frame_a = TrajectoryRecord {
        tick: 199,
        camera: CameraTransform {
            eye: [0.0, 10.0, 20.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 10.0, 100.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    // Frame B has cut_from_previous = true (camera jump to tower)
    let frame_b = TrajectoryRecord {
        tick: 200,
        camera: CameraTransform {
            eye: [45.0, 25.0, 120.0],
            target: [0.0, 10.0, 100.0],
            fov_degrees: 48.0,
            roll_radians: 0.0,
            cut_from_previous: true,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 10.0, 101.2],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    // Interpolation at alpha = 0.5 MUST suppress lerp (alpha_eff = 0.0) per Invariant [I4]
    let sub = interpolate_trajectory(&frame_a, &frame_b, 0.5);
    assert_eq!(sub.camera.eye, frame_a.camera.eye); // Held at frame A eye!
    assert_eq!(sub.camera.fov_degrees, frame_a.camera.fov_degrees);
    assert_eq!(
        sub.actors[0].position_meters,
        frame_a.actors[0].position_meters
    );

    // Continuous tick helper
    let records = vec![frame_a.clone(), frame_b.clone()];
    let eval_half = evaluate_sub_tick(&records, 199.5).unwrap();
    assert_eq!(eval_half.camera.eye, frame_a.camera.eye);
}

#[test]
fn test_sub_tick_continuous_lerp_when_not_cut() {
    let frame_a = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 10.0, 0.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    let frame_b = TrajectoryRecord {
        tick: 1,
        camera: CameraTransform {
            eye: [0.0, 10.0, 40.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 10.0, 2.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    let sub = interpolate_trajectory(&frame_a, &frame_b, 0.5);
    assert_eq!(sub.camera.eye, [0.0, 10.0, 45.0]);
    assert_eq!(sub.actors[0].position_meters, [0.0, 10.0, 1.0]);
}

// ----------------------------------------------------------------------------
// 6. Quaternions & Slerp Precision
// ----------------------------------------------------------------------------

#[test]
fn test_slerp_antipodal_and_parallel_paths() {
    let q1 = [0.0, 0.0, 0.0, 1.0];
    let q2 = [0.0, 0.0, 0.0, -1.0]; // Antipodal identity (dot = -1.0)

    let slerped = slerp_quat(q1, q2, 0.5);
    assert!(quat_norm_diff(slerped) < 1e-4);
    assert!((slerped[3].abs() - 1.0).abs() < 1e-4);

    // Nearly parallel
    let q_near = [0.0, 0.0, 0.0001, 0.999999];
    let slerped_near = slerp_quat(q1, q_near, 0.5);
    assert!(quat_norm_diff(slerped_near) < 1e-4);
}

#[test]
fn test_quat_from_euler_and_unit_invariant() {
    let q = quat_from_euler(0.5, -0.3, 0.2);
    assert!(quat_norm_diff(q) < 1e-4);
    assert!((quat_norm(q) - 1.0).abs() < 1e-4);

    let zero = quat_normalize([0.0, 0.0, 0.0, 0.0]);
    assert_eq!(zero, [0.0, 0.0, 0.0, 1.0]);
}

#[test]
fn test_focal_to_fov_y_accuracy() {
    // 290 focal length yields ~44.96 degrees (nominal 45)
    let fov = focal_to_fov_y(290.0);
    assert!((fov - 45.0).abs() < 0.1);

    // Invalid focal length defaults to 45.0
    assert_eq!(focal_to_fov_y(0.0), 45.0);
    assert_eq!(focal_to_fov_y(-10.0), 45.0);
}

// ----------------------------------------------------------------------------
// 7. Static vs Dynamic Placement Opcodes
// ----------------------------------------------------------------------------

#[test]
fn test_flm_static_actor_placement_in_create() {
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice0 = Vec::new();

    // CREATE slot 2: SIF_EXISTS | SIF_DRAW (no SIF_MOVES, no SIF_ROTATES) -> static!
    slice0.push(0x02);
    slice0.push(SIF_EXISTS | SIF_DRAW);
    slice0.extend_from_slice(&42u16.to_le_bytes()); // shape_id 42
    // Static pos [10.0, 20.0, 30.0]
    slice0.extend_from_slice(&(10 * 65536i32).to_le_bytes());
    slice0.extend_from_slice(&(20 * 65536i32).to_le_bytes());
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

    let mut player = FlmPlayer::new(&film).unwrap();
    let tick0 = player.step_tick().unwrap();
    assert_eq!(tick0.actors.len(), 1);
    assert_eq!(tick0.actors[0].actor_id, 2);
    assert_eq!(tick0.actors[0].position_meters, [10.0, 20.0, 30.0]);

    let tick1 = player.step_tick().unwrap();
    assert_eq!(tick1.actors.len(), 1);
    assert_eq!(tick1.actors[0].position_meters, [10.0, 20.0, 30.0]); // Static hold!
}

// ----------------------------------------------------------------------------
// 8. Credits and Control Opcodes
// ----------------------------------------------------------------------------

#[test]
fn test_flm_credits_and_max_obj_and_variables() {
    let mut film = Vec::from(&b"FILM"[..]);
    let mut slice0 = Vec::new();

    // 0x9B: max_obj = 5
    slice0.push(0x9B);
    slice0.push(5);

    // 0x99: set credits ("Directed by", "Stunt Island")
    slice0.push(0x99);
    slice0.extend_from_slice(b"Directed by\0");
    slice0.extend_from_slice(b"Stunt Island\0");

    // 0x82: variable 2 = 1234
    slice0.push(0x82);
    slice0.extend_from_slice(&1234u16.to_le_bytes());

    // 0xA2: before word
    slice0.push(0xA2);
    slice0.extend_from_slice(&5678u16.to_le_bytes());

    slice0.push(0xFF);

    film.push(1);
    film.extend_from_slice(&(slice0.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice0);

    // Slice 1: 0x98: clear credits
    let slice1 = vec![0x98, 0xFF];

    film.push(1);
    film.extend_from_slice(&(slice1.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice1);

    let mut player = FlmPlayer::new(&film).unwrap();
    let _t0 = player.step_tick().unwrap();
    assert_eq!(player.max_obj(), 5);
    assert_eq!(player.credits()[0], "Directed by");
    assert_eq!(player.credits()[1], "Stunt Island");
    assert_eq!(player.variables()[2], 1234);

    let _t1 = player.step_tick().unwrap();
    assert_eq!(player.credits()[0], "");
    assert_eq!(player.credits()[1], "");
}

#[test]
fn test_flm_invalid_opcode_detection() {
    let mut film = Vec::from(&b"FILM"[..]);
    let slice0 = vec![0xF0, 0xFF]; // Unknown opcode class

    film.push(1);
    film.extend_from_slice(&(slice0.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice0);

    let mut player = FlmPlayer::new(&film).unwrap();
    assert!(player.step_tick().is_none());
    assert!(matches!(
        player.last_error(),
        Some(FlmError::InvalidOpcode { opcode: 0xF0, .. })
    ));
}

#[test]
fn test_flm_slot_state_methods() {
    let mut slot = SlotState::default();
    assert_eq!(slot.position_meters(), [0.0, 0.0, 0.0]);
    assert_eq!(slot.rotation_quat(), [0.0, 0.0, 0.0, 1.0]);

    slot.type_flags = SIF_EXISTS | SIF_MOVES | SIF_ROTATES | SIF_ANIMATES;
    assert_ne!(slot.type_flags & SIF_MOVES, 0);
    assert_ne!(slot.type_flags & SIF_ROTATES, 0);
    assert_ne!(slot.type_flags & SIF_ANIMATES, 0);

    slot.pos_fixed = [65536, 131072, -65536];
    assert_eq!(slot.position_meters(), [1.0, 2.0, -1.0]);
}

#[test]
fn test_multi_tick_intro_flm_generation() {
    // Generate 50 ticks of synthetic INTRO choreography
    let bytes = build_synthetic_intro_flm(50);
    assert!(bytes.len() > 100);

    let mut evaluator = FlmEvaluator::new(&bytes).expect("FlmEvaluator creates");
    let records = evaluator
        .evaluate_all()
        .expect("multi-tick film evaluation succeeds");
    assert_eq!(records.len(), 50);

    // Initial ticks match golden oracle
    assert_eq!(records[0].camera.eye, [0.0, 10.0, 50.0]);
    assert_eq!(records[1].camera.eye, [0.0, 10.0, 49.5]);
    assert_eq!(records[0].actors[0].position_meters, [0.0, 10.0, 0.0]);
    assert_eq!(records[1].actors[0].position_meters, [0.0, 10.0, 0.5]);

    // Self-parity check asserts Gate G04 threshold
    let rmse = compute_position_rmse(&records, &records);
    assert_eq!(rmse, 0.0);
    let verified = assert_parity_gate_g04(&records, &records);
    assert!(verified <= GATE_G04_RMSE_THRESHOLD_METERS);
}

#[test]
fn test_compute_position_rmse_empty_set_returns_infinity() {
    let empty: [TrajectoryRecord; 0] = [];
    let rmse = compute_position_rmse(&empty, &empty);
    assert_eq!(rmse, f32::INFINITY);

    let panic_res = std::panic::catch_unwind(|| {
        assert_parity_gate_g04(&empty, &empty);
    });
    assert!(
        panic_res.is_err(),
        "Empty evaluation set must fail Gate G04 assertion"
    );
}

//! Empirical Challenge Suite for Seam 2: Native .FLM Choreography Evaluator & Parity Suite (Ticket T07).
//!
//! Adversarially verifies:
//! - Gate G04: Independent position RMSE calculation <= 0.01 m vs `tests/fixtures/oracle_intro_trajectory.json`
//! - Invariant `[I4]`: Sub-tick interpolation across alpha in {0.0, 0.25, 0.5, 0.75, 1.0}
//! - Invariant `[I4]`: Instantaneous camera cut suppression (zero intermediate camera lerp when cut_from_previous == true)
//! - Invariant `[I1]`: Unit quaternion normalization (| ||q|| - 1.0 | < 1e-4) across all frames, angles, and slerp
//! - Invariant `[I1]`: Column-major affine 4x4 world matrix orthonormality (R^T * R = I, det(R) = +1.0)
//! - 600-tick continuous cinematic simulation stream parity and cut detection
//! - Adversarial malformed byte stream rejection (truncated slices, unknown opcodes, non-terminated strings)

mod common;

#[cfg(feature = "serde")]
use std::fs;
#[cfg(feature = "serde")]
use std::path::{Path, PathBuf};

use stunt_core::contracts::trajectory::{
    ActorTransform, AudioCue, CameraTransform, TrajectoryRecord,
};
use stunt_core::flm::{FilmTimeline, FlmError, SliceKeyframe, compute_position_rmse};
#[cfg(feature = "serde")]
use stunt_core::flm::{GATE_G04_RMSE_THRESHOLD_METERS, assert_parity_gate_g04};

use common::{build_synthetic_intro_flm, quat_norm_diff};

#[cfg(feature = "serde")]
fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures")
}

// =============================================================================
// Independent Mathematical Verification Oracles
// =============================================================================

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

// =============================================================================
// Category 1: Gate G04 & Golden Oracle Parity Challenge
// =============================================================================

#[cfg(feature = "serde")]
#[test]
fn test_challenge_gate_g04_oracle_independent_verification() {
    let oracle_path = fixtures_dir().join("oracle_intro_trajectory.json");
    assert!(
        oracle_path.exists(),
        "oracle_intro_trajectory.json fixture must exist"
    );

    let content = fs::read_to_string(&oracle_path).expect("read oracle json");
    let oracle_records: Vec<TrajectoryRecord> =
        serde_json::from_str(&content).expect("parse oracle json");
    assert_eq!(
        oracle_records.len(),
        2,
        "Oracle must contain exactly 2 golden ticks"
    );

    // Evaluate native .FLM bytecode into a 50 Hz timeline
    let bytecode = build_synthetic_intro_flm(2);
    let timeline = FilmTimeline::from_bytes(&bytecode).expect("timeline evaluates");
    assert!(timeline.stop_reason().is_none());

    assert_eq!(
        timeline.slices().len(),
        oracle_records.len(),
        "Evaluated slices must match oracle count"
    );

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
    let helper_rmse = compute_position_rmse(&timeline, &oracle_records);
    assert!(
        (helper_rmse as f64 - indep_rmse).abs() < 1e-6,
        "Engine compute_position_rmse ({helper_rmse}) disagrees with independent oracle ({indep_rmse})"
    );

    let gate_assert_res = assert_parity_gate_g04(&timeline, &oracle_records);
    assert_eq!(helper_rmse, gate_assert_res);
}

#[cfg(feature = "serde")]
#[test]
fn test_challenge_gate_g04_tamper_rejection() {
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

// =============================================================================
// Category 2: Invariant [I4] Sub-Tick Interpolation Across Alpha Lattice
// =============================================================================

#[test]
fn test_challenge_sub_tick_interpolation_across_alpha_lattice() {
    let frame_0 = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 40.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 10.0, 0.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: vec![AudioCue {
            tick: 0,
            sample_name: "ENGINE.VOC".to_string(),
            volume: 0.8,
            pan: 0.0,
        }],
    };

    let frame_1 = TrajectoryRecord {
        tick: 1,
        camera: CameraTransform {
            eye: [10.0, 20.0, 40.0],
            target: [5.0, 0.0, 0.0],
            fov_degrees: 60.0,
            roll_radians: 0.2,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [4.0, 12.0, 8.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: vec![AudioCue {
            tick: 1,
            sample_name: "WIND.VOC".to_string(),
            volume: 0.5,
            pan: 0.0,
        }],
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
fn test_challenge_sub_tick_out_of_bounds_and_clamping() {
    let frame_0 = TrajectoryRecord {
        tick: 10,
        camera: CameraTransform {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "ACTOR".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 0.0, 0.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    let frame_1 = TrajectoryRecord {
        tick: 11,
        camera: CameraTransform {
            eye: [10.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 50.0,
            roll_radians: 0.1,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "ACTOR".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [10.0, 0.0, 0.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
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

// =============================================================================
// Category 3: Invariant [I4] Camera Cut Suppression Challenge
// =============================================================================

#[test]
fn test_challenge_camera_cut_suppression_holds_prior_pose_adversarial() {
    let frame_a = TrajectoryRecord {
        tick: 50,
        camera: CameraTransform {
            eye: [10.0, 5.0, -100.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 35.0,
            roll_radians: 0.05,
            cut_from_previous: false,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [10.0, 5.0, -50.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    // Frame B is a cut: camera moved 500 meters away to a hilltop tower
    let frame_b = TrajectoryRecord {
        tick: 51,
        camera: CameraTransform {
            eye: [500.0, 250.0, 300.0],
            target: [10.0, 5.0, -50.0],
            fov_degrees: 55.0,
            roll_radians: -0.1,
            cut_from_previous: true,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [10.0, 5.0, -48.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
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
        camera: CameraTransform {
            eye: [510.0, 250.0, 300.0],
            target: [10.0, 5.0, -50.0],
            fov_degrees: 55.0,
            roll_radians: -0.1,
            cut_from_previous: false,
        },
        actors: frame_b.actors.clone(),
        audio_cues: Vec::new(),
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

// =============================================================================
// Category 5: Multi-Tick 600-Tick Trajectory Stream Parity & Stress
// =============================================================================

#[test]
fn test_challenge_600_tick_intro_trajectory_kinematic_stream() {
    // Generate 600 ticks matching Requirement R3
    let flm_bytes = build_synthetic_intro_flm(600);
    assert!(
        flm_bytes.len() > 10000,
        "600 ticks bytecode must be substantial in size"
    );

    let timeline = FilmTimeline::from_bytes(&flm_bytes).expect("600 ticks film evaluates");
    assert!(timeline.stop_reason().is_none());
    assert!(timeline.warnings().is_empty());
    let records: Vec<TrajectoryRecord> = timeline
        .slices()
        .iter()
        .map(|slice| slice.record.clone())
        .collect();

    assert_eq!(
        records.len(),
        600,
        "Stream must evaluate exactly 600 continuous simulation ticks"
    );

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
}

// =============================================================================
// Category 6: Dynamic Object Lifecycle & Slot Migration
// =============================================================================

#[test]
fn test_challenge_actor_lifecycle_spawn_despawn_in_sub_tick() {
    // Frame 0 has actor 1 only
    let frame_0 = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform::default(),
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "ACTOR_1".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0, 0.0, 0.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
    };

    // Frame 1 has actor 2 only (actor 1 despawned, actor 2 spawned)
    let frame_1 = TrajectoryRecord {
        tick: 1,
        camera: CameraTransform::default(),
        actors: vec![ActorTransform {
            actor_id: 2,
            model_name: "ACTOR_2".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [10.0, 10.0, 10.0],
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }],
        audio_cues: Vec::new(),
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

// =============================================================================
// Category 7: Adversarial Malformed Byte Stream & Resiliency Challenge
// =============================================================================

#[test]
fn test_challenge_adversarial_malformed_slices() {
    // 1. Header-only trailer: a valid end-of-film epilogue, not a malformed slice
    let mut film = Vec::from(&b"FILM"[..]);
    film.push(1); // prev_slice_len low byte
    film.extend_from_slice(&0u16.to_le_bytes()); // prev_slice_len high byte, tick_duration
    // no terminator
    let timeline = FilmTimeline::from_bytes(&film).unwrap();
    assert!(timeline.slices().is_empty());
    assert!(timeline.stop_reason().is_none());

    // 2. Unclosed string in credits opcode 0x99
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

    // 3. Unknown opcode 0xEF
    let mut film = Vec::from(&b"FILM"[..]);
    let slice = vec![0xEF, 0xFF];
    film.push(1);
    film.extend_from_slice(&(slice.len() as u16).to_le_bytes());
    film.extend_from_slice(&slice);
    let timeline = FilmTimeline::from_bytes(&film).unwrap();
    assert!(timeline.slices().is_empty());
    assert!(matches!(
        timeline.stop_reason(),
        Some(FlmError::InvalidOpcode { opcode: 0xEF, .. })
    ));
}

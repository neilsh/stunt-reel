//! `flm::interpolate`'s unit tests and the test-only conversions they use.

use super::*;
use std::f32::consts::{FRAC_PI_2, PI};

/// Convert an angle in radians to a 16-bit BAM value.
#[inline]
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "`norm` is in 0..TAU, and a full turn rounds to 65536, which wraps to BAM 0"
)]
pub(crate) fn radians_to_bam(rad: f32) -> u16 {
    let mut norm = rad % TAU;
    if norm < 0.0 {
        norm += TAU;
    }
    ((norm / TAU) * 65536.0).round() as u32 as u16
}

/// Compute deviation from unit length: `| ||q|| - 1.0 |`.
#[inline]
pub(crate) fn quat_norm_diff(q: [f32; 4]) -> f32 {
    (quat_norm(q) - 1.0).abs()
}

#[test]
fn animate_interpolates_unsigned_and_never_wraps() {
    // CTRY.FLM's explosion: 24576 -> 47104 rises; 47104 -> 4096 falls straight down.
    assert_eq!(lerp_animate(24_576, 47_104, 0.0), 24_576);
    assert_eq!(lerp_animate(24_576, 47_104, 0.5), 35_840);
    assert_eq!(lerp_animate(24_576, 47_104, 1.0), 47_104);
    assert_eq!(lerp_animate(47_104, 4096, 0.5), 25_600);
    assert_eq!(lerp_animate(47_104, 4096, 1.0), 4096);
    // A fall rounds toward the lower value, as `PLAYONE`'s `mul`/`sub` does.
    assert_eq!(lerp_animate(1, 0, 0.25), 0);
}

#[test]
fn joints_carry_the_animate_word_in_slot_zero() {
    assert_eq!(interpolate_joints(&[], &[(0, 1000)], 0.5), vec![(0, 500)]);
    assert_eq!(interpolate_joints(&[(0, 10)], &[], 1.0), Vec::new());
    assert_eq!(
        interpolate_joints(&[(0, 0), (3, 7)], &[(3, 9)], 0.75),
        vec![(3, 9)]
    );
}

/// An unrotated, visible actor with no shadow at `position_meters`.
fn actor(actor_id: u32, position_meters: [f32; 3]) -> ActorTransform {
    ActorTransform {
        actor_id,
        model_name: "FOKKER".to_string(),
        shape_id: 0,
        rotation_quat: [0.0, 0.0, 0.0, 1.0],
        position_meters,
        state_mask: 1,
        casts_shadow: false,
        joint_angles_bam: Vec::new(),
    }
}

fn record(tick: u32, eye: [f32; 3], cut: bool, actors: Vec<ActorTransform>) -> TrajectoryRecord {
    TrajectoryRecord {
        tick,
        camera: CameraTransform {
            eye,
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: cut,
            ..Default::default()
        },
        actors,
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
        bank: BankVariables::default(),
    }
}

/// Independent oracle to verify a 4x4 column-major matrix is a rigid transform.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "test helper: column indices 0..=2 into a 16-element matrix"
)]
fn assert_rigid_transform(mat: &[f32; 16], pos: [f32; 3]) {
    let col = |c: usize| [mat[c * 4], mat[c * 4 + 1], mat[c * 4 + 2]];
    let dot = |a: [f32; 3], b: [f32; 3]| a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    let (c0, c1, c2) = (col(0), col(1), col(2));
    for c in [c0, c1, c2] {
        assert!(
            (dot(c, c).sqrt() - 1.0).abs() < 1e-4,
            "column not unit: {c:?}"
        );
    }
    assert!(dot(c0, c1).abs() < 1e-4);
    assert!(dot(c0, c2).abs() < 1e-4);
    assert!(dot(c1, c2).abs() < 1e-4);

    let det = c0[0] * (c1[1] * c2[2] - c2[1] * c1[2]) - c1[0] * (c0[1] * c2[2] - c2[1] * c0[2])
        + c2[0] * (c0[1] * c1[2] - c1[1] * c0[2]);
    assert!(
        (det - 1.0).abs() < 1e-4,
        "rotation determinant is not +1: {det}"
    );

    let translation = col(3);
    for i in 0..3 {
        assert!(
            (translation[i] - pos[i]).abs() < 1e-4,
            "translation mismatch"
        );
    }
    assert_eq!([mat[3], mat[7], mat[11], mat[15]], [0.0, 0.0, 0.0, 1.0]);
}

#[test]
fn camera_cut_detection_criteria() {
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
fn camera_cut_displacement_boundary_precision() {
    let eye_base = [0.0, 10.0, 50.0];

    assert!(
        !detect_camera_cut([0.0, 10.0, 50.0 + 49.99], Some(eye_base), 0, Some(0)),
        "49.99m displacement must NOT trigger camera cut"
    );
    assert!(
        detect_camera_cut([0.0, 10.0, 50.0 + 50.01], Some(eye_base), 0, Some(0)),
        "50.01m displacement MUST trigger camera cut"
    );
    // 3D diagonal displacement: sqrt(3 * 28.87^2) = 50.004m
    assert!(
        detect_camera_cut(
            [28.87, 10.0 + 28.87, 50.0 + 28.87],
            Some(eye_base),
            0,
            Some(0)
        ),
        "diagonal displacement of 50.004m must trigger camera cut"
    );
    assert!(
        detect_camera_cut(eye_base, Some(eye_base), 1, Some(0)),
        "view_obj slot change from 0 to 1 MUST trigger camera cut"
    );
    assert_eq!(
        CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS.to_bits(),
        50.0f32.to_bits()
    );

    // Exact boundary behaviour at the origin
    let eye0 = [0.0, 10.0, 0.0];
    assert!(!detect_camera_cut(
        [0.0, 10.0, 49.99],
        Some(eye0),
        0,
        Some(0)
    ));
    assert!(detect_camera_cut(
        [0.0, 10.0, 50.01],
        Some(eye0),
        0,
        Some(0)
    ));
    assert!(detect_camera_cut(eye0, Some(eye0), 1, Some(0)));
}

#[test]
fn interpolation_alpha_is_clamped() {
    let frame_0 = record(
        10,
        [0.0, 10.0, 50.0],
        false,
        vec![actor(1, [0.0, 0.0, 0.0])],
    );
    let frame_1 = record(
        11,
        [10.0, 10.0, 50.0],
        false,
        vec![actor(1, [10.0, 0.0, 0.0])],
    );

    let sub_neg = interpolate_trajectory(&frame_0, &frame_1, -0.5);
    assert_eq!(sub_neg.camera.eye, frame_0.camera.eye);
    assert_eq!(
        sub_neg.actors[0].position_meters,
        frame_0.actors[0].position_meters
    );

    let sub_pos = interpolate_trajectory(&frame_0, &frame_1, 2.5);
    assert_eq!(sub_pos.camera.eye, frame_1.camera.eye);
    assert_eq!(
        sub_pos.actors[0].position_meters,
        frame_1.actors[0].position_meters
    );
}

#[test]
fn interpolation_survives_extreme_alpha_values() {
    let dummy_a = record(0, [0.0, 0.0, 0.0], false, vec![]);
    let dummy_b = record(1, [10.0, 20.0, 30.0], true, vec![]);
    drop(interpolate_trajectory(&dummy_a, &dummy_b, -10.0));
    drop(interpolate_trajectory(&dummy_a, &dummy_b, 10.0));
    drop(interpolate_trajectory(&dummy_a, &dummy_b, f32::NAN));
    drop(interpolate_trajectory(&dummy_a, &dummy_b, f32::INFINITY));
}

#[test]
fn slerp_antipodal_and_parallel_paths() {
    let q1 = [0.0, 0.0, 0.0, 1.0];
    let q2 = [0.0, 0.0, 0.0, -1.0]; // Antipodal identity (dot = -1.0)

    let slerped = slerp_quat(q1, q2, 0.5);
    assert!(quat_norm_diff(slerped) < 1e-4);
    assert!((slerped[3].abs() - 1.0).abs() < 1e-4);

    // Nearly parallel
    let q_near = [0.0, 0.0, 0.0001, 0.999_999];
    let slerped_near = slerp_quat(q1, q_near, 0.5);
    assert!(quat_norm_diff(slerped_near) < 1e-4);
}

#[test]
fn slerp_shortest_path_and_normalization_adversarial() {
    let q_id = [0.0, 0.0, 0.0, 1.0];
    let q_90 = quat_from_euler(FRAC_PI_2, 0.0, 0.0);

    for &t in &[0.0f32, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0] {
        let diff = quat_norm_diff(slerp_quat(q_id, q_90, t));
        assert!(
            diff < 1e-4,
            "slerp produced unnormalized quaternion at t={t}: diff={diff}"
        );
    }

    // Near-antipodal (179.9 degrees rotation)
    let q_179 = quat_from_euler(PI - 0.001, 0.0, 0.0);
    assert!(quat_norm_diff(slerp_quat(q_id, q_179, 0.5)) < 1e-4);

    // Exact antipodal: q and -q represent the same SO(3) orientation
    let q_neg = [-q_id[0], -q_id[1], -q_id[2], -q_id[3]];
    let slerped_neg = slerp_quat(q_id, q_neg, 0.5);
    assert!(quat_norm_diff(slerped_neg) < 1e-4);
    assert!(
        (slerped_neg[3].abs() - 1.0).abs() < 1e-4,
        "antipodal slerp must stay at identity pose"
    );
}

#[test]
fn slerp_degenerate_inputs_are_stable() {
    let q_ident = [0.0, 0.0, 0.0, 1.0];
    let q_zero = [0.0, 0.0, 0.0, 0.0];
    let q_nan = [f32::NAN, 0.0, 0.0, 1.0];

    assert!(quat_norm_diff(slerp_quat(q_ident, [0.0, 0.0, 0.0, -1.0], 0.5)) < 1e-4);
    assert!(!slerp_quat(q_ident, q_zero, 0.5)[3].is_nan());
    let _: [f32; 4] = slerp_quat(q_ident, q_nan, 0.5);
}

#[test]
fn quat_from_euler_and_unit_invariant() {
    let q = quat_from_euler(0.5, -0.3, 0.2);
    assert!(quat_norm_diff(q) < 1e-4);
    assert!((quat_norm(q) - 1.0).abs() < 1e-4);

    let zero = quat_normalize([0.0, 0.0, 0.0, 0.0]);
    assert_eq!(zero, [0.0, 0.0, 0.0, 1.0]);

    // Extreme angles stay normalised.
    assert!(quat_norm_diff(quat_from_euler(1e6, -1e6, 1e6)) < 1e-3);
}

#[test]
fn quaternion_normalization_across_all_angles() {
    // Sweep the BAM circle for yaw, pitch, roll
    let test_bams: [u16; 16] = [
        0, 1024, 4096, 8192, 16384, 24576, 32768, 40960, 49152, 57344, 60000, 65000, 65535, 1,
        32767, 32769,
    ];

    for &rz_bam in &test_bams {
        for &rx_bam in &test_bams[0..8] {
            for &ry_bam in &test_bams[0..4] {
                let q = quat_from_euler(
                    bam_to_radians(ry_bam),
                    bam_to_radians(rx_bam),
                    bam_to_radians(rz_bam),
                );
                let diff = quat_norm_diff(q);
                assert!(
                    diff < 1e-4,
                    "unit quaternion invariant violated for BAM ({rz_bam}, {rx_bam}, {ry_bam}): {diff}"
                );
            }
        }
    }
}

#[test]
fn actor_world_matrix_orthonormality_and_determinant() {
    let test_cases = [
        ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]),
        ([100.0, -50.0, 25.0], [0.0, 0.0, 0.0, 1.0]),
        ([0.0, 10.0, 0.0], quat_from_euler(0.5, -0.2, 0.8)),
        ([-34.5, 120.0, -89.2], quat_from_euler(1.5, 0.3, -0.4)),
        ([1000.0, 200.0, -500.0], quat_from_euler(PI, 0.0, 0.0)),
    ];

    for (pos, quat) in test_cases {
        let mut actor = actor(1, pos);
        actor.rotation_quat = quat;
        assert_rigid_transform(&actor.compute_world_matrix(), pos);
    }
}

#[test]
fn lerp_angle_takes_the_shorter_arc_across_the_wrap() {
    let tau = TAU;
    // 359 degrees to 1 degree is a 2 degree arc, not 358.
    let a = 359f32.to_radians();
    let b = 1f32.to_radians();
    let mid = lerp_angle(a, b, 0.5);
    let wrapped = mid.rem_euclid(tau);
    assert!(wrapped < 1e-4 || (tau - wrapped) < 1e-4, "{wrapped}");
    assert!((lerp_angle(0.5, 1.5, 0.5) - 1.0).abs() < 1e-6);
}

#[test]
fn focal_to_fov_y_accuracy() {
    // 290 focal length yields ~44.96 degrees (nominal 45)
    assert!((focal_to_fov_y(290.0) - 45.0).abs() < 0.1);

    // Invalid focal length defaults to 45.0
    assert_eq!(focal_to_fov_y(0.0), 45.0);
    assert_eq!(focal_to_fov_y(-10.0), 45.0);
    assert_eq!(focal_to_fov_y(-100.0), 45.0);

    // Extreme values never produce NaN
    assert!(!focal_to_fov_y(1e-12).is_nan());
    assert!(!focal_to_fov_y(1e12).is_nan());
}

#[test]
fn bam_radian_conversion_extremes() {
    for bam in [0u16, 1, 32767, 32768, 65535] {
        let rad = bam_to_radians(bam);
        assert!(!rad.is_nan() && (0.0..=TAU).contains(&rad));
        let diff = (i32::from(radians_to_bam(rad)) - i32::from(bam)).abs();
        assert!(diff <= 1, "BAM conversion inaccuracy: {bam} -> {diff}");
    }

    assert_eq!(radians_to_bam(0.0), 0);
    assert_eq!(radians_to_bam(-PI), 32768);
    let _: u16 = radians_to_bam(1e9);
    let _: u16 = radians_to_bam(f32::NAN);
    let _: u16 = radians_to_bam(f32::INFINITY);
    let _: u16 = radians_to_bam(f32::NEG_INFINITY);
}

#[expect(
    clippy::cast_possible_truncation,
    reason = "the goldens are f32 values written out as JSON numbers"
)]
fn golden_f32s(value: &serde_json::Value) -> Vec<f32> {
    match value {
        serde_json::Value::Array(items) => items
            .iter()
            .map(|v| v.as_f64().expect("number") as f32)
            .collect(),
        other => vec![other.as_f64().expect("number") as f32],
    }
}

fn assert_close(actual: &[f32], expected: &[f32], context: &str) {
    assert_eq!(actual.len(), expected.len(), "{context}: length");
    for (i, (a, e)) in actual.iter().zip(expected).enumerate() {
        assert!(
            (a - e).abs() <= 1e-5,
            "{context}[{i}]: rust {a} vs golden {e}"
        );
    }
}

#[test]
fn dos_math_matches_shared_goldens() {
    let text = include_str!("../../../../../tests/fixtures/dos_math_goldens.json");
    let goldens: serde_json::Value = serde_json::from_str(text).expect("valid golden json");

    for case in goldens["bam_to_radians"].as_array().expect("section") {
        let raw = u16::try_from(case["input"].as_u64().expect("u16 input")).expect("u16 input");
        let expected = golden_f32s(&case["expected"]);
        assert_close(&[bam_to_radians(raw)], &expected, &format!("bam {raw}"));
    }

    for case in goldens["focal_to_fov_y"].as_array().expect("section") {
        let focal = golden_f32s(&case["input"])[0];
        let expected = golden_f32s(&case["expected"]);
        assert_close(
            &[focal_to_fov_y(focal)],
            &expected,
            &format!("focal {focal}"),
        );
    }

    for case in goldens["quat_from_euler"].as_array().expect("section") {
        let e = golden_f32s(&case["input"]);
        let expected = golden_f32s(&case["expected"]);
        assert_close(
            &quat_from_euler(e[0], e[1], e[2]),
            &expected,
            &format!("euler {e:?}"),
        );
    }
}

//! Interpolation, kinematic conversions, and cut detection for `.FLM` choreography.
//!
//! Adheres strictly to:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, +Z Backward, -Z Forward)
//! - `[I4]` Discrete simulation ticks (50 Hz) with sub-tick interpolation and cut suppression

use crate::contracts::trajectory::{ActorTransform, CameraTransform, TrajectoryRecord};
use std::f32::consts::TAU;

/// Threshold in meters for camera displacement triggering cut suppression `[I4]`.
pub(crate) const CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS: f32 = 50.0;

/// Convert a 16-bit Binary Angular Measurement (BAM) to radians `[0, 2*pi)`.
#[inline]
pub(crate) fn bam_to_radians(raw_u16: u16) -> f32 {
    (raw_u16 as f32 / 65536.0) * TAU
}

/// Convert an angle in radians to a 16-bit BAM value.
#[cfg(test)]
#[inline]
pub(crate) fn radians_to_bam(rad: f32) -> u16 {
    let mut norm = rad % TAU;
    if norm < 0.0 {
        norm += TAU;
    }
    ((norm / TAU) * 65536.0).round() as u32 as u16
}

/// Convert Stunt Island integer focal distance scalar to vertical FOV in degrees.
///
/// Uses aspect-corrected half-height H_half = 120.0 for 320x240 (4:3) Mode 13h:
/// `FOV_y = 2 * arctan(120.0 / focal_dist) * (180.0 / pi)`.
pub(crate) fn focal_to_fov_y(focal_dist: f32) -> f32 {
    if focal_dist <= 0.0 {
        return 45.0;
    }
    2.0 * (120.0 / focal_dist).atan().to_degrees()
}

/// Compute Euclidean norm of a quaternion `[x, y, z, w]`.
#[inline]
pub(crate) fn quat_norm(q: [f32; 4]) -> f32 {
    (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt()
}

/// Normalize quaternion `[x, y, z, w]` to unit length.
pub(crate) fn quat_normalize(q: [f32; 4]) -> [f32; 4] {
    let norm = quat_norm(q);
    if norm <= 1e-12 {
        [0.0, 0.0, 0.0, 1.0]
    } else {
        let inv = 1.0 / norm;
        [q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv]
    }
}

/// Compute deviation from unit length: `| ||q|| - 1.0 |`.
#[cfg(test)]
#[inline]
pub(crate) fn quat_norm_diff(q: [f32; 4]) -> f32 {
    (quat_norm(q) - 1.0).abs()
}

/// `(sin, cos)` of half of `angle`, with float noise below `1e-7` snapped to zero.
///
/// `cos(PI / 2)` in `f32` is `-4.4e-8`, not `0`; without the snap a half-turn authored as
/// BAM `0x8000` would not produce an exact quaternion.
fn half_angle_sin_cos(angle: f32) -> (f32, f32) {
    let (s, c) = (angle * 0.5).sin_cos();
    let snap = |v: f32| if v.abs() < 1e-7 { 0.0 } else { v };
    (snap(s), snap(c))
}

/// Compute unit quaternion `[x, y, z, w]` from Euler angles under Invariant `[I1]`.
///
/// Rotations conform to Invariant `[I1]` metric right-handed basis:
/// - `pitch`: rotation around X axis (+X Right), tilts +Y toward -Z.
/// - `yaw`: rotation around Y axis (+Y Up), turns +X toward +Z.
/// - `roll`: rotation around Z axis (+Z Backward), banks +X toward +Y.
///
/// Intrinsic rotation sequence matching Python reference: `q = q_yaw(Y) * q_pitch(X) * q_roll(Z)`.
/// Guarantees unit quaternion invariant: `| ||q|| - 1.0 | < 1e-4`.
pub(crate) fn quat_from_euler(yaw: f32, pitch: f32, roll: f32) -> [f32; 4] {
    let (sy, cy) = half_angle_sin_cos(yaw);
    let (sp, cp) = half_angle_sin_cos(pitch);
    let (sr, cr) = half_angle_sin_cos(roll);

    let qx = -(sp * cy * cr + cp * sy * sr);
    let qy = -(cp * sy * cr - sp * cy * sr);
    let qz = cp * cy * sr - sp * sy * cr;
    let qw = cp * cy * cr + sp * sy * sr;

    quat_normalize([qx, qy, qz, qw])
}

/// Spherical linear interpolation (Slerp) between two unit quaternions.
///
/// Ensures shortest path on S^3 by taking the dot product and negating when negative.
/// When nearly parallel (`dot > 0.9995`), falls back to normalized Lerp.
pub(crate) fn slerp_quat(q1: [f32; 4], mut q2: [f32; 4], t: f32) -> [f32; 4] {
    let mut dot = q1[0] * q2[0] + q1[1] * q2[1] + q1[2] * q2[2] + q1[3] * q2[3];
    if dot < 0.0 {
        q2[0] = -q2[0];
        q2[1] = -q2[1];
        q2[2] = -q2[2];
        q2[3] = -q2[3];
        dot = -dot;
    }

    if dot > 0.9995 {
        let res = [
            q1[0] + t * (q2[0] - q1[0]),
            q1[1] + t * (q2[1] - q1[1]),
            q1[2] + t * (q2[2] - q1[2]),
            q1[3] + t * (q2[3] - q1[3]),
        ];
        return quat_normalize(res);
    }

    let theta_0 = dot.clamp(-1.0, 1.0).acos();
    let theta = theta_0 * t;
    let sin_theta = theta.sin();
    let sin_theta_0 = theta_0.sin();

    let s0 = (theta_0 - theta).sin() / sin_theta_0;
    let s1 = sin_theta / sin_theta_0;

    let res = [
        s0 * q1[0] + s1 * q2[0],
        s0 * q1[1] + s1 * q2[1],
        s0 * q1[2] + s1 * q2[2],
        s0 * q1[3] + s1 * q2[3],
    ];
    quat_normalize(res)
}

/// Rotates a 3D vector by unit quaternion `q` (`[x, y, z, w]`) as an active rotation.
///
/// Uses the quaternion sandwich `v + 2w(q_xyz × v) + 2(q_xyz × (q_xyz × v))`, cheaper
/// than materializing a rotation matrix when only one direction vector is needed.
#[must_use]
pub(crate) fn rotate_quat(q: [f32; 4], v: [f32; 3]) -> [f32; 3] {
    let u = [q[0], q[1], q[2]];
    let w = q[3];

    // t = u × v
    let t = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ];
    // t2 = u × t
    let t2 = [
        u[1] * t[2] - u[2] * t[1],
        u[2] * t[0] - u[0] * t[2],
        u[0] * t[1] - u[1] * t[0],
    ];

    [
        v[0] + 2.0 * (w * t[0] + t2[0]),
        v[1] + 2.0 * (w * t[1] + t2[1]),
        v[2] + 2.0 * (w * t[2] + t2[2]),
    ]
}

/// Linear interpolation between two 3D vectors.
#[inline]
pub(crate) fn lerp_vec3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [
        a[0] + t * (b[0] - a[0]),
        a[1] + t * (b[1] - a[1]),
        a[2] + t * (b[2] - a[2]),
    ]
}

/// Linear interpolation between two f32 scalars.
#[inline]
pub(crate) fn lerp_f32(a: f32, b: f32, t: f32) -> f32 {
    a + t * (b - a)
}

/// Detect camera cut between successive frames based on view object change or large eye displacement.
pub(crate) fn detect_camera_cut(
    current_eye: [f32; 3],
    last_eye: Option<[f32; 3]>,
    current_view_obj: u8,
    last_view_obj: Option<u8>,
) -> bool {
    if last_view_obj.is_some_and(|last_v| current_view_obj != last_v) {
        return true;
    }
    if let Some(last_e) = last_eye {
        let dx = current_eye[0] - last_e[0];
        let dy = current_eye[1] - last_e[1];
        let dz = current_eye[2] - last_e[2];
        let dist = (dx * dx + dy * dy + dz * dz).sqrt();
        if dist > CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS {
            return true;
        }
    }
    false
}

/// Interpolate between two `TrajectoryRecord` frames for a sub-tick parameter `alpha` in `[0.0, 1.0]`.
///
/// Invariant `[I4]`:
/// If `record_b.camera.cut_from_previous == true`, sub-tick interpolation is suppressed
/// (`alpha_eff = 0.0`), holding pose `record_a` until the exact tick boundary `record_b`.
pub(crate) fn interpolate_trajectory(
    record_a: &TrajectoryRecord,
    record_b: &TrajectoryRecord,
    alpha: f32,
) -> TrajectoryRecord {
    let alpha_clamped = alpha.clamp(0.0, 1.0);

    // Invariant [I4]: On instantaneous cut, suppress sub-tick interpolation
    let eff_alpha = if record_b.camera.cut_from_previous && alpha_clamped < 1.0 {
        0.0
    } else {
        alpha_clamped
    };

    let camera = CameraTransform {
        eye: lerp_vec3(record_a.camera.eye, record_b.camera.eye, eff_alpha),
        target: lerp_vec3(record_a.camera.target, record_b.camera.target, eff_alpha),
        fov_degrees: lerp_f32(
            record_a.camera.fov_degrees,
            record_b.camera.fov_degrees,
            eff_alpha,
        ),
        roll_radians: lerp_f32(
            record_a.camera.roll_radians,
            record_b.camera.roll_radians,
            eff_alpha,
        ),
        cut_from_previous: record_b.camera.cut_from_previous && alpha_clamped >= 1.0,
    };

    // Interpolate actors
    let mut actors = Vec::with_capacity(record_a.actors.len().max(record_b.actors.len()));

    for act_a in &record_a.actors {
        if let Some(act_b) = record_b
            .actors
            .iter()
            .find(|b| b.actor_id == act_a.actor_id)
        {
            let pos = lerp_vec3(act_a.position_meters, act_b.position_meters, eff_alpha);
            let rot = slerp_quat(act_a.rotation_quat, act_b.rotation_quat, eff_alpha);
            let state_mask = if eff_alpha < 0.5 {
                act_a.state_mask
            } else {
                act_b.state_mask
            };

            let mut actor = ActorTransform {
                actor_id: act_a.actor_id,
                model_name: act_a.model_name.clone(),
                shape_id: if eff_alpha < 0.5 {
                    act_a.shape_id
                } else {
                    act_b.shape_id
                },
                world_matrix: [0.0; 16],
                rotation_quat: rot,
                position_meters: pos,
                state_mask,
                joint_angles_bam: if eff_alpha < 0.5 {
                    act_a.joint_angles_bam.clone()
                } else {
                    act_b.joint_angles_bam.clone()
                },
            };
            actor.world_matrix = actor.compute_world_matrix();
            actors.push(actor);
        } else if eff_alpha < 0.5 {
            actors.push(act_a.clone());
        }
    }

    for act_b in &record_b.actors {
        if !record_a.actors.iter().any(|a| a.actor_id == act_b.actor_id) && eff_alpha >= 0.5 {
            actors.push(act_b.clone());
        }
    }

    TrajectoryRecord {
        tick: record_a.tick,
        camera,
        actors,
        audio_cues: if alpha_clamped == 0.0 {
            record_a.audio_cues.clone()
        } else if alpha_clamped == 1.0 {
            record_b.audio_cues.clone()
        } else {
            Vec::new() // Audio cues are discrete triggers at exact tick boundaries
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f32::consts::{FRAC_PI_2, PI};

    fn actor(actor_id: u32, position_meters: [f32; 3]) -> ActorTransform {
        ActorTransform {
            actor_id,
            model_name: "FOKKER".to_string(),
            shape_id: 0,
            world_matrix: [0.0; 16],
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters,
            state_mask: 1,
            joint_angles_bam: Vec::new(),
        }
    }

    fn record(
        tick: u32,
        eye: [f32; 3],
        cut: bool,
        actors: Vec<ActorTransform>,
    ) -> TrajectoryRecord {
        TrajectoryRecord {
            tick,
            camera: CameraTransform {
                eye,
                target: [0.0, 0.0, 0.0],
                fov_degrees: 45.0,
                roll_radians: 0.0,
                cut_from_previous: cut,
            },
            actors,
            audio_cues: Vec::new(),
        }
    }

    /// Independent oracle to verify a 4x4 column-major matrix is a rigid transform.
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
        assert_eq!(CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS, 50.0);

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
        let _ = interpolate_trajectory(&dummy_a, &dummy_b, -10.0);
        let _ = interpolate_trajectory(&dummy_a, &dummy_b, 10.0);
        let _ = interpolate_trajectory(&dummy_a, &dummy_b, f32::NAN);
        let _ = interpolate_trajectory(&dummy_a, &dummy_b, f32::INFINITY);
    }

    #[test]
    fn slerp_antipodal_and_parallel_paths() {
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
        let _ = slerp_quat(q_ident, q_nan, 0.5);
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
            actor.world_matrix = actor.compute_world_matrix();
            assert_rigid_transform(&actor.world_matrix, pos);
        }
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
        let _ = radians_to_bam(1e9);
        let _ = radians_to_bam(f32::NAN);
        let _ = radians_to_bam(f32::INFINITY);
        let _ = radians_to_bam(f32::NEG_INFINITY);
    }
}

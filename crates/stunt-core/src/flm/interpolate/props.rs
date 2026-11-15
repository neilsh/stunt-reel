//! Property tests over random unit quaternions, vectors and angles.
//!
//! The example tests in `tests` above sweep fixed grids; these check the defining
//! properties of each operation on inputs the grids do not reach.

use super::tests::quat_norm_diff;
use super::*;
use proptest::array::{uniform3, uniform4};
use proptest::prelude::*;
use std::f32::consts::PI;

fn unit_quat() -> impl Strategy<Value = [f32; 4]> {
    uniform4(-1.0f32..1.0)
        .prop_filter("too short to normalise", |q| quat_norm(*q) > 0.1)
        .prop_map(quat_normalize)
}

fn length(v: [f32; 3]) -> f32 {
    (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt()
}

/// Rotation angle between the orientations `a` and `b`, in `[0, pi]`.
///
/// `4 * atan2(|a - b|, |a + b|)` after aligning signs, which stays accurate for nearly
/// equal quaternions where `2 * acos(dot)` loses half its digits.
fn rotation_angle(a: [f32; 4], b: [f32; 4]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let b = if dot < 0.0 { b.map(|c| -c) } else { b };
    let diff = quat_norm([a[0] - b[0], a[1] - b[1], a[2] - b[2], a[3] - b[3]]);
    let sum = quat_norm([a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]);
    4.0 * diff.atan2(sum)
}

proptest! {
    #![proptest_config(crate::props::config())]

    /// `rotate_quat` and `ActorTransform::compute_world_matrix` are separate
    /// implementations of the same rotation.
    #[test]
    fn rotate_quat_matches_the_world_matrix(
        q in unit_quat(),
        v in uniform3(-100.0f32..100.0),
    ) {
        let actor = ActorTransform {
            actor_id: 1,
            model_name: String::new(),
            shape_id: 0,
            rotation_quat: q,
            position_meters: [0.0; 3],
            state_mask: 0,
            casts_shadow: false,
            joint_angles_bam: Vec::new(),
        };
        let m = actor.compute_world_matrix();
        let [c0, c1, c2, _] = m.as_chunks::<4>().0 else {
            unreachable!("a 4x4 matrix has four columns");
        };
        let by_matrix: [f32; 3] =
            std::array::from_fn(|row| c0[row] * v[0] + c1[row] * v[1] + c2[row] * v[2]);
        let by_quat = rotate_quat(q, v);
        let tolerance = 1e-4 * length(v).max(1.0);
        for axis in 0..3 {
            prop_assert!(
                (by_quat[axis] - by_matrix[axis]).abs() <= tolerance,
                "q {q:?} v {v:?}: quaternion {by_quat:?}, matrix {by_matrix:?}"
            );
        }
        prop_assert!((length(by_quat) - length(v)).abs() <= tolerance);
    }

    /// Slerp starts at `q1`, ends at `q2` and turns at a constant rate between them.
    #[test]
    fn slerp_turns_at_a_constant_rate(
        q1 in unit_quat(),
        q2 in unit_quat(),
        t in 0.0f32..=1.0,
    ) {
        prop_assert!(rotation_angle(slerp_quat(q1, q2, 0.0), q1) < 1e-3);
        prop_assert!(rotation_angle(slerp_quat(q1, q2, 1.0), q2) < 1e-3);

        let total = rotation_angle(q1, q2);
        let at_t = slerp_quat(q1, q2, t);
        prop_assert!(quat_norm_diff(at_t) < 1e-4);
        let done = rotation_angle(q1, at_t);
        let left = rotation_angle(at_t, q2);
        prop_assert!(
            (done - t * total).abs() < 2e-3 && (left - (1.0 - t) * total).abs() < 2e-3,
            "t {t}: turned {done} and left {left} of {total}"
        );
    }

    /// The interpolated roll ends on `b`'s angle and never turns more than half a circle.
    #[test]
    fn lerp_angle_takes_the_short_arc(a in -20.0f32..20.0, b in -20.0f32..20.0) {
        let end = lerp_angle(a, b, 1.0);
        let off = (end - b).rem_euclid(TAU);
        prop_assert!(off.min(TAU - off) < 1e-4 * 20.0, "a {a} b {b}: ended at {end}");
        prop_assert!((end - a).abs() <= PI + 1e-4 * 20.0, "a {a} b {b}: turned {}", end - a);
    }
}

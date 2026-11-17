//! Interpolation, kinematic conversions, and cut detection for `.FLM` choreography.
//!
//! Adheres strictly to:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, +Z Backward, -Z Forward)
//! - `[I4]` Discrete simulation ticks (50 Hz) with sub-tick interpolation and cut suppression

use crate::contracts::palette::PaletteControls;
use crate::contracts::trajectory::{
    ActorTransform, BankVariables, CameraTransform, TrajectoryRecord,
};
use std::f32::consts::TAU;

/// Threshold in meters for camera displacement triggering cut suppression `[I4]`.
pub(crate) const CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS: f32 = 50.0;

/// Convert a 16-bit Binary Angular Measurement (BAM) to radians `[0, 2*pi)`.
#[inline]
pub(crate) fn bam_to_radians(raw_u16: u16) -> f32 {
    (f32::from(raw_u16) / 65536.0) * TAU
}

/// Convert Stunt Island integer focal distance scalar to vertical FOV in degrees.
///
/// Uses aspect-corrected half-height `H_half` = 120.0 for 320x240 (4:3) Mode 13h:
/// `FOV_y = 2 * arctan(120.0 / focal_dist) * (180.0 / pi)`. This follows the unverified
/// camera-rig mock and no film sets `focal_dist`; films use
/// [`PLAYONE_FOV_Y_DEGREES`](crate::contracts::trajectory::PLAYONE_FOV_Y_DEGREES), measured
/// on square raster pixels.
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

/// Interpolates two angles in radians along the shorter arc, so a roll that crosses
/// the 0/2π wrap does not sweep the long way round.
#[inline]
pub(crate) fn lerp_angle(a: f32, b: f32, t: f32) -> f32 {
    let delta = (b - a + std::f32::consts::PI).rem_euclid(TAU) - std::f32::consts::PI;
    a + t * delta
}

/// Interpolates a slot's `.FLM` animate word as `PLAYONE` does (image `0x3EFE`): straight
/// from `a` to `b` as unsigned values, downward when `b < a`, never across the wrap.
///
/// The fraction is `t` in 1/65536 steps, the word `0x22E0` holds.
pub(crate) fn lerp_animate(a: u16, b: u16, t: f32) -> u16 {
    // Saturating float-to-int, then clamped: `t` 1.0 lands exactly on `b`.
    #[expect(clippy::cast_possible_truncation, reason = "clamped to 0..=65536")]
    let frac = ((t * 65536.0) as i64).clamp(0, 65536);
    let (a, b) = (i64::from(a), i64::from(b));
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "both words are u16 and frac is at most 65536, so the i64 maths cannot overflow"
    )]
    let value = a + (((b - a) * frac) >> 16);
    u16::try_from(value).unwrap_or(0)
}

/// Joint angles between two actors' `a` and `b` at `t`: slot 0, the animate word, by
/// [`lerp_animate`], every other slot from the nearer record.
fn interpolate_joints(a: &[(u16, u16)], b: &[(u16, u16)], t: f32) -> Vec<(u16, u16)> {
    let animate = |joints: &[(u16, u16)]| {
        joints
            .iter()
            .find(|&&(joint, _)| joint == 0)
            .map_or(0, |&(_, value)| value)
    };
    let nearer = if t < 0.5 { a } else { b };
    let value = lerp_animate(animate(a), animate(b), t);
    (value != 0)
        .then_some((0, value))
        .into_iter()
        .chain(nearer.iter().copied().filter(|&(joint, _)| joint != 0))
        .collect()
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
#[expect(
    clippy::float_cmp,
    reason = "an exact keyframe or endpoint hit is a sentinel, not a computed result"
)]
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
        roll_radians: lerp_angle(
            record_a.camera.roll_radians,
            record_b.camera.roll_radians,
            eff_alpha,
        ),
        cut_from_previous: record_b.camera.cut_from_previous && alpha_clamped >= 1.0,
        lens: lerp_variable(record_a.camera.lens, record_b.camera.lens, eff_alpha),
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

            actors.push(ActorTransform {
                actor_id: act_a.actor_id,
                model_name: act_a.model_name.clone(),
                shape_id: if eff_alpha < 0.5 {
                    act_a.shape_id
                } else {
                    act_b.shape_id
                },
                rotation_quat: rot,
                position_meters: pos,
                state_mask,
                casts_shadow: if eff_alpha < 0.5 {
                    act_a.casts_shadow
                } else {
                    act_b.casts_shadow
                },
                joint_angles_bam: interpolate_joints(
                    &act_a.joint_angles_bam,
                    &act_b.joint_angles_bam,
                    eff_alpha,
                ),
            });
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
        // Film variables keep interpolating across camera cuts, so they use the raw alpha.
        palette: lerp_palette(record_a.palette, record_b.palette, alpha_clamped),
        bank: BankVariables {
            var10: lerp_variable(record_a.bank.var10, record_b.bank.var10, alpha_clamped),
            var12: lerp_variable(record_a.bank.var12, record_b.bank.var12, alpha_clamped),
        },
    }
}

/// Interpolates a film variable as `PLAYONE` does (`CS:0x136F`): an unsigned `u16` lerp
/// whose step is rounded toward negative infinity.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "a lerp between two u16 values with `alpha` in 0..=1 stays in the u16 range"
)]
fn lerp_variable(from: u16, to: u16, alpha: f32) -> u16 {
    let from = f32::from(from);
    (from + (f32::from(to) - from) * alpha).floor() as u16
}

/// Interpolates the film palette variables with [`lerp_variable`].
fn lerp_palette(a: PaletteControls, b: PaletteControls, alpha: f32) -> PaletteControls {
    PaletteControls {
        sky: lerp_variable(a.sky, b.sky, alpha),
        brightness: lerp_variable(a.brightness, b.brightness, alpha),
        saturation: lerp_variable(a.saturation, b.saturation, alpha),
    }
}

#[cfg(test)]
mod props;
#[cfg(test)]
mod tests;

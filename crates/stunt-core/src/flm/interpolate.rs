//! Interpolation, kinematic conversions, and cut detection for `.FLM` choreography.
//!
//! Adheres strictly to:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, +Z Backward, -Z Forward)
//! - `[I4]` Discrete simulation ticks (20/30 Hz) with sub-tick interpolation and cut suppression

use crate::contracts::trajectory::{ActorTransform, CameraTransform, TrajectoryRecord};
use std::f32::consts::TAU;

/// Threshold in meters for camera displacement triggering cut suppression `[I4]`.
pub const CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS: f32 = 50.0;

/// Convert a 16-bit Binary Angular Measurement (BAM) to radians `[0, 2*pi)`.
#[inline]
pub fn bam_to_radians(raw_u16: u16) -> f32 {
    (raw_u16 as f32 / 65536.0) * TAU
}

/// Convert an angle in radians to a 16-bit BAM value.
#[inline]
pub fn radians_to_bam(rad: f32) -> u16 {
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
pub fn focal_to_fov_y(focal_dist: f32) -> f32 {
    if focal_dist <= 0.0 {
        return 45.0;
    }
    2.0 * (120.0 / focal_dist).atan().to_degrees()
}

/// Compute Euclidean norm of a quaternion `[x, y, z, w]`.
#[inline]
pub fn quat_norm(q: [f32; 4]) -> f32 {
    (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt()
}

/// Normalize quaternion `[x, y, z, w]` to unit length.
pub fn quat_normalize(q: [f32; 4]) -> [f32; 4] {
    let norm = quat_norm(q);
    if norm <= 1e-12 {
        [0.0, 0.0, 0.0, 1.0]
    } else {
        let inv = 1.0 / norm;
        [q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv]
    }
}

/// Compute deviation from unit length: `| ||q|| - 1.0 |`.
#[inline]
pub fn quat_norm_diff(q: [f32; 4]) -> f32 {
    (quat_norm(q) - 1.0).abs()
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
pub fn quat_from_euler(yaw: f32, pitch: f32, roll: f32) -> [f32; 4] {
    let cy = (yaw * 0.5).cos();
    let sy = (yaw * 0.5).sin();
    let cp = (pitch * 0.5).cos();
    let sp = (pitch * 0.5).sin();
    let cr = (roll * 0.5).cos();
    let sr = (roll * 0.5).sin();

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
pub fn slerp_quat(q1: [f32; 4], mut q2: [f32; 4], t: f32) -> [f32; 4] {
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

/// Linear interpolation between two 3D vectors.
#[inline]
pub fn lerp_vec3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [
        a[0] + t * (b[0] - a[0]),
        a[1] + t * (b[1] - a[1]),
        a[2] + t * (b[2] - a[2]),
    ]
}

/// Linear interpolation between two f32 scalars.
#[inline]
pub fn lerp_f32(a: f32, b: f32, t: f32) -> f32 {
    a + t * (b - a)
}

/// Detect camera cut between successive frames based on view object change or large eye displacement.
pub fn detect_camera_cut(
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
pub fn interpolate_trajectory(
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

/// Evaluates trajectory state at an arbitrary continuous tick index (e.g. 1.25) across a trajectory sequence.
pub fn evaluate_sub_tick(
    records: &[TrajectoryRecord],
    continuous_tick: f32,
) -> Option<TrajectoryRecord> {
    if records.is_empty() {
        return None;
    }
    if records.len() == 1 || continuous_tick <= records[0].tick as f32 {
        return records.first().cloned();
    }
    if continuous_tick >= records[records.len() - 1].tick as f32 {
        return records.last().cloned();
    }

    // Find the enclosing interval [i, i+1]
    for i in 0..records.len() - 1 {
        let t_curr = records[i].tick as f32;
        let t_next = records[i + 1].tick as f32;

        if continuous_tick >= t_curr && continuous_tick <= t_next {
            let dt = t_next - t_curr;
            let alpha = if dt > 1e-6 {
                (continuous_tick - t_curr) / dt
            } else {
                0.0
            };
            return Some(interpolate_trajectory(&records[i], &records[i + 1], alpha));
        }
    }

    records.last().cloned()
}

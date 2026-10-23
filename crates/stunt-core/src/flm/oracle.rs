//! Position error of an evaluated timeline against an oracle trajectory (GLOSSARY.md:
//! **Oracle trajectory**).
//!
//! Gate G04 bounds it: `RMSE_pos <= 0.01 m` against `tests/fixtures/oracle_intro_trajectory.json`.

use super::timeline::FilmTimeline;
use crate::contracts::trajectory::TrajectoryRecord;

/// Gate G04 maximum allowed position RMSE in meters.
pub const GATE_G04_RMSE_THRESHOLD_METERS: f32 = 0.01;

/// Compute position Root-Mean-Square Error (RMSE) in meters comparing an evaluated
/// timeline against an oracle trajectory.
///
/// Each oracle record's `tick` is a cumulative 50 Hz tick; the timeline is sampled at
/// that tick with [`FilmTimeline::sample`] (an empty timeline contributes no samples).
///
/// Matches the Python reference calculation in `python/stunt_reel/tac/streamer.py`.
/// Evaluates Euclidean distance squared for camera eye positions and all matching actor positions.
pub fn compute_position_rmse(timeline: &FilmTimeline, oracle: &[TrajectoryRecord]) -> f32 {
    let mut sq_errors = Vec::new();

    for base_rec in oracle {
        let Some(eval_rec) = timeline.sample(base_rec.tick as f32) else {
            continue;
        };

        // 1. Camera eye error
        let cx = eval_rec.camera.eye[0] - base_rec.camera.eye[0];
        let cy = eval_rec.camera.eye[1] - base_rec.camera.eye[1];
        let cz = eval_rec.camera.eye[2] - base_rec.camera.eye[2];
        sq_errors.push(cx * cx + cy * cy + cz * cz);

        // 2. Actor position error
        for base_act in &base_rec.actors {
            if let Some(eval_act) = eval_rec
                .actors
                .iter()
                .find(|a| a.actor_id == base_act.actor_id)
            {
                let ax = eval_act.position_meters[0] - base_act.position_meters[0];
                let ay = eval_act.position_meters[1] - base_act.position_meters[1];
                let az = eval_act.position_meters[2] - base_act.position_meters[2];
                sq_errors.push(ax * ax + ay * ay + az * az);
            }
        }
    }

    if sq_errors.is_empty() {
        return f32::INFINITY;
    }

    let mean_sq: f64 = sq_errors.iter().map(|&e| e as f64).sum::<f64>() / (sq_errors.len() as f64);
    mean_sq.sqrt() as f32
}

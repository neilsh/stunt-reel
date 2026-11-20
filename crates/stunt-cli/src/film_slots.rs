//! `stuntreel film-slots`: where a film's slots and camera stand at one tick, in DOS axes, as JSON.
//!
//! The state is [`stunt_core::flm::FilmTimeline::sample`] at the tick, the same interpolation
//! the renderer draws. `[I1]` positions are mapped back to the DOS axes the scenery tree and
//! `PLAYONE.EXE`'s draw walk work in (`(x, y, z) -> (-x, -y, z)`); `python/scripts/scene_walk.py`
//! replays the slot through the tree.

use std::fs;
use std::path::PathBuf;

use clap::{CommandFactory as _, Parser};
use serde_json::{Value, json};
use stunt_core::contracts::TrajectoryRecord;
use stunt_core::flm::FilmTimeline;

/// `film-slots` options as clap parses them.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel film-slots",
    about = "Print a film's slot and camera positions at one tick, in DOS axes, as JSON"
)]
struct Args {
    /// The film to sample
    #[arg(long, value_name = "X.FLM")]
    flm: PathBuf,
    /// The 50 Hz tick to sample at (fractional ticks interpolate)
    #[arg(long, value_name = "TICK")]
    tick: f32,
}

/// Help text for `stuntreel film-slots`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

/// Runs `stuntreel film-slots` with `args` (without the subcommand name).
pub(crate) fn run(args: impl IntoIterator<Item = String>) -> Result<(), String> {
    let argv = std::iter::once("stuntreel film-slots".to_string()).chain(args);
    let args = Args::try_parse_from(argv).unwrap_or_else(|e| e.exit());
    let bytes = fs::read(&args.flm).map_err(|e| format!("read {}: {e}", args.flm.display()))?;
    let timeline = FilmTimeline::from_bytes(&bytes)
        .map_err(|e| format!("parse {}: {e}", args.flm.display()))?;
    let record = timeline
        .sample(args.tick)
        .ok_or_else(|| format!("{} has no slices", args.flm.display()))?;
    println!("{}", slots_json(&record));
    Ok(())
}

/// The record's camera and drawn slots as JSON in DOS axes.
fn slots_json(record: &TrajectoryRecord) -> Value {
    let slots: Vec<Value> = record
        .actors
        .iter()
        .map(|actor| {
            json!({
                "slot": actor.actor_id,
                "shape": actor.shape_id,
                "position": dos(actor.position_meters),
                "view": actor.view,
                "shadow": actor.casts_shadow,
            })
        })
        .collect();
    json!({
        "tick": record.tick,
        "eye": dos(record.camera.eye),
        "target": dos(record.camera.target),
        "slots": slots,
    })
}

/// `[I1]` metres to DOS axes: the map is its own inverse, `(x, y, z) -> (-x, -y, z)`.
fn dos(p: [f32; 3]) -> [f32; 3] {
    [-p[0] + 0.0, -p[1] + 0.0, p[2]]
}

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::contracts::{ActorTransform, BankVariables, CameraTransform, PaletteControls};

    #[test]
    fn slots_json_maps_positions_back_to_dos_axes() {
        let record = TrajectoryRecord {
            camera: CameraTransform {
                eye: [1.0, 2.0, 3.0],
                target: [-4.0, 0.0, 5.0],
                ..CameraTransform::default()
            },
            actors: vec![ActorTransform {
                actor_id: 11,
                model_name: "ACTOR_11".to_string(),
                shape_id: 0x0107,
                rotation_quat: [0.0, 0.0, 0.0, 1.0],
                position_meters: [3192.5, 1.5, 2489.0],
                state_mask: 1,
                casts_shadow: true,
                view: false,
                joint_angles_bam: Vec::new(),
            }],
            tick: 871,
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
            bank: BankVariables::default(),
        };
        let value = slots_json(&record);
        assert_eq!(value["eye"], json!([-1.0, -2.0, 3.0]));
        assert_eq!(value["target"], json!([4.0, 0.0, 5.0]));
        assert_eq!(value["slots"][0]["slot"], 11);
        assert_eq!(value["slots"][0]["shape"], 0x0107);
        assert_eq!(
            value["slots"][0]["position"],
            json!([-3192.5, -1.5, 2489.0])
        );
        assert_eq!(value["slots"][0]["shadow"], true);
    }
}

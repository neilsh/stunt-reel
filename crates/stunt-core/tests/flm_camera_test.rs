//! Camera orientation for a real film: the view slot drives the look direction.
//!
//! Corpus-gated: `corpus/` is gitignored, so this runs only on a machine carrying the
//! Stunt Island demo archive:
//!
//! ```text
//! cargo test -p stunt-core --test flm_camera_test -- --ignored
//! ```

use std::fs;
use std::path::{Path, PathBuf};

use stunt_core::flm::{CAMERA_LOOKAHEAD_METERS, FlmPlayer};

/// Resource ID of the `.SOD` chunk `CTRY.FLM` draws on its opening ticks.
const CTRY_ACTOR_SHAPE: u16 = 0x7F37;

fn corpus_film() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("corpus")
        .join("stisldem")
        .join("VAULT")
        .join("CTRY.FLM")
}

/// Euclidean distance between two metric positions.
fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    let dx = a[0] - b[0];
    let dy = a[1] - b[1];
    let dz = a[2] - b[2];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

#[test]
#[ignore = "requires corpus/stisldem/VAULT/CTRY.FLM"]
fn test_ctry_view_slot_directs_camera_at_drawn_actor() {
    let path = corpus_film();
    let bytes = fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));

    let mut player = FlmPlayer::new(&bytes).expect("CTRY.FLM parses");
    let mut records = Vec::new();
    while let Some(record) = player.step_tick() {
        records.push(record);
    }

    let record = records
        .iter()
        .find(|record| record.tick == 1)
        .unwrap_or_else(|| {
            panic!(
                "CTRY.FLM produced no tick 1 record ({} total)",
                records.len()
            )
        });

    let drawn: Vec<_> = record
        .actors
        .iter()
        .filter(|actor| actor.shape_id == CTRY_ACTOR_SHAPE)
        .collect();
    assert_eq!(
        drawn.len(),
        1,
        "tick 1 must carry exactly one drawn actor with shape_id 0x{CTRY_ACTOR_SHAPE:04X}, got {:?}",
        record
            .actors
            .iter()
            .map(|actor| actor.shape_id)
            .collect::<Vec<_>>()
    );

    let eye = record.camera.eye;
    let lookahead = distance(record.camera.target, eye);
    assert!(
        (lookahead - CAMERA_LOOKAHEAD_METERS).abs() < 1.0,
        "look-at distance {lookahead:.3} m should be {CAMERA_LOOKAHEAD_METERS:.0} m"
    );
    assert_ne!(
        record.camera.target,
        [0.0, 0.0, 0.0],
        "camera target must come from the view slot, not the origin default"
    );

    let actor_distance = distance(eye, drawn[0].position_meters);
    assert!(
        actor_distance < 10.0,
        "drawn actor sits {actor_distance:.2} m from the view slot, expected < 10 m"
    );
}

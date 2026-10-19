use std::fs;
use std::path::PathBuf;
use stunt_core::contracts::ArchiveFormat;
#[cfg(feature = "serde")]
use stunt_core::contracts::TrajectoryRecord;
use stunt_core::vfs::detect_and_parse;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
}

#[test]
fn test_synthetic_minimal_res_fixture() {
    let path = fixtures_dir().join("synthetic_minimal.res");
    assert!(path.exists(), "synthetic_minimal.res must exist");

    let data = fs::read(&path).expect("read synthetic_minimal.res");
    assert_eq!(data.len(), 72, "file size must be 72 bytes");

    // Verify 'RS' magic header per [fmt res]
    assert_eq!(&data[0..2], b"RS");

    // Parse the synthetic container via VFS parser
    let archive = detect_and_parse(&data).expect("parse synthetic_minimal.res");

    assert_eq!(archive.format, ArchiveFormat::Res);
    assert_eq!(archive.entries.len(), 2);

    // Verify exact 16-byte payloads
    let plane_entry = archive.get("PLANE.SOD").expect("PLANE.SOD must exist");
    assert_eq!(plane_entry.data.len(), 16);
    assert_eq!(plane_entry.data, &data[40..56]);
    assert_eq!(plane_entry.source_offset, 40);
    assert!(!plane_entry.was_compressed);

    let prop_entry = archive.get("PROP.SOD").expect("PROP.SOD must exist");
    assert_eq!(prop_entry.data.len(), 16);
    assert_eq!(prop_entry.data, &data[56..72]);
    assert_eq!(prop_entry.source_offset, 56);
    assert!(!prop_entry.was_compressed);

    // Invariant [I8]: Case-insensitive lookups
    assert!(archive.get("plane.sod").is_some());
    assert!(archive.get("Plane.Sod").is_some());
    assert!(archive.get("pLaNe.SoD").is_some());
    assert!(archive.get("prop.sod").is_some());
    assert!(archive.get("Prop.Sod").is_some());
}

#[test]
fn test_synthetic_minimal_flm_fixture() {
    let path = fixtures_dir().join("synthetic_minimal.flm");
    assert!(path.exists(), "synthetic_minimal.flm must exist");

    let data = fs::read(&path).expect("read synthetic_minimal.flm");
    assert!(data.len() >= 4);

    // Verify 'FILM' magic header per [fmt flm]
    assert_eq!(&data[0..4], b"FILM");
}

#[cfg(feature = "serde")]
#[test]
fn test_oracle_intro_trajectory_fixture() {
    let path = fixtures_dir().join("oracle_intro_trajectory.json");
    assert!(path.exists(), "oracle_intro_trajectory.json must exist");

    let content = fs::read_to_string(&path).expect("read oracle_intro_trajectory.json");
    let records: Vec<TrajectoryRecord> =
        serde_json::from_str(&content).expect("deserialization of oracle trajectory");

    assert_eq!(records.len(), 2);

    // Tick 0 assertions
    assert_eq!(records[0].tick, 0);
    assert_eq!(records[0].camera.eye, [0.0, 10.0, 50.0]);
    assert_eq!(records[0].camera.target, [0.0, 10.0, 1050.0]);
    assert_eq!(records[0].camera.fov_degrees, 45.0);
    assert_eq!(records[0].actors.len(), 1);
    assert_eq!(records[0].actors[0].model_name, "FOKKER");
    assert_eq!(records[0].actors[0].shape_id, 1);
    assert_eq!(records[0].actors[0].position_meters, [0.0, 10.0, 0.0]);
    assert_eq!(records[0].audio_cues.len(), 1);
    assert_eq!(records[0].audio_cues[0].sample_name, "ENGINE.VOC");

    // Tick 1 assertions (camera and actor moved per Invariant [I4])
    assert_eq!(records[1].tick, 1);
    assert_eq!(records[1].camera.eye, [0.0, 10.0, 49.5]);
    assert_eq!(records[1].actors[0].position_meters, [0.0, 10.0, 0.5]);
    assert!(records[1].audio_cues.is_empty());
}

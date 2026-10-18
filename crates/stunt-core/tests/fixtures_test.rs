use std::fs;
use std::path::PathBuf;
use stunt_core::contracts::{ArchiveFormat, TrajectoryRecord, VfsArchive, VfsEntry};

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

    // Manually parse the synthetic container into a VfsArchive
    let mut archive = VfsArchive::new(ArchiveFormat::Res);

    // Extract entries from the known synthetic offsets
    archive.insert(VfsEntry {
        name: "PLANE.SOD".to_string(),
        data: data[40..56].to_vec(),
        source_offset: 40,
        was_compressed: false,
    });
    archive.insert(VfsEntry {
        name: "PROP.SOD".to_string(),
        data: data[56..72].to_vec(),
        source_offset: 56,
        was_compressed: false,
    });

    assert_eq!(archive.format, ArchiveFormat::Res);
    assert_eq!(archive.entries.len(), 2);
    assert!(archive.get("plane.sod").is_some());
    assert_eq!(archive.get_bytes("PLANE.SOD").unwrap().len(), 16);
    assert_eq!(archive.get_bytes("PROP.SOD").unwrap().len(), 16);
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
    assert_eq!(records[0].camera.target, [0.0, 0.0, 0.0]);
    assert_eq!(records[0].camera.fov_degrees, 45.0);
    assert_eq!(records[0].actors.len(), 1);
    assert_eq!(records[0].actors[0].model_name, "FOKKER");
    assert_eq!(records[0].actors[0].position_meters, [0.0, 10.0, 0.0]);
    assert_eq!(records[0].audio_cues.len(), 1);
    assert_eq!(records[0].audio_cues[0].sample_name, "ENGINE.VOC");

    // Tick 1 assertions (camera and actor moved per Invariant [I4])
    assert_eq!(records[1].tick, 1);
    assert_eq!(records[1].camera.eye, [0.0, 10.0, 49.5]);
    assert_eq!(records[1].actors[0].position_meters, [0.0, 10.0, 0.5]);
    assert!(records[1].audio_cues.is_empty());
}

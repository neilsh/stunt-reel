//! `OP_TAP` (`0x022E`) anchor-table resolution.
//!
//! `tests/fixtures/synthetic_tap.sod` references three `synthetic_anchors.bin`
//! records by byte offset; a fixed four-word operand skip would swallow the
//! following `OP_COLOR`.

use std::path::PathBuf;

use stunt_core::sod::{
    OP_TAP, SodAnchorPoint, SodError, SodStop, SodStopReason, transpile_sod, transpile_sod_lenient,
};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
}

fn anchors() -> Vec<SodAnchorPoint> {
    let data =
        std::fs::read(fixtures_dir().join("synthetic_anchors.bin")).expect("read anchor fixture");
    data.as_chunks::<28>()
        .0
        .iter()
        .map(|record| SodAnchorPoint {
            x: i16::from_le_bytes([record[0], record[1]]),
            y: i16::from_le_bytes([record[2], record[3]]),
            z: i16::from_le_bytes([record[4], record[5]]),
        })
        .collect()
}

fn header() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&0x000Cu16.to_le_bytes());
    bytes.extend_from_slice(&[0u8; 8]);
    bytes
}

fn tap(op_reg: u16, count: u16, offsets: &[u16]) -> Vec<u8> {
    let mut bytes = header();
    bytes.extend_from_slice(&OP_TAP.to_le_bytes());
    bytes.extend_from_slice(&op_reg.to_le_bytes());
    bytes.extend_from_slice(&count.to_le_bytes());
    for offset in offsets {
        bytes.extend_from_slice(&offset.to_le_bytes());
    }
    bytes.extend_from_slice(&0x0195u16.to_le_bytes());
    bytes
}

#[test]
fn test_tap_rejects_misaligned_anchor_offset() {
    let bytes = tap(0, 1, &[2]);
    assert!(matches!(
        transpile_sod(&bytes, "TAP", Some(&anchors())),
        Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
    ));
}

#[test]
fn test_tap_rejects_misaligned_register_offset() {
    let bytes = tap(6, 1, &[0]);
    assert!(matches!(
        transpile_sod(&bytes, "TAP", Some(&anchors())),
        Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
    ));
}

#[test]
fn test_tap_rejects_empty_and_oversized_counts() {
    for count in [0u16, 65] {
        let bytes = tap(0, count, &[]);
        assert!(
            matches!(
                transpile_sod(&bytes, "TAP", Some(&anchors())),
                Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
            ),
            "count {count} must be rejected"
        );
    }
}

#[test]
fn test_tap_anchor_index_out_of_range_is_a_missing_anchor_stop() {
    let single = [SodAnchorPoint { x: 1, y: 0, z: 2 }];
    let bytes = tap(0, 1, &[28]);

    assert_eq!(
        transpile_sod(&bytes, "TAP", Some(&single)).unwrap_err(),
        SodError::MissingAnchors {
            opcode: OP_TAP,
            offset: 10,
        }
    );

    let (_, stop) = transpile_sod_lenient(&bytes, "TAP", Some(&single)).expect("lenient stop");
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: OP_TAP,
            reason: SodStopReason::MissingAnchors,
        })
    );
}

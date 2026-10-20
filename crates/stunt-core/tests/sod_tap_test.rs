//! `OP_TAP` (`0x022E`) anchor-table resolution.
//!
//! `tests/fixtures/synthetic_tap.sod` references three `synthetic_anchors.bin`
//! records by byte offset; a fixed four-word operand skip would swallow the
//! following `OP_COLOR`.

use std::path::PathBuf;

use stunt_core::contracts::SodModelIr;
use stunt_core::sod::{
    OP_TAP, SodAnchorPoint, SodError, SodStop, SodStopReason, execute_sod_vm, execute_sod_vm_impl,
    transpile_sod,
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

fn tap_bytes() -> Vec<u8> {
    std::fs::read(fixtures_dir().join("synthetic_tap.sod")).expect("read TAP fixture")
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

fn cross(a: [f32; 3], b: [f32; 3], c: [f32; 3]) -> [f32; 3] {
    let ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    [
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    ]
}

#[test]
fn test_tap_resolves_anchor_points_into_non_degenerate_polygon() {
    let table = anchors();
    let (_, polygons) = execute_sod_vm(&tap_bytes(), Some(&table)).expect("TAP resolves");

    assert_eq!(polygons.len(), 1);
    let vertices = &polygons[0].vertices;
    assert_eq!(vertices.len(), 3);
    // Header scale index 1 = 0.5 m/unit; raw anchors map through [-x, -y, z].
    assert_eq!(vertices[0], [-50.0, 0.0, 100.0]);
    assert_eq!(vertices[1], [-150.0, 250.0, 200.0]);
    assert_eq!(vertices[2], [-250.0, 0.0, 300.0]);

    let area = cross(vertices[0], vertices[1], vertices[2]);
    assert!(
        area[0].abs() + area[1].abs() + area[2].abs() > 1.0,
        "TAP polygon must have non-zero area, got {area:?}"
    );
}

#[test]
fn test_tap_variable_operand_width_preserves_following_opcodes() {
    let table = anchors();
    let (_, polygons, stop) =
        execute_sod_vm_impl(&tap_bytes(), true, Some(&table)).expect("lenient decode");
    assert_eq!(stop, None, "count=3 TAP must not desynchronize the stream");
    assert_eq!(polygons.len(), 1);
    assert_eq!(
        polygons[0].palette_index, 40,
        "OP_COLOR after the three anchor words must be decoded"
    );

    let ir: SodModelIr =
        transpile_sod(&tap_bytes(), "TAP_MODEL", Some(&table)).expect("transpile TAP model");
    assert_eq!(ir.vertices.len(), 3);
    assert_eq!(ir.indices.len(), 3);
}

#[test]
fn test_tap_without_anchor_table_is_a_distinct_error() {
    let bytes = tap_bytes();
    assert_eq!(
        execute_sod_vm(&bytes, None),
        Err(SodError::MissingAnchors {
            opcode: OP_TAP,
            offset: 10,
        })
    );

    let (_, polygons, stop) = execute_sod_vm_impl(&bytes, true, None).expect("lenient stop");
    assert!(polygons.is_empty());
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: OP_TAP,
            reason: SodStopReason::MissingAnchors,
        })
    );
}

#[test]
fn test_tap_rejects_misaligned_anchor_offset() {
    let bytes = tap(0, 1, &[2]);
    assert!(matches!(
        execute_sod_vm(&bytes, Some(&anchors())),
        Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
    ));
}

#[test]
fn test_tap_rejects_misaligned_register_offset() {
    let bytes = tap(6, 1, &[0]);
    assert!(matches!(
        execute_sod_vm(&bytes, Some(&anchors())),
        Err(SodError::MalformedOpcode { opcode: OP_TAP, .. })
    ));
}

#[test]
fn test_tap_rejects_empty_and_oversized_counts() {
    for count in [0u16, 65] {
        let bytes = tap(0, count, &[]);
        assert!(
            matches!(
                execute_sod_vm(&bytes, Some(&anchors())),
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
        execute_sod_vm(&bytes, Some(&single)),
        Err(SodError::MissingAnchors {
            opcode: OP_TAP,
            offset: 10,
        })
    );

    let (_, _, stop) = execute_sod_vm_impl(&bytes, true, Some(&single)).expect("lenient stop");
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: OP_TAP,
            reason: SodStopReason::MissingAnchors,
        })
    );
}

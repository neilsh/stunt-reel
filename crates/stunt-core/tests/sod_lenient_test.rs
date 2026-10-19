//! Lenient `.SOD` decode: geometry parsed before an unknown opcode is kept.

use stunt_core::sod::{SodError, SodStop, execute_sod_vm_impl, transpile_sod_lenient};

/// `0x000C` header (bounding size, ground offset, flags/scale, collision meta) followed
/// by opcode `0x02B5`, which is outside the decoded opcode table.
fn stop_after_header() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&0x000Cu16.to_le_bytes());
    bytes.extend_from_slice(&[0u8; 8]);
    bytes.extend_from_slice(&0x02B5u16.to_le_bytes());
    bytes
}

#[test]
fn test_lenient_decode_reports_stop_and_keeps_geometry() {
    let bytes = stop_after_header();

    let strict = execute_sod_vm_impl(&bytes, false);
    assert_eq!(
        strict,
        Err(SodError::InvalidOpcode {
            opcode: 0x02B5,
            offset: 10,
        })
    );

    let (header, polygons, stop) = execute_sod_vm_impl(&bytes, true).expect("lenient decode");
    assert_eq!(header.bounding_size, 0);
    assert!(polygons.is_empty());
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: 0x02B5,
        })
    );

    let (ir, stop) = transpile_sod_lenient(&bytes, "STOPPED").expect("lenient transpile");
    assert_eq!(ir.name, "STOPPED");
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: 0x02B5,
        })
    );
}

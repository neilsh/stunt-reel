#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Census decode: opcodes outside the execution table are stepped over by their
//! `CENSUS_SKIPS` width and recorded on the shape's decode record, while strict and lenient
//! decodes still stop on them.
//!
//! The masked stream is synthesized inline rather than committed under `tests/fixtures/`:
//! only this test consumes it, and a fixture file would need a README row describing bytes
//! nothing else reads.

use stunt_core::sod::{
    DecodeMode, DecodeRecord, OP_COLOR, OP_RETURN, OP_TAP, SodError, SodStop, SodStopReason,
    census_skip, decode_sod,
};

const PUSHCENTRE: u16 = 0x007E;
const MOVECENTRE: u16 = 0x0090;
const SHADE1: u16 = 0x0144;
const GOSUB: u16 = 0x01A7;
const ANIMATE: u16 = 0x01F8;
const BVGT: u16 = 0x02FD;

fn model(words: &[u16]) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&0x000Cu16.to_le_bytes());
    bytes.extend_from_slice(&[0u8; 8]);
    for word in words {
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    bytes
}

fn stopped(offset: usize, opcode: u16, reason: SodStopReason) -> SodStop {
    SodStop {
        offset,
        opcode,
        reason,
    }
}

/// Group-C-like stream: every unimplemented opcode carries operands that look like
/// opcodes, so a wrong width would surface as a different opcode list.
fn masked_stream() -> Vec<u8> {
    model(&[
        PUSHCENTRE, // offset 10, no operands
        MOVECENTRE, // 12
        OP_COLOR,   // operand
        BVGT,       // 16
        OP_RETURN, OP_RETURN, OP_RETURN, OP_COLOR, // 24
        7, ANIMATE, // 28: reg, parameter, selector, count = 2, then two resource IDs
        0, OP_RETURN, OP_RETURN, 2, OP_RETURN, OP_RETURN,
        OP_TAP, // 42: reg, count = 2, then two anchor offsets
        0, 2, OP_RETURN, 28, OP_RETURN, // 52
        SHADE1,    // after the first RETURN: never reached
        0, 0,
    ])
}

fn census(data: &[u8]) -> DecodeRecord {
    let ir = decode_sod(data, "CENSUS", None, DecodeMode::Census).expect("census decode");
    assert!(
        ir.vertices.is_empty() && ir.indices.is_empty(),
        "census mode builds no geometry"
    );
    ir.decode()
        .expect("a census decode carries a record")
        .clone()
}

#[test]
fn census_steps_over_and_records_each_unimplemented_opcode() {
    let record = census(&masked_stream());
    assert_eq!(
        record.stepped_over,
        vec![
            stopped(10, PUSHCENTRE, SodStopReason::UnknownOpcode),
            stopped(12, MOVECENTRE, SodStopReason::UnknownOpcode),
            stopped(16, BVGT, SodStopReason::UnknownOpcode),
            stopped(28, ANIMATE, SodStopReason::UnknownOpcode),
            stopped(42, OP_TAP, SodStopReason::MissingAnchors),
        ]
    );
    assert_eq!(record.stop, None);
    assert_eq!(record.returned_at, Some(52));
}

#[test]
fn census_records_the_masked_opcodes_behind_the_first_blocking_one() {
    // PUSHCENTRE blocks first; ANIMATE and TAP are masked behind it but still walked. The
    // record keeps stream order, so entry 0 is the first blocking opcode and the rest sit
    // behind it.
    let record = census(&model(&[
        PUSHCENTRE, ANIMATE, 0, 0, 0, 0, OP_TAP, 0, 1, 0, OP_RETURN,
    ]));
    assert_eq!(
        record.stepped_over[0],
        stopped(10, PUSHCENTRE, SodStopReason::UnknownOpcode)
    );
    assert_eq!(record.stepped_over[1].opcode, ANIMATE);
    assert_eq!(record.stepped_over[2].opcode, OP_TAP);
    assert_eq!(record.returned_at, Some(30));
    assert_eq!(record.stop, None);
}

#[test]
fn lenient_and_strict_decodes_still_stop_at_the_blocking_opcode() {
    let bytes = masked_stream();
    let ir = decode_sod(&bytes, "CENSUS", None, DecodeMode::Lenient).expect("lenient decode");
    assert_eq!(
        ir.decode().and_then(|record| record.stop),
        Some(stopped(10, PUSHCENTRE, SodStopReason::UnknownOpcode))
    );
    assert_eq!(
        decode_sod(&bytes, "CENSUS", None, DecodeMode::Strict).map(|_| ()),
        Err(SodError::InvalidOpcode {
            opcode: PUSHCENTRE,
            offset: 10,
        })
    );
}

#[test]
fn census_steps_over_gosub_without_following_it() {
    // The GOSUB target (+8 bytes) holds an opcode with no width; a linear walk never sees it.
    let record = census(&model(&[GOSUB, 8, OP_RETURN, 0x0FFF]));
    assert_eq!(
        record.stepped_over,
        vec![stopped(10, GOSUB, SodStopReason::UnknownOpcode)]
    );
    assert_eq!(record.returned_at, Some(14));
    assert_eq!(record.stop, None);
}

#[test]
fn census_stops_on_an_opcode_without_a_width() {
    assert_eq!(census_skip(0x0FFF), None);
    let record = census(&model(&[SHADE1, 0, 0, 0x0FFF, OP_RETURN]));
    assert_eq!(
        record.stepped_over,
        vec![stopped(10, SHADE1, SodStopReason::UnknownOpcode)]
    );
    assert_eq!(
        record.stop,
        Some(stopped(16, 0x0FFF, SodStopReason::UnknownOpcode))
    );
    assert_eq!(record.returned_at, None);
}

#[test]
fn census_without_return_ends_at_end_of_data() {
    let record = census(&model(&[PUSHCENTRE]));
    assert_eq!(
        record.stepped_over,
        vec![stopped(10, PUSHCENTRE, SodStopReason::UnknownOpcode)]
    );
    assert_eq!(record.stop, None);
    assert_eq!(record.returned_at, None);
}

#[test]
fn census_of_a_fully_implemented_model_records_nothing() {
    let record = census(&model(&[OP_COLOR, 3, OP_RETURN]));
    assert!(record.stepped_over.is_empty());
    assert_eq!(record.stop, None);
    assert_eq!(record.returned_at, Some(14));
}

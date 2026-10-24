//! Census walk ([`walk_sod`]): unimplemented opcodes are stepped over by their
//! `CENSUS_SKIPS` width and logged, while lenient and strict decodes still stop on them.

use stunt_core::sod::{
    OP_COLOR, OP_RETURN, OP_TAP, SodError, SodSkip, SodStop, SodStopReason, SodWalkEnd,
    census_skip, transpile_sod, transpile_sod_lenient, walk_sod,
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

fn skipped(offset: usize, opcode: u16) -> SodSkip {
    SodSkip {
        offset,
        opcode,
        reason: SodStopReason::UnknownOpcode,
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

#[test]
fn walk_skips_and_logs_each_unimplemented_opcode() {
    let walk = walk_sod(&masked_stream()).expect("census walk");
    assert_eq!(
        walk.skipped,
        vec![
            skipped(10, PUSHCENTRE),
            skipped(12, MOVECENTRE),
            skipped(16, BVGT),
            skipped(28, ANIMATE),
            SodSkip {
                offset: 42,
                opcode: OP_TAP,
                reason: SodStopReason::MissingAnchors,
            },
        ]
    );
    assert_eq!(walk.end, SodWalkEnd::Return(52));
}

#[test]
fn lenient_and_strict_decodes_still_stop_at_the_blocking_opcode() {
    let bytes = masked_stream();
    let (_, stop) = transpile_sod_lenient(&bytes, "CENSUS", None).expect("lenient decode");
    assert_eq!(
        stop,
        Some(SodStop {
            offset: 10,
            opcode: PUSHCENTRE,
            reason: SodStopReason::UnknownOpcode,
        })
    );
    assert_eq!(
        transpile_sod(&bytes, "CENSUS", None).map(|_| ()),
        Err(SodError::InvalidOpcode {
            opcode: PUSHCENTRE,
            offset: 10,
        })
    );
}

#[test]
fn walk_steps_over_gosub_without_following_it() {
    // The GOSUB target (+8 bytes) holds an opcode with no width; a linear walk never sees it.
    let walk = walk_sod(&model(&[GOSUB, 8, OP_RETURN, 0x0FFF])).expect("census walk");
    assert_eq!(walk.skipped, vec![skipped(10, GOSUB)]);
    assert_eq!(walk.end, SodWalkEnd::Return(14));
}

#[test]
fn walk_ends_on_an_opcode_without_a_width() {
    assert_eq!(census_skip(0x0FFF), None);
    let walk = walk_sod(&model(&[SHADE1, 0, 0, 0x0FFF, OP_RETURN])).expect("census walk");
    assert_eq!(walk.skipped, vec![skipped(10, SHADE1)]);
    assert_eq!(
        walk.end,
        SodWalkEnd::Unskippable(SodStop {
            offset: 16,
            opcode: 0x0FFF,
            reason: SodStopReason::UnknownOpcode,
        })
    );
}

#[test]
fn walk_without_return_ends_at_end_of_data() {
    let walk = walk_sod(&model(&[PUSHCENTRE])).expect("census walk");
    assert_eq!(walk.skipped, vec![skipped(10, PUSHCENTRE)]);
    assert_eq!(walk.end, SodWalkEnd::EndOfData);
}

#[test]
fn walk_of_a_fully_implemented_model_skips_nothing() {
    let walk = walk_sod(&model(&[OP_COLOR, 3, OP_RETURN])).expect("census walk");
    assert!(walk.skipped.is_empty());
    assert_eq!(walk.end, SodWalkEnd::Return(14));
}

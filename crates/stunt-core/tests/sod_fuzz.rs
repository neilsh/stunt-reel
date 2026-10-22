//! Never-panics and structured-error coverage for the `.SOD` transpiler (Seam 3).
//!
//! `transpile_sod` consumes untrusted bytes, so these tests assert that it never panics and
//! that malformed input comes back as a `SodError`. Inputs are generated, mutated or swept
//! across a matrix; the pass condition is "no panic" (plus the expected `SodError` variant or
//! a coarse success invariant where noted). Named single-input behaviour with exact expected
//! results lives in `sod_spec.rs`.
//!
//! Matrices:
//! - header truncations (0..10 bytes) and invalid magic words
//! - truncated operand payloads for every known opcode
//! - register offset wrapping (unaligned, >= 1024 registers, `u16::MAX`), `OP_IPG` start registers
//!   near register 1023 and `OP_VECTORS` runs that wrap past register 1023
//! - scale indices 0..=255 and `OP_SHLV` / `OP_SHRV` shift amounts, including >= 32
//! - polygons with fewer than 3 vertices and a 500-polygon model
//!
//! Fuzz (fixed-seed `XorShift64`, 10,000 iterations each): random bytecode behind a valid
//! header, random sequences of valid opcodes with random operands, and bit-flipped /
//! overwritten / truncated / extended copies of a valid model.

use std::panic::{AssertUnwindSafe, catch_unwind};

use stunt_core::sod::{
    OP_ADDV, OP_BLOCK, OP_CLRV, OP_COLOR, OP_DOT, OP_GETV, OP_GVPOLY, OP_GVPOLY16, OP_ID, OP_IFVIS,
    OP_INTV, OP_IPG, OP_LINECOL, OP_MOVETO, OP_NEGV, OP_PERFDISK, OP_PERS, OP_POLYZ, OP_PUTV,
    OP_REJ, OP_RETURN, OP_SHADES, OP_SHLV, OP_SHRV, OP_SORT, OP_SPHERE, OP_SUBV, OP_VEC,
    OP_VECTORS, OP_ZLINETO, compute_scale_factor,
};
use stunt_core::sod::{SodError, transpile_sod};

/// Simple deterministic PRNG (Xorshift64) to avoid external crate dependencies.
struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x8543_5897_4EC5_D643
            } else {
                seed
            },
        }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    fn next_u8(&mut self) -> u8 {
        self.next_u64() as u8
    }

    fn next_range(&mut self, min: usize, max: usize) -> usize {
        if min >= max {
            return min;
        }
        let span = (max - min) as u64;
        min + (self.next_u64() % span) as usize
    }

    fn fill_bytes(&mut self, buf: &mut [u8]) {
        for b in buf.iter_mut() {
            *b = self.next_u8();
        }
    }
}

fn make_sod_header(
    bounding_size: u16,
    ground_y_offset: i16,
    scale_index: u8,
    header_flags: u8,
) -> Vec<u8> {
    let mut header = Vec::with_capacity(10);
    header.extend_from_slice(&OP_ID.to_le_bytes());
    header.extend_from_slice(&bounding_size.to_le_bytes());
    header.extend_from_slice(&ground_y_offset.to_le_bytes());
    let flags_scale = (scale_index as u16) | ((header_flags as u16) << 8);
    header.extend_from_slice(&flags_scale.to_le_bytes());
    header.extend_from_slice(&0u16.to_le_bytes()); // collision_meta
    header
}

// =============================================================================
// Header and opcode truncation, invalid magic
// =============================================================================

/// Files of 0..=9 bytes (zeros and 0xFF) fail with `UnexpectedEof { expected: 10 }` and never panic.
#[test]
fn matrix_sub_header_truncations() {
    // Zero length
    assert_eq!(
        transpile_sod(&[], "ZERO", None).unwrap_err(),
        SodError::UnexpectedEof {
            expected: 10,
            actual: 0
        }
    );

    // Every length from 1 to 9 bytes with all zeros and all 0xFF
    for len in 1..10 {
        let zeros = vec![0u8; len];
        let ones = vec![0xFFu8; len];

        let res_zeros = catch_unwind(AssertUnwindSafe(|| transpile_sod(&zeros, "ZEROS", None)));
        assert!(res_zeros.is_ok(), "Panic on zeros length {len}");
        assert_eq!(
            res_zeros.unwrap().unwrap_err(),
            SodError::UnexpectedEof {
                expected: 10,
                actual: len
            }
        );

        let res_ones = catch_unwind(AssertUnwindSafe(|| transpile_sod(&ones, "ONES", None)));
        assert!(res_ones.is_ok(), "Panic on ones length {len}");
        assert_eq!(
            res_ones.unwrap().unwrap_err(),
            SodError::UnexpectedEof {
                expected: 10,
                actual: len
            }
        );
    }
}

/// Wrong magic words fail with `InvalidMagic` and never panic.
#[test]
fn matrix_invalid_magic_words() {
    // 0x000C is valid magic. Test all other 16-bit values around it.
    for invalid_magic in [
        0x0000u16, 0x0001, 0x000B, 0x000D, 0x0010, 0x7FFF, 0x8000, 0xFFFF,
    ] {
        let mut buf = make_sod_header(100, 0, 0, 0);
        buf[0..2].copy_from_slice(&invalid_magic.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "BAD_MAGIC", None)));
        assert!(res.is_ok(), "Panic on invalid magic 0x{invalid_magic:04X}");
        assert_eq!(
            res.unwrap().unwrap_err(),
            SodError::InvalidMagic {
                expected: OP_ID,
                actual: invalid_magic
            }
        );
    }
}

/// Every known opcode followed by 0..6 operand bytes never panics.
#[test]
fn matrix_truncated_opcode_payloads_for_all_opcodes() {
    // List all known opcodes and their minimal expected payloads
    let opcodes = [
        OP_CLRV,
        OP_GETV,
        OP_ID,
        OP_PUTV,
        OP_INTV,
        OP_ADDV,
        OP_SUBV,
        OP_NEGV,
        OP_SHLV,
        OP_SHRV,
        OP_VEC,
        OP_IPG,
        OP_VECTORS,
        OP_PERS,
        OP_MOVETO,
        OP_LINECOL,
        OP_ZLINETO,
        OP_POLYZ,
        OP_SPHERE,
        OP_PERFDISK,
        OP_COLOR,
        OP_SHADES,
        OP_GVPOLY,
        OP_IFVIS,
        OP_SORT,
        OP_RETURN,
        OP_REJ,
        OP_GVPOLY16,
        OP_DOT,
        OP_BLOCK,
    ];

    for &op in &opcodes {
        // Construct header + opcode with 0 extra bytes, 1 extra byte, etc.
        for partial_len in 0..6 {
            let mut buf = make_sod_header(50, 0, 0, 0);
            buf.extend_from_slice(&op.to_le_bytes());
            if (op == OP_SHLV || op == OP_SHRV) && partial_len >= 2 {
                buf.extend_from_slice(&1u16.to_le_bytes());
                buf.extend_from_slice(&vec![0xAAu8; partial_len - 2]);
            } else {
                buf.extend_from_slice(&vec![0xAAu8; partial_len]);
            }

            let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "PARTIAL_OP", None)));
            assert!(
                res.is_ok(),
                "Panic on opcode 0x{op:04X} with partial payload len {partial_len}"
            );
        }
    }
}

// =============================================================================
// Register, IPG, vector and scale matrices
// =============================================================================

/// `OP_GETV/PUTV/ADDV/SUBV/INTV` with extreme and unaligned offsets still transpile cleanly.
#[test]
fn matrix_register_offsets_wrap_and_unaligned() {
    let offsets: [u16; 16] = [
        0,
        1,
        2,
        11,
        12,
        13,
        1023 * 12,
        1024 * 12,
        1025 * 12,
        20000,
        32767,
        32768,
        60000,
        65530,
        65534,
        65535,
    ];

    for &off in &offsets {
        let mut buf = make_sod_header(100, 0, 0, 0);
        // GETV with extreme offset
        buf.extend_from_slice(&OP_GETV.to_le_bytes());
        buf.extend_from_slice(&off.to_le_bytes());
        // PUTV with extreme offset
        buf.extend_from_slice(&OP_PUTV.to_le_bytes());
        buf.extend_from_slice(&off.to_le_bytes());
        // ADDV with extreme offset
        buf.extend_from_slice(&OP_ADDV.to_le_bytes());
        buf.extend_from_slice(&off.to_le_bytes());
        // SUBV with extreme offset
        buf.extend_from_slice(&OP_SUBV.to_le_bytes());
        buf.extend_from_slice(&off.to_le_bytes());
        // INTV with extreme offset
        buf.extend_from_slice(&OP_INTV.to_le_bytes());
        buf.extend_from_slice(&off.to_le_bytes());
        buf.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "REG_TEST", None)));
        assert!(res.is_ok(), "Panic on register offset {off}");
        assert!(res.unwrap().is_ok());
    }
}

/// `OP_IPG` types 0, 2 and 8 starting at registers 0 and 1020..=1023 transpile cleanly.
#[test]
fn matrix_ipg_start_registers_near_1023() {
    // Types 0 (cube), 2 (ground quad), 8 (vertical quad) with start offsets near register 1023
    for &start_reg in &[0u16, 1020, 1021, 1022, 1023] {
        let start_off = start_reg * 12;

        for &ipg_type in &[0u16, 2, 8] {
            let mut buf = make_sod_header(100, 0, 0, 0);
            buf.extend_from_slice(&OP_IPG.to_le_bytes());
            buf.extend_from_slice(&ipg_type.to_le_bytes());
            match ipg_type {
                0 => {
                    buf.extend_from_slice(&10i16.to_le_bytes());
                    buf.extend_from_slice(&20i16.to_le_bytes());
                    buf.extend_from_slice(&30i16.to_le_bytes());
                    buf.extend_from_slice(&start_off.to_le_bytes());
                }
                2 => {
                    buf.extend_from_slice(&15i16.to_le_bytes());
                    buf.extend_from_slice(&25i16.to_le_bytes());
                    buf.extend_from_slice(&start_off.to_le_bytes());
                }
                8 => {
                    buf.extend_from_slice(&5i16.to_le_bytes());
                    buf.extend_from_slice(&7i16.to_le_bytes());
                    buf.extend_from_slice(&start_off.to_le_bytes());
                }
                _ => unreachable!(),
            }
            buf.extend_from_slice(&OP_RETURN.to_le_bytes());

            let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "IPG_BOUND", None)));
            assert!(
                res.is_ok(),
                "Panic on IPG type {ipg_type} at start_reg {start_reg}"
            );
            assert!(res.unwrap().is_ok());
        }
    }
}

/// 50-vector `OP_VECTORS` runs starting at registers 0, 1000 and 1023 transpile cleanly.
#[test]
fn matrix_vectors_wrap_past_register_1023() {
    for &start_reg in &[0u16, 1000, 1023] {
        let start_off = start_reg * 12;
        let count = 50u16; // will wrap around register 1023 -> 0

        let mut buf = make_sod_header(100, 0, 0, 0);
        buf.extend_from_slice(&OP_VECTORS.to_le_bytes());
        buf.extend_from_slice(&count.to_le_bytes());
        buf.extend_from_slice(&start_off.to_le_bytes());
        for i in 0..count {
            buf.extend_from_slice(&(i as i16).to_le_bytes());
            buf.extend_from_slice(&(i as i16 * 2).to_le_bytes());
            buf.extend_from_slice(&(i as i16 * 3).to_le_bytes());
        }
        buf.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "VEC_WRAP", None)));
        assert!(res.is_ok(), "Panic on OP_VECTORS wrapping from {start_reg}");
        assert!(res.unwrap().is_ok());
    }
}

/// Every scale index has a non-NaN, non-negative scale factor and transpiles to a one-node model.
#[test]
fn matrix_scale_indices_0_to_255() {
    for idx in 0..=255usize {
        let factor = compute_scale_factor(idx);
        assert!(
            !factor.is_nan(),
            "Scale factor must not be NaN for idx {idx}"
        );
        assert!(
            factor >= 0.0,
            "Scale factor must be non-negative for idx {idx}"
        );

        let mut buf = make_sod_header(100, 0, idx as u8, 0);
        buf.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf, "SCALE_TEST", None)));
        assert!(res.is_ok(), "Panic on scale_index {idx}");
        let ir = res.unwrap().expect("valid IR");
        assert_eq!(ir.nodes.len(), 1); // root node
    }
}

/// `OP_POLYZ` and `OP_GVPOLY` with 0..=2 vertices fail with `MalformedPolygon`.
#[test]
fn matrix_polygon_counts_under_3() {
    for count in 0..3u16 {
        let mut buf = make_sod_header(50, 0, 0, 0);
        buf.extend_from_slice(&OP_POLYZ.to_le_bytes());
        buf.extend_from_slice(&count.to_le_bytes());
        for i in 0..count {
            buf.extend_from_slice(&(i * 12).to_le_bytes());
        }
        buf.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| {
            transpile_sod(&buf, "COUNT_UNDER_3", None)
        }));
        assert!(res.is_ok(), "Panic on OP_POLYZ count {count}");
        assert!(matches!(
            res.unwrap().unwrap_err(),
            SodError::MalformedPolygon { .. }
        ));

        // Repeat for GVPOLY
        let mut buf_gv = make_sod_header(50, 0, 0, 0);
        buf_gv.extend_from_slice(&OP_GVPOLY.to_le_bytes());
        buf_gv.extend_from_slice(&count.to_le_bytes());
        for i in 0..count {
            buf_gv.extend_from_slice(&(i * 12).to_le_bytes());
        }
        buf_gv.extend_from_slice(&0u16.to_le_bytes()); // norm offset
        for _ in 0..count {
            buf_gv.extend_from_slice(&0u16.to_le_bytes()); // shade
        }
        buf_gv.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res_gv = catch_unwind(AssertUnwindSafe(|| {
            transpile_sod(&buf_gv, "GV_COUNT_UNDER_3", None)
        }));
        assert!(res_gv.is_ok(), "Panic on OP_GVPOLY count {count}");
        assert!(matches!(
            res_gv.unwrap().unwrap_err(),
            SodError::MalformedPolygon { .. }
        ));
    }
}

/// A 500-triangle model transpiles to 1500 indices.
#[test]
fn fuzz_large_polygon_count() {
    let mut buf = make_sod_header(500, 0, 0, 0);

    // Create 500 triangles
    for i in 0..500u16 {
        buf.extend_from_slice(&OP_VECTORS.to_le_bytes());
        buf.extend_from_slice(&3u16.to_le_bytes());
        buf.extend_from_slice(&0u16.to_le_bytes()); // start offset 0
        buf.extend_from_slice(&(i as i16).to_le_bytes());
        buf.extend_from_slice(&0i16.to_le_bytes());
        buf.extend_from_slice(&0i16.to_le_bytes());
        buf.extend_from_slice(&(i as i16 + 1).to_le_bytes());
        buf.extend_from_slice(&10i16.to_le_bytes());
        buf.extend_from_slice(&0i16.to_le_bytes());
        buf.extend_from_slice(&(i as i16).to_le_bytes());
        buf.extend_from_slice(&10i16.to_le_bytes());
        buf.extend_from_slice(&0i16.to_le_bytes());

        buf.extend_from_slice(&OP_COLOR.to_le_bytes());
        buf.extend_from_slice(&(i % 256).to_le_bytes());

        buf.extend_from_slice(&OP_POLYZ.to_le_bytes());
        buf.extend_from_slice(&3u16.to_le_bytes());
        buf.extend_from_slice(&0u16.to_le_bytes());
        buf.extend_from_slice(&12u16.to_le_bytes());
        buf.extend_from_slice(&24u16.to_le_bytes());
    }
    buf.extend_from_slice(&OP_RETURN.to_le_bytes());

    let res = catch_unwind(AssertUnwindSafe(|| {
        transpile_sod(&buf, "LARGE_MODEL", None)
    }));
    assert!(res.is_ok(), "Panic on 500 polygons");
    let ir = res.unwrap().expect("transpile 500 polygons");
    assert_eq!(ir.name, "LARGE_MODEL");
    assert_eq!(ir.indices.len(), 500 * 3);
}

// =============================================================================
// Shift amounts (OP_SHLV / OP_SHRV)
// =============================================================================

/// `OP_SHLV` / `OP_SHRV` accept every shift amount, including >= 32, without panicking.
#[test]
fn matrix_shift_amounts_never_panic() {
    // Shifts 0..=31 are within the width of the 32-bit accumulator.
    for shift in 0..32u16 {
        let mut buf_shl = make_sod_header(50, 0, 0, 0);
        buf_shl.extend_from_slice(&OP_SHLV.to_le_bytes());
        buf_shl.extend_from_slice(&shift.to_le_bytes());
        buf_shl.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res_shl = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf_shl, "SHL_OK", None)));
        assert!(res_shl.is_ok(), "Panic on OP_SHLV with valid shift {shift}");

        let mut buf_shr = make_sod_header(50, 0, 0, 0);
        buf_shr.extend_from_slice(&OP_SHRV.to_le_bytes());
        buf_shr.extend_from_slice(&shift.to_le_bytes());
        buf_shr.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res_shr = catch_unwind(AssertUnwindSafe(|| transpile_sod(&buf_shr, "SHR_OK", None)));
        assert!(res_shr.is_ok(), "Panic on OP_SHRV with valid shift {shift}");
    }

    // Shifts >= 32 are masked to 5 bits by the VM (`wrapping_shl` / `wrapping_shr`), so they
    // cannot panic; a bare `<<` / `>>` on `i32` would. Pin that for amounts around and above 32.
    for overflow_shift in [32u16, 33, 64, 100, 65535] {
        let mut buf_shl = make_sod_header(50, 0, 0, 0);
        buf_shl.extend_from_slice(&OP_SHLV.to_le_bytes());
        buf_shl.extend_from_slice(&overflow_shift.to_le_bytes());
        buf_shl.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res_shl = catch_unwind(AssertUnwindSafe(|| {
            transpile_sod(&buf_shl, "SHL_PANIC", None)
        }));
        let shl_panicked = res_shl.is_err();

        let mut buf_shr = make_sod_header(50, 0, 0, 0);
        buf_shr.extend_from_slice(&OP_SHRV.to_le_bytes());
        buf_shr.extend_from_slice(&overflow_shift.to_le_bytes());
        buf_shr.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res_shr = catch_unwind(AssertUnwindSafe(|| {
            transpile_sod(&buf_shr, "SHR_PANIC", None)
        }));
        let shr_panicked = res_shr.is_err();

        // `transpile_sod` must never panic on untrusted input.
        assert!(
            !shl_panicked,
            "VULNERABILITY: OP_SHLV panicked on shift amount {overflow_shift} (attempt to shift left with overflow)"
        );
        assert!(
            !shr_panicked,
            "VULNERABILITY: OP_SHRV panicked on shift amount {overflow_shift} (attempt to shift right with overflow)"
        );
    }
}

// =============================================================================
// Randomized fuzzing (fixed seeds, 10,000 iterations each)
// =============================================================================

/// Random bytes (0..1024) behind a valid header never panic.
#[test]
fn fuzz_random_bytecode_with_valid_header() {
    let mut rng = XorShift64::new(0xDEAD_BEEF_CAFE_0001);

    for i in 0..10_000 {
        let mut buf = make_sod_header(100, 0, 0, 0);
        let payload_len = rng.next_range(0, 1024);
        let mut payload = vec![0u8; payload_len];
        rng.fill_bytes(&mut payload);
        buf.extend_from_slice(&payload);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let _ = transpile_sod(&buf, "FUZZ_PAYLOAD", None);
        }));

        assert!(
            res.is_ok(),
            "Panic detected on random bytecode with valid header at iteration {i}"
        );
    }
}

/// Random sequences of valid opcodes with random operand words never panic.
#[test]
fn fuzz_valid_opcode_sequences_with_random_operands() {
    let valid_opcodes = [
        OP_CLRV, OP_GETV, OP_PUTV, OP_INTV, OP_ADDV, OP_SUBV, OP_NEGV, OP_COLOR, OP_POLYZ, OP_IPG,
        OP_VECTORS, OP_RETURN,
    ];
    let mut rng = XorShift64::new(0xCAFE_BABE_0123_4567);

    for i in 0..10_000 {
        let mut buf = make_sod_header(100, 0, 0, 0);
        let op_count = rng.next_range(1, 20);
        for _ in 0..op_count {
            let op = valid_opcodes[rng.next_range(0, valid_opcodes.len())];
            buf.extend_from_slice(&op.to_le_bytes());
            // Append random parameter words
            let param_count = rng.next_range(1, 10);
            for _ in 0..param_count {
                buf.extend_from_slice(&(rng.next_u64() as u16).to_le_bytes());
            }
        }
        buf.extend_from_slice(&OP_RETURN.to_le_bytes());

        let res = catch_unwind(AssertUnwindSafe(|| {
            let _ = transpile_sod(&buf, "FUZZ_OPCODES", None);
        }));

        assert!(
            res.is_ok(),
            "Panic detected on valid opcode fuzz stream at iteration {i}"
        );
    }
}

/// Bit flips, overwrites, truncations and insertions of a valid model never panic.
#[test]
fn fuzz_mutated_valid_sod() {
    // Generate valid baseline .SOD fixture with header, vectors, color, polyz, return
    let mut baseline = make_sod_header(100, 0, 1, 0); // 10 bytes
    // OP_VECTORS (3 vectors)
    baseline.extend_from_slice(&OP_VECTORS.to_le_bytes());
    baseline.extend_from_slice(&3u16.to_le_bytes());
    baseline.extend_from_slice(&0u16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&10i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    baseline.extend_from_slice(&10i16.to_le_bytes());
    baseline.extend_from_slice(&0i16.to_le_bytes());
    // OP_COLOR
    baseline.extend_from_slice(&OP_COLOR.to_le_bytes());
    baseline.extend_from_slice(&40u16.to_le_bytes());
    // OP_POLYZ (count 3)
    baseline.extend_from_slice(&OP_POLYZ.to_le_bytes());
    baseline.extend_from_slice(&3u16.to_le_bytes());
    baseline.extend_from_slice(&0u16.to_le_bytes());
    baseline.extend_from_slice(&12u16.to_le_bytes());
    baseline.extend_from_slice(&24u16.to_le_bytes());
    // OP_RETURN
    baseline.extend_from_slice(&OP_RETURN.to_le_bytes());

    assert!(transpile_sod(&baseline, "BASELINE", None).is_ok());

    let mut rng = XorShift64::new(0xABCD_EF01_2345_6789);

    for i in 0..10_000 {
        let mut mutated = baseline.clone();
        let mutation_count = rng.next_range(1, 8);

        for _ in 0..mutation_count {
            let op = rng.next_range(0, 4);
            match op {
                0 => {
                    // Bit flip
                    if !mutated.is_empty() {
                        let idx = rng.next_range(0, mutated.len());
                        let bit = 1 << rng.next_range(0, 8);
                        mutated[idx] ^= bit;
                    }
                }
                1 => {
                    // Byte overwrite
                    if !mutated.is_empty() {
                        let idx = rng.next_range(0, mutated.len());
                        mutated[idx] = rng.next_u8();
                    }
                }
                2 => {
                    // Truncation
                    if !mutated.is_empty() {
                        let new_len = rng.next_range(0, mutated.len());
                        mutated.truncate(new_len);
                    }
                }
                3 => {
                    // Byte insertion
                    let idx = rng.next_range(0, mutated.len() + 1);
                    mutated.insert(idx, rng.next_u8());
                }
                _ => unreachable!(),
            }
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            let _ = transpile_sod(&mutated, "MUTATED", None);
        }));

        assert!(
            res.is_ok(),
            "Panic detected during mutated .SOD fuzzing at iteration {i}"
        );
    }
}

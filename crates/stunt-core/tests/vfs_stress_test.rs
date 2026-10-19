//! Adversarial Stress and Fuzz Test Suite for Ticket T05 VFS Containers.
//!
//! Stress-tests `.RES` and `.ALL` parsers against malformed headers, offset wrapping,
//! non-monotonic offsets, negative payload lengths, corrupt name tables, truncated
//! buffers, and 15,000+ randomized fuzz iterations.
//! Asserts that `parse_res`, `parse_all`, and `detect_and_parse` NEVER panic and
//! cleanly return structured `VfsError` variants.

use std::panic::{AssertUnwindSafe, catch_unwind};
use stunt_core::contracts::ArchiveFormat;
use stunt_core::vfs::{VfsError, detect_and_parse, parse_all, parse_res};

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

// ---------------------------------------------------------------------------
// 1. Boundary & Truncation Stress Tests
// ---------------------------------------------------------------------------

#[test]
fn test_adversarial_zero_and_sub_header_buffers() {
    // Zero-length buffer
    assert!(matches!(
        parse_res(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: 0
        })
    ));
    assert!(matches!(
        parse_all(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 0
        })
    ));
    assert!(matches!(
        detect_and_parse(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 0
        })
    ));

    // Every length from 1 to 16 with zeros and 0xFF
    for len in 1..=16 {
        let zeros = vec![0u8; len];
        let ones = vec![0xFFu8; len];

        catch_unwind(AssertUnwindSafe(|| {
            let _ = parse_res(&zeros);
            let _ = parse_res(&ones);
            let _ = parse_all(&zeros);
            let _ = parse_all(&ones);
            let _ = detect_and_parse(&zeros);
            let _ = detect_and_parse(&ones);
        }))
        .expect("Sub-header buffer parsing must never panic");
    }
}

#[test]
fn test_adversarial_res_magic_variations() {
    let bad_magics: &[&[u8]] = &[
        b"rs", // lowercase
        b"RS", // valid magic prefix, but truncated overall
        b"Rs", // mixed case
        b"rS", // mixed case
        b"R\0",
        b"\0S",
        b"\0\0",
        b"\xFF\xFF",
        b"FL",
        b"MZ",
        b"PK",
    ];

    for &magic in bad_magics {
        let mut buf = magic.to_vec();
        buf.extend_from_slice(&[0u8; 32]);

        let res = parse_res(&buf);
        if magic == b"RS" {
            // "RS" with 0 ofs[0] will fail on ofs[0] < 8
            assert!(matches!(res, Err(VfsError::InvalidOffsetTable { .. })));
        } else {
            match res {
                Err(VfsError::InvalidMagic { expected, actual }) => {
                    assert_eq!(expected, "RS");
                    assert_eq!(actual, [magic[0], magic[1]]);
                }
                other => panic!("Expected InvalidMagic for {magic:?}, got {other:?}"),
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 2. Offset Table Integrity & Wrapping Stress Tests
// ---------------------------------------------------------------------------

#[test]
fn test_adversarial_res_offset_bounds_and_alignment() {
    // Case A: ofs0 = 0..7 (< 8)
    for bad_ofs in 0..8u32 {
        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&bad_ofs.to_le_bytes());
        data.extend_from_slice(&[0u8; 32]);

        let res = parse_res(&data);
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "ofs0={bad_ofs} must be rejected as InvalidOffsetTable"
        );
    }

    // Case B: ofs0 unaligned to 4 bytes (e.g. 9, 10, 11, 13, 14, 15)
    for unaligned in [9u32, 10, 11, 13, 14, 15, 17, 18, 19] {
        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&unaligned.to_le_bytes());
        data.resize(64, 0);

        let res = parse_res(&data);
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "unaligned ofs0={unaligned} must be rejected as InvalidOffsetTable"
        );
    }

    // Case C: ofs0 = u32::MAX, u32::MAX - 1, etc.
    for huge_ofs in [u32::MAX, u32::MAX - 1, u32::MAX - 3, 0x8000_0000] {
        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&huge_ofs.to_le_bytes());
        data.resize(32, 0);

        let res = parse_res(&data);
        assert!(
            matches!(res, Err(VfsError::UnexpectedEof { .. })),
            "huge ofs0={huge_ofs} beyond data.len() must return UnexpectedEof"
        );
    }
}

#[test]
fn test_adversarial_res_non_monotonic_and_wrapping_offsets() {
    // Construct table with N = 4 offsets (ofs[0]=20, ofs[1]=30, ofs[2]=40, ofs[3]=50)
    // Then perturb each position to be non-monotonic or out of bounds.
    let base_offsets: [u32; 4] = [20, 30, 40, 50];

    // Non-monotonic pairs: offsets[i+1] < offsets[i]
    for i in 0..3 {
        let mut offsets = base_offsets;
        // Make index i+1 smaller than index i
        offsets[i + 1] = offsets[i] - 1;

        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        for &off in &offsets {
            data.extend_from_slice(&off.to_le_bytes());
        }
        data.resize(100, 0);

        let res = parse_res(&data);
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "Non-monotonic offset at index {} must return InvalidOffsetTable",
            i + 1
        );
    }

    // Out-of-bounds offset in table
    for i in 1..4 {
        let mut offsets = base_offsets;
        offsets[i] = 200; // beyond data.len() = 100

        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        for &off in &offsets {
            data.extend_from_slice(&off.to_le_bytes());
        }
        data.resize(100, 0);

        let res = parse_res(&data);
        assert!(
            matches!(res, Err(VfsError::UnexpectedEof { .. })),
            "Out of bounds offset {i} must return UnexpectedEof"
        );
    }
}

#[test]
fn test_adversarial_all_offset_bounds_and_wrapping() {
    // Case A: num = 2, header_size = 2 + 2*2 + 2*4 = 14
    // First offset < header_size
    for bad_first in [0u32, 1, 5, 13] {
        let mut data = Vec::new();
        data.extend_from_slice(&2u16.to_le_bytes()); // num = 2
        data.extend_from_slice(&1u16.to_le_bytes()); // id 1
        data.extend_from_slice(&2u16.to_le_bytes()); // id 2
        data.extend_from_slice(&bad_first.to_le_bytes()); // off 0 < 14
        data.extend_from_slice(&30u32.to_le_bytes()); // off 1
        data.resize(50, 0);

        let res = parse_all(&data);
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "first offset {bad_first} < header_size must return InvalidOffsetTable"
        );
    }

    // Case B: Non-monotonic offsets in .ALL (off[1] < off[0])
    let mut data = Vec::new();
    data.extend_from_slice(&2u16.to_le_bytes());
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&2u16.to_le_bytes());
    data.extend_from_slice(&20u32.to_le_bytes()); // off 0 = 20
    data.extend_from_slice(&19u32.to_le_bytes()); // off 1 = 19 < 20
    data.resize(50, 0);

    let res = parse_all(&data);
    assert!(matches!(res, Err(VfsError::InvalidOffsetTable { .. })));

    // Case C: Offset beyond buffer in .ALL
    let mut data = Vec::new();
    data.extend_from_slice(&1u16.to_le_bytes()); // num = 1, header_size = 8
    data.extend_from_slice(&1u16.to_le_bytes()); // id
    data.extend_from_slice(&100u32.to_le_bytes()); // off 0 = 100
    data.resize(20, 0); // buffer is only 20 bytes

    let res = parse_all(&data);
    assert!(matches!(
        res,
        Err(VfsError::UnexpectedEof {
            expected: 100,
            actual: 20
        })
    ));

    // Case D: Huge num = 0xFFFF in .ALL
    let mut data = Vec::new();
    data.extend_from_slice(&0xFFFFu16.to_le_bytes()); // num = 65535, header_size = 393212
    data.resize(100, 0);
    assert!(matches!(
        parse_all(&data),
        Err(VfsError::UnexpectedEof {
            expected: 393212,
            actual: 100
        })
    ));
}

// ---------------------------------------------------------------------------
// 3. Name Table Adversarial Stress Tests (.RES)
// ---------------------------------------------------------------------------

#[test]
fn test_adversarial_res_name_table_edge_cases() {
    // Helper to build a valid .RES skeleton with customized name table bytes
    let build_res_with_name_table = |names_raw: &[u8]| -> Vec<u8> {
        let ofs0: u32 = 20;
        let ofs1: u32 = 20 + names_raw.len() as u32;
        let ofs2: u32 = ofs1 + 8; // payload 0 (8 bytes)
        let ofs3: u32 = ofs2 + 8; // payload 1 (8 bytes)

        let mut data = Vec::new();
        data.extend_from_slice(b"RS");
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&ofs0.to_le_bytes());
        data.extend_from_slice(&ofs1.to_le_bytes());
        data.extend_from_slice(&ofs2.to_le_bytes());
        data.extend_from_slice(&ofs3.to_le_bytes());
        assert_eq!(data.len(), 20);

        data.extend_from_slice(names_raw);
        data.extend_from_slice(&[0x11u8; 8]); // payload 0
        data.extend_from_slice(&[0x22u8; 8]); // payload 1
        data
    };

    // Case 1: Non-ASCII characters (0x80..=0xFF) -> name table discarded, fallback to 0000.BIN / 0001.BIN
    let corrupted_names = b"PLANE.SOD\0\x80\xFF\xFE\0";
    let data = build_res_with_name_table(corrupted_names);
    let archive = parse_res(&data).expect("corrupt names should cleanly fallback, not error");
    assert_eq!(archive.entries.len(), 2);
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Case 2: Control characters (\t, \n, \r) -> fallback to default names
    let ctrl_names = b"PLANE.SOD\0BAD\tNAME.SOD\0";
    let data = build_res_with_name_table(ctrl_names);
    let archive = parse_res(&data).expect("ctrl char in names should fallback");
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Case 3: Empty / whitespace names -> trimmed to empty -> fallback to default names
    let whitespace_names = b"   \0  \t  \0";
    let data = build_res_with_name_table(whitespace_names);
    let archive = parse_res(&data).expect("whitespace names fallback");
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Case 4: Names with leading/trailing spaces -> trimmed and normalized
    let padded_names = b"  plane.sod  \0  prop.sod \0";
    let data = build_res_with_name_table(padded_names);
    let archive = parse_res(&data).expect("padded names should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());
    assert!(archive.get("plane.sod").is_some());

    // Case 5: Unterminated name (no trailing null)
    let unterminated_names = b"plane.sod\0prop.sod";
    let data = build_res_with_name_table(unterminated_names);
    let archive = parse_res(&data).expect("unterminated name should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());

    // Case 6: Fewer names than payloads (only 1 name for 2 payloads)
    let short_names = b"single.sod\0";
    let data = build_res_with_name_table(short_names);
    let archive = parse_res(&data).expect("short name table should parse");
    assert_eq!(archive.entries.len(), 2);
    assert!(archive.get("SINGLE.SOD").is_some());
    assert!(archive.get("0001.BIN").is_some()); // payload 1 defaults to 0001.BIN

    // Case 7: Consecutive nulls (empty entries)
    let null_padded = b"\0\0PLANE.SOD\0\0\0PROP.SOD\0\0";
    let data = build_res_with_name_table(null_padded);
    let archive = parse_res(&data).expect("null padded name table should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());
}

// ---------------------------------------------------------------------------
// 4. Zero-Length Payloads & Duplicate Entry Names
// ---------------------------------------------------------------------------

#[test]
fn test_adversarial_zero_length_payloads() {
    // .RES container where start == end for all payloads
    let ofs0: u32 = 20;
    let ofs1: u32 = 20;
    let ofs2: u32 = 20;
    let ofs3: u32 = 20;

    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());
    data.extend_from_slice(&ofs3.to_le_bytes());

    let archive = parse_res(&data).expect("zero-length payloads in .RES should succeed");
    assert_eq!(archive.format, ArchiveFormat::Res);
    // payload_count = 4 - 2 = 2 entries: 0000.BIN and 0001.BIN with len 0
    assert_eq!(archive.entries.len(), 2);
    assert_eq!(archive.get_bytes("0000.BIN"), Some([].as_slice()));
    assert_eq!(archive.get_bytes("0001.BIN"), Some([].as_slice()));

    // .ALL container where offsets[0] == offsets[1] == data.len()
    let mut all_data = Vec::new();
    all_data.extend_from_slice(&2u16.to_le_bytes()); // num = 2
    all_data.extend_from_slice(&1u16.to_le_bytes()); // id 1
    all_data.extend_from_slice(&2u16.to_le_bytes()); // id 2
    all_data.extend_from_slice(&14u32.to_le_bytes()); // off 0 = 14
    all_data.extend_from_slice(&14u32.to_le_bytes()); // off 1 = 14

    let all_archive = parse_all(&all_data).expect("zero-length payloads in .ALL should succeed");
    assert_eq!(all_archive.format, ArchiveFormat::All);
    assert_eq!(all_archive.entries.len(), 2);
    assert_eq!(all_archive.get_bytes("RES_0001.BIN"), Some([].as_slice()));
    assert_eq!(all_archive.get_bytes("RES_0002.BIN"), Some([].as_slice()));
}

#[test]
fn test_adversarial_all_payload_classification_edge_cases() {
    // num = 5
    // Payload 0: Exactly 4 bytes "FILM" -> CHOREO.FLM
    // Payload 1: 3 bytes "FIL" -> RES_0002.BIN (too short for FILM)
    // Payload 2: Exactly 2 bytes [0x0C, 0x00] -> MODEL_0003.SOD
    // Payload 3: Exactly 1 byte [0x0C] -> RES_0004.BIN (too short for 0x000C)
    // Payload 4: 0 bytes -> RES_0005.BIN
    let num: u16 = 5;
    let header_size = 2 + 5 * 2 + 5 * 4; // 2 + 10 + 20 = 32 bytes

    let off0 = header_size as u32; // 32
    let off1 = off0 + 4; // 36 (len 4)
    let off2 = off1 + 3; // 39 (len 3)
    let off3 = off2 + 2; // 41 (len 2)
    let off4 = off3 + 1; // 42 (len 1)
    // payload 4: 42..42 (len 0)

    let mut data = Vec::new();
    data.extend_from_slice(&num.to_le_bytes());
    // IDs: 1, 2, 3, 4, 5
    for id in 1..=5u16 {
        data.extend_from_slice(&id.to_le_bytes());
    }
    // Offsets
    for &off in &[off0, off1, off2, off3, off4] {
        data.extend_from_slice(&off.to_le_bytes());
    }
    assert_eq!(data.len(), 32);

    data.extend_from_slice(b"FILM"); // P0
    data.extend_from_slice(b"FIL"); // P1
    data.extend_from_slice(&0x000Cu16.to_le_bytes()); // P2
    data.extend_from_slice(&[0x0C]); // P3
    assert_eq!(data.len(), 42);

    let archive = parse_all(&data).expect("classification edge cases must parse");
    assert_eq!(archive.entries.len(), 5);

    assert_eq!(archive.get("CHOREO.FLM").unwrap().data, b"FILM");
    assert_eq!(archive.get("RES_0002.BIN").unwrap().data, b"FIL");
    assert_eq!(
        archive.get("MODEL_0003.SOD").unwrap().data,
        &0x000Cu16.to_le_bytes()
    );
    assert_eq!(archive.get("RES_0004.BIN").unwrap().data, &[0x0C]);
    assert_eq!(archive.get("RES_0005.BIN").unwrap().data, &[]);
}

#[test]
fn test_adversarial_res_n_equals_two_boundary() {
    // ofs0 = 12: N = (12/4) - 1 = 2 offsets (ofs0, ofs1).
    // payload_count = N - 2 = 0.
    // ofs0 = 12, ofs1 = 12
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&12u32.to_le_bytes()); // ofs0
    data.extend_from_slice(&12u32.to_le_bytes()); // ofs1
    assert_eq!(data.len(), 12);

    let archive = parse_res(&data).expect("N=2 boundary in .RES must produce empty archive");
    assert_eq!(archive.entries.len(), 0);

    // What if ofs1 is 20, with 8 bytes between 12 and 20?
    let mut data2 = Vec::new();
    data2.extend_from_slice(b"RS");
    data2.extend_from_slice(&1u16.to_le_bytes());
    data2.extend_from_slice(&12u32.to_le_bytes());
    data2.extend_from_slice(&20u32.to_le_bytes());
    data2.extend_from_slice(b"FOOBARBA"); // name slice, but 0 payloads
    let archive2 = parse_res(&data2).expect("N=2 with name slice must produce empty archive");
    assert_eq!(archive2.entries.len(), 0);
}

// ---------------------------------------------------------------------------
// 5. Randomized Fuzzing Harness (20,000+ Iterations)
// ---------------------------------------------------------------------------

#[test]
fn test_fuzz_pure_random_bytes_never_panic() {
    let mut rng = XorShift64::new(0x1337_C0DE_FACE_BEEF);

    for i in 0..10_000 {
        let len = rng.next_range(0, 4096);
        let mut buf = vec![0u8; len];
        rng.fill_bytes(&mut buf);

        let res = catch_unwind(AssertUnwindSafe(|| {
            let _ = parse_res(&buf);
            let _ = parse_all(&buf);
            let _ = detect_and_parse(&buf);
        }));

        assert!(
            res.is_ok(),
            "Panic detected on pure random fuzz buffer at iteration {i} (len {len})"
        );
    }
}

#[test]
fn test_fuzz_mutated_valid_res_never_panic() {
    // Generate valid baseline .RES fixture
    let mut baseline = Vec::new();
    baseline.extend_from_slice(b"RS");
    baseline.extend_from_slice(&1u16.to_le_bytes());
    let ofs0: u32 = 24;
    let ofs1: u32 = 44;
    let ofs2: u32 = 54;
    let ofs3: u32 = 64;
    let ofs4: u32 = 74;
    baseline.extend_from_slice(&ofs0.to_le_bytes());
    baseline.extend_from_slice(&ofs1.to_le_bytes());
    baseline.extend_from_slice(&ofs2.to_le_bytes());
    baseline.extend_from_slice(&ofs3.to_le_bytes());
    baseline.extend_from_slice(&ofs4.to_le_bytes());
    baseline.extend_from_slice(b"FOO.SOD\0BAR.SOD\0BAZ.BIN\0");
    baseline.extend_from_slice(&[0x11; 10]);
    baseline.extend_from_slice(&[0x22; 10]);
    baseline.extend_from_slice(&[0x33; 10]);

    assert!(parse_res(&baseline).is_ok());

    let mut rng = XorShift64::new(0xABCD_EF01_2345_6789);

    for i in 0..10_000 {
        let mut mutated = baseline.clone();
        let mutation_count = rng.next_range(1, 10);

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
            if let Ok(archive) = parse_res(&mutated) {
                // Exercise archive lookups
                let _ = archive.get("FOO.SOD");
                let _ = archive.get("nonexistent");
                let _ = archive.get_bytes("FOO.SOD");
            }
            if let Ok(archive) = detect_and_parse(&mutated) {
                let _ = archive.get("FOO.SOD");
            }
        }));

        assert!(
            res.is_ok(),
            "Panic detected during mutated .RES fuzzing at iteration {i}"
        );
    }
}

#[test]
fn test_fuzz_mutated_valid_all_never_panic() {
    // Generate valid baseline .ALL fixture
    let mut baseline = Vec::new();
    let num: u16 = 3;
    baseline.extend_from_slice(&num.to_le_bytes());
    baseline.extend_from_slice(&1u16.to_le_bytes()); // id 1
    baseline.extend_from_slice(&2u16.to_le_bytes()); // id 2
    baseline.extend_from_slice(&3u16.to_le_bytes()); // id 3
    let off0: u32 = 20;
    let off1: u32 = 32;
    let off2: u32 = 44;
    baseline.extend_from_slice(&off0.to_le_bytes());
    baseline.extend_from_slice(&off1.to_le_bytes());
    baseline.extend_from_slice(&off2.to_le_bytes());

    let mut p0 = vec![0u8; 12];
    p0[0..4].copy_from_slice(b"FILM");
    baseline.extend_from_slice(&p0);

    let mut p1 = vec![0u8; 12];
    p1[0..2].copy_from_slice(&0x000Cu16.to_le_bytes());
    baseline.extend_from_slice(&p1);

    let p2 = vec![0x77u8; 12];
    baseline.extend_from_slice(&p2);

    assert!(parse_all(&baseline).is_ok());

    let mut rng = XorShift64::new(0x9876_5432_10FE_DCBA);

    for i in 0..10_000 {
        let mut mutated = baseline.clone();
        let mutation_count = rng.next_range(1, 10);

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
                    // Insertion
                    let idx = rng.next_range(0, mutated.len() + 1);
                    mutated.insert(idx, rng.next_u8());
                }
                _ => unreachable!(),
            }
        }

        let res = catch_unwind(AssertUnwindSafe(|| {
            if let Ok(archive) = parse_all(&mutated) {
                let _ = archive.get("CHOREO.FLM");
                let _ = archive.get("MODEL_0002.SOD");
                let _ = archive.get("nonexistent");
            }
            if let Ok(archive) = detect_and_parse(&mutated) {
                let _ = archive.get("CHOREO.FLM");
            }
        }));

        assert!(
            res.is_ok(),
            "Panic detected during mutated .ALL fuzzing at iteration {i}"
        );
    }
}

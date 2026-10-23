//! Panic-freedom fuzz and matrix tests for the VFS archive parsers (Seam 1).
//!
//! Every test here passes when `parse_res`, `parse_all` and `detect_and_parse` never panic on
//! the generated input. The result of the parse (success or a structured `VfsError`) is not
//! inspected beyond exercising the returned archive's lookups. Inputs come from fixed-seed
//! deterministic PRNGs so a failure reproduces exactly:
//!
//! - `matrix_sub_header_buffers_never_panic`: every length 1..=16 of all-zero / all-0xFF bytes.
//! - `fuzz_pure_random_bytes_never_panic`: 10,000 random buffers of up to 4 KiB.
//! - `fuzz_mutated_valid_res_never_panic`: 10,000 bit-flip / overwrite / truncate / insert
//!   mutations of a valid `.RES` container.
//! - `fuzz_mutated_valid_all_never_panic`: the same mutation fuzz over a valid `.ALL` container.
//!
//! Tests with specific expected results (exact errors, exact payloads) live in `vfs_spec.rs`.

mod common;

use std::panic::{AssertUnwindSafe, catch_unwind};

use common::rng::{XorShift64, mutate};
use stunt_core::vfs::{detect_and_parse, parse_all, parse_res};

#[test]
fn matrix_sub_header_buffers_never_panic() {
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
fn fuzz_pure_random_bytes_never_panic() {
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
fn fuzz_mutated_valid_res_never_panic() {
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
        mutate(&mut rng, &mut mutated, 10);

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
fn fuzz_mutated_valid_all_never_panic() {
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
        mutate(&mut rng, &mut mutated, 10);

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

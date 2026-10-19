//! Empirical Challenger Test Suite for Seam 1: VFS Archive Parsers (Ticket T05)
//!
//! Verifies:
//! - 100% bit-exact payload roundtrip extraction across multi-entry `.RES` and `.ALL` containers.
//! - Strict conformance to Invariant `[I8]` uppercase DOS 8.3 normalization and case-insensitive lookups.
//! - Extreme payload variation: 0 bytes, 1 byte, prime lengths, up to 64 KB per entry.
//! - Large container stress (50+ entries).
//! - Edge cases: zero-length payloads, whitespace trimming, omitted/fallback name tables, trailing container padding.

use stunt_core::contracts::ArchiveFormat;
use stunt_core::vfs::{detect_and_parse, parse_all, parse_res};

/// Simple deterministic Pseudo-Random Number Generator (Xorshift32).
struct SimpleRng {
    state: u32,
}

impl SimpleRng {
    fn new(seed: u32) -> Self {
        Self {
            state: if seed == 0 { 0xCAFE_BABE } else { seed },
        }
    }

    fn next_u32(&mut self) -> u32 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.state = x;
        x
    }

    fn next_bytes(&mut self, len: usize) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(len);
        for _ in 0..len {
            bytes.push((self.next_u32() & 0xFF) as u8);
        }
        bytes
    }
}

/// Permutes casing of an ASCII string according to bitmask.
fn permute_casing(s: &str, mask: u64) -> String {
    s.chars()
        .enumerate()
        .map(|(idx, ch)| {
            if ch.is_ascii_alphabetic() {
                if ((mask >> (idx % 64)) & 1) == 1 {
                    ch.to_ascii_uppercase()
                } else {
                    ch.to_ascii_lowercase()
                }
            } else {
                ch
            }
        })
        .collect()
}

#[test]
fn test_challenge_res_multi_entry_roundtrip_16_entries() {
    let mut rng = SimpleRng::new(0x1992_1018);

    // 16 entries with widely varying sizes
    let names = [
        "PLANE.SOD",
        "PROP.SOD",
        "BUILDING.SOD",
        "RUNWAY.SOD",
        "HANGAR.SOD",
        "TOWER.SOD",
        "CAMERA.DAT",
        "PILOT.SOD",
        "CLOUD.SOD",
        "TERRAIN.DAT",
        "PALETTE.COL",
        "FONT.FNT",
        "SOUND01.VOC",
        "SOUND02.VOC",
        "SCENE.FLM",
        "CONFIG.CFG",
    ];

    let sizes = [
        0, 1, 7, 16, 64, 128, 255, 512, 1024, 2048, 4096, 8192, 12345, 16384, 32768, 65536,
    ];

    let num_entries = names.len();
    assert_eq!(num_entries, 16);
    assert_eq!(sizes.len(), 16);

    let payloads: Vec<Vec<u8>> = sizes.iter().map(|&sz| rng.next_bytes(sz)).collect();

    // Construct Name Table (null-separated strings)
    let mut name_table_bytes = Vec::new();
    for name in &names {
        name_table_bytes.extend_from_slice(name.as_bytes());
        name_table_bytes.push(0); // null terminator
    }

    // Number of offsets: N = num_entries + 2
    // ofs[0]: name table start
    // ofs[1]: name table end / payload 0 start
    // ofs[2..N-1]: payload boundaries
    let n = num_entries + 2;
    let ofs0 = (4 * (n + 1)) as u32; // 4 + n*4 = 4*(n+1)

    let mut offsets = Vec::with_capacity(n);
    offsets.push(ofs0);

    let mut current_offset = ofs0 + name_table_bytes.len() as u32;
    offsets.push(current_offset);

    for p in &payloads {
        current_offset += p.len() as u32;
        offsets.push(current_offset);
    }
    assert_eq!(offsets.len(), n);

    // Assemble .RES container
    let mut container = Vec::new();
    container.extend_from_slice(b"RS");
    container.extend_from_slice(&1u16.to_le_bytes()); // version 1
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    container.extend_from_slice(&name_table_bytes);
    for p in &payloads {
        container.extend_from_slice(p);
    }

    // Extraction assertion 1: parse_res
    let archive_res = parse_res(&container).expect("parse_res must succeed on 16-entry container");
    assert_eq!(archive_res.format, ArchiveFormat::Res);
    assert_eq!(archive_res.entries.len(), 16);

    // Extraction assertion 2: detect_and_parse
    let archive_detected =
        detect_and_parse(&container).expect("detect_and_parse must succeed on .RES container");
    assert_eq!(archive_detected.format, ArchiveFormat::Res);
    assert_eq!(archive_detected.entries.len(), 16);

    // Verify 100% bit-exact payload match and metadata across all 16 entries
    for (i, name) in names.iter().enumerate() {
        let expected_payload = &payloads[i];
        let expected_offset = offsets[i + 1];

        let entry = archive_res
            .get(name)
            .unwrap_or_else(|| panic!("Entry {name} must be present in archive"));

        assert_eq!(entry.name, *name);
        assert_eq!(entry.source_offset, expected_offset);
        assert_eq!(entry.data.len(), expected_payload.len());
        assert_eq!(
            &entry.data, expected_payload,
            "100% bit-exact payload match for {name}"
        );
        assert!(!entry.was_compressed);

        // Also assert bytes slice getter
        assert_eq!(
            archive_res.get_bytes(name),
            Some(expected_payload.as_slice()),
            "get_bytes must match expected payload for {name}"
        );
    }
}

#[test]
fn test_challenge_res_case_insensitivity_oracle() {
    let mut rng = SimpleRng::new(0x2026_0417);

    let names = [
        "Fokker.Sod",
        "plane.SOD",
        "prOP.soD",
        "Building.Sod",
        "RuNwAy.SoD",
        "hangar.sod",
        "TOWER.SOD",
        "Camera.Dat",
        "PILOT.sod",
        "cloud.SOD",
    ];

    let payloads: Vec<Vec<u8>> = (0..names.len())
        .map(|i| rng.next_bytes(32 + i * 16))
        .collect();

    let mut name_table_bytes = Vec::new();
    for name in &names {
        name_table_bytes.extend_from_slice(name.as_bytes());
        name_table_bytes.push(0);
    }

    let n = names.len() + 2;
    let ofs0 = (4 * (n + 1)) as u32;

    let mut offsets = Vec::with_capacity(n);
    offsets.push(ofs0);
    let mut current_offset = ofs0 + name_table_bytes.len() as u32;
    offsets.push(current_offset);
    for p in &payloads {
        current_offset += p.len() as u32;
        offsets.push(current_offset);
    }

    let mut container = Vec::new();
    container.extend_from_slice(b"RS");
    container.extend_from_slice(&1u16.to_le_bytes());
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    container.extend_from_slice(&name_table_bytes);
    for p in &payloads {
        container.extend_from_slice(p);
    }

    let archive = parse_res(&container).expect("parse_res");

    // Invariant [I8] Case-Insensitivity Oracle:
    // Generate 30 randomized case permutations per entry name
    for (i, name) in names.iter().enumerate() {
        let expected_payload = &payloads[i];

        for seed in 0..30u64 {
            let permuted = permute_casing(name, seed.wrapping_mul(0x9E37_79B9_7F4A_7C15));
            let entry = archive.get(&permuted).unwrap_or_else(|| {
                panic!("Lookup failed for permuted casing '{permuted}' of original '{name}'");
            });

            assert_eq!(
                &entry.data, expected_payload,
                "Payload mismatch under permuted casing '{permuted}'"
            );
            assert_eq!(
                archive.get_bytes(&permuted),
                Some(expected_payload.as_slice())
            );
        }
    }

    // Negative oracle: non-existent filenames
    let negative_queries = [
        "FOKKER.SO",
        "FOKKER.SODD",
        "NONEXISTENT.RES",
        "PLANE.BIN",
        "RUNWAY",
        "CAMERA.DA",
    ];
    for neg in &negative_queries {
        assert!(
            archive.get(neg).is_none(),
            "Query for '{neg}' should return None"
        );
        assert!(
            archive.get_bytes(neg).is_none(),
            "Query get_bytes for '{neg}' should return None"
        );
    }
}

#[test]
fn test_challenge_all_multi_entry_roundtrip_12_entries() {
    let mut rng = SimpleRng::new(0x1992_0515);

    // 12 items spanning FILM, SOD, and BIN with diverse IDs and sizes
    struct Spec {
        id: u16,
        prefix: &'static [u8],
        size: usize,
        expected_name: &'static str,
    }

    let specs = [
        Spec {
            id: 0x0001,
            prefix: b"FILM",
            size: 512,
            expected_name: "CHOREO.FLM",
        },
        Spec {
            id: 0x0010,
            prefix: &[0x0C, 0x00],
            size: 16,
            expected_name: "MODEL_0010.SOD",
        },
        Spec {
            id: 0x0020,
            prefix: &[0x0C, 0x00],
            size: 128,
            expected_name: "MODEL_0020.SOD",
        },
        Spec {
            id: 0x0030,
            prefix: &[0x0C, 0x00],
            size: 1024,
            expected_name: "MODEL_0030.SOD",
        },
        Spec {
            id: 0x0040,
            prefix: &[0x0C, 0x00],
            size: 4096,
            expected_name: "MODEL_0040.SOD",
        },
        Spec {
            id: 0x0050,
            prefix: &[0x0C, 0x00],
            size: 8192,
            expected_name: "MODEL_0050.SOD",
        },
        Spec {
            id: 0x00A0,
            prefix: b"",
            size: 0, // 0-byte payload test!
            expected_name: "RES_00A0.BIN",
        },
        Spec {
            id: 0x00B0,
            prefix: &[0xFF],
            size: 1, // 1-byte payload test!
            expected_name: "RES_00B0.BIN",
        },
        Spec {
            id: 0x00C0,
            prefix: &[0xAA, 0xBB],
            size: 33,
            expected_name: "RES_00C0.BIN",
        },
        Spec {
            id: 0x00D0,
            prefix: &[0x12, 0x34],
            size: 2048,
            expected_name: "RES_00D0.BIN",
        },
        Spec {
            id: 0x00E0,
            prefix: &[0x56, 0x78],
            size: 16384,
            expected_name: "RES_00E0.BIN",
        },
        Spec {
            id: 0x00F0,
            prefix: &[0x9A, 0xBC],
            size: 65536,
            expected_name: "RES_00F0.BIN",
        },
    ];

    let num = specs.len();
    assert_eq!(num, 12);

    let mut payloads = Vec::with_capacity(num);
    for spec in &specs {
        let mut p = rng.next_bytes(spec.size);
        if !spec.prefix.is_empty() && p.len() >= spec.prefix.len() {
            p[0..spec.prefix.len()].copy_from_slice(spec.prefix);
        }
        payloads.push(p);
    }

    let header_size = 2 + num * 6; // 2 + 12*2 + 12*4 = 74 bytes

    let mut offsets = Vec::with_capacity(num);
    let mut current_offset = header_size as u32;
    for p in &payloads {
        offsets.push(current_offset);
        current_offset += p.len() as u32;
    }

    // Assemble .ALL container
    let mut container = Vec::new();
    container.extend_from_slice(&(num as u16).to_le_bytes());
    for spec in &specs {
        container.extend_from_slice(&spec.id.to_le_bytes());
    }
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    for p in &payloads {
        container.extend_from_slice(p);
    }

    // Extraction via parse_all and detect_and_parse
    let archive_all = parse_all(&container).expect("parse_all must succeed on 12-entry container");
    assert_eq!(archive_all.format, ArchiveFormat::All);
    assert_eq!(archive_all.entries.len(), 12);

    let archive_detected =
        detect_and_parse(&container).expect("detect_and_parse must succeed on .ALL container");
    assert_eq!(archive_detected.format, ArchiveFormat::All);
    assert_eq!(archive_detected.entries.len(), 12);

    // Verify 100% bit-exact payload match across all 12 entries
    for (i, spec) in specs.iter().enumerate() {
        let expected_payload = &payloads[i];
        let expected_offset = offsets[i];
        let name = spec.expected_name;

        let entry = archive_all
            .get(name)
            .unwrap_or_else(|| panic!("Entry {name} must exist in .ALL archive"));

        assert_eq!(entry.name, name);
        assert_eq!(entry.source_offset, expected_offset);
        assert_eq!(entry.data.len(), expected_payload.len());
        assert_eq!(
            &entry.data, expected_payload,
            "100% bit-exact payload match for {name}"
        );
        assert!(!entry.was_compressed);

        assert_eq!(
            archive_all.get_bytes(name),
            Some(expected_payload.as_slice())
        );
    }
}

#[test]
fn test_challenge_all_case_insensitivity_oracle() {
    let mut rng = SimpleRng::new(0x1992_0820);

    let ids = [0x0001u16, 0x0022u16, 0x0033u16, 0x0044u16];
    let mut p0 = rng.next_bytes(64);
    p0[0..4].copy_from_slice(b"FILM");
    let mut p1 = rng.next_bytes(64);
    p1[0..2].copy_from_slice(&0x000Cu16.to_le_bytes());
    let mut p2 = rng.next_bytes(64);
    p2[0..2].copy_from_slice(&0x000Cu16.to_le_bytes());
    let p3 = rng.next_bytes(64);

    let payloads = [p0, p1, p2, p3];
    let expected_names = [
        "CHOREO.FLM",
        "MODEL_0022.SOD",
        "MODEL_0033.SOD",
        "RES_0044.BIN",
    ];

    let header_size = 2 + 4 * 6; // 26 bytes
    let mut offsets = Vec::new();
    let mut cur = header_size as u32;
    for p in &payloads {
        offsets.push(cur);
        cur += p.len() as u32;
    }

    let mut container = Vec::new();
    container.extend_from_slice(&4u16.to_le_bytes());
    for &id in &ids {
        container.extend_from_slice(&id.to_le_bytes());
    }
    for &off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    for p in &payloads {
        container.extend_from_slice(p);
    }

    let archive = parse_all(&container).expect("parse_all");

    // Case-insensitivity oracle: test 30 random casing permutations per name
    for (i, name) in expected_names.iter().enumerate() {
        let expected_payload = &payloads[i];

        for seed in 0..30u64 {
            let permuted = permute_casing(name, seed.wrapping_mul(0x517C_C1B7_2722_0A95));
            let entry = archive.get(&permuted).unwrap_or_else(|| {
                panic!("Lookup failed for permuted casing '{permuted}' of original '{name}'");
            });

            assert_eq!(
                &entry.data, expected_payload,
                "Payload mismatch under permuted casing '{permuted}'"
            );
            assert_eq!(
                archive.get_bytes(&permuted),
                Some(expected_payload.as_slice())
            );
        }
    }
}

#[test]
fn test_challenge_res_large_container_stress_50_entries() {
    let mut rng = SimpleRng::new(0x50_50_50_50);

    let count = 50;
    let mut names = Vec::with_capacity(count);
    let mut payloads = Vec::with_capacity(count);

    for i in 0..count {
        names.push(format!("ASSET_{i:03}.DAT"));
        let sz = (i * 137 + 11) % 5000;
        payloads.push(rng.next_bytes(sz));
    }

    let mut name_table_bytes = Vec::new();
    for name in &names {
        name_table_bytes.extend_from_slice(name.as_bytes());
        name_table_bytes.push(0);
    }

    let n = count + 2;
    let ofs0 = (4 * (n + 1)) as u32;

    let mut offsets = Vec::with_capacity(n);
    offsets.push(ofs0);
    let mut cur = ofs0 + name_table_bytes.len() as u32;
    offsets.push(cur);
    for p in &payloads {
        cur += p.len() as u32;
        offsets.push(cur);
    }

    let mut container = Vec::new();
    container.extend_from_slice(b"RS");
    container.extend_from_slice(&1u16.to_le_bytes());
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    container.extend_from_slice(&name_table_bytes);
    for p in &payloads {
        container.extend_from_slice(p);
    }

    let archive = parse_res(&container).expect("parse_res 50 entries");
    assert_eq!(archive.entries.len(), count);

    for (i, name) in names.iter().enumerate() {
        let entry = archive.get(name).expect("entry must exist");
        assert_eq!(&entry.data, &payloads[i]);
        assert_eq!(entry.source_offset, offsets[i + 1]);
    }
}

#[test]
fn test_challenge_res_name_table_edge_cases() {
    // 1. Whitespace in names: names with leading/trailing spaces must be trimmed
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());

    // N = 3 offsets (ofs[0], ofs[1], ofs[2]) -> ofs[0] = 16
    let ofs0: u32 = 16;
    let ofs1: u32 = 16 + 16; // name table: "  TRIMMED.SOD  \0" (16 bytes)
    let ofs2: u32 = ofs1 + 8; // payload: 8 bytes
    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());

    data.extend_from_slice(b"  TRIMMED.SOD  \0");
    let payload = [0x42u8; 8];
    data.extend_from_slice(&payload);

    let archive = parse_res(&data).expect("parse res with spaces");
    assert_eq!(archive.entries.len(), 1);

    // Should be trimmed and uppercase
    assert!(archive.get("TRIMMED.SOD").is_some());
    assert!(archive.get("trimmed.sod").is_some());
    assert_eq!(archive.get_bytes("trimmed.sod"), Some(payload.as_slice()));

    // 2. Fewer names in name table than payloads: remainder must fall back to {:04X}.BIN
    let mut data2 = Vec::new();
    data2.extend_from_slice(b"RS");
    data2.extend_from_slice(&1u16.to_le_bytes());

    // N = 4 offsets (ofs[0..3]) -> 2 payloads.
    // Name table only contains 1 name "FIRST.SOD\0" (10 bytes).
    let ofs0: u32 = 20;
    let ofs1: u32 = 30; // name table end
    let ofs2: u32 = 34; // payload 0 (4 bytes)
    let ofs3: u32 = 38; // payload 1 (4 bytes) -> should default to "0001.BIN"
    data2.extend_from_slice(&ofs0.to_le_bytes());
    data2.extend_from_slice(&ofs1.to_le_bytes());
    data2.extend_from_slice(&ofs2.to_le_bytes());
    data2.extend_from_slice(&ofs3.to_le_bytes());

    data2.extend_from_slice(b"FIRST.SOD\0");
    data2.extend_from_slice(&[1, 2, 3, 4]);
    data2.extend_from_slice(&[5, 6, 7, 8]);

    let archive2 = parse_res(&data2).expect("parse res with fewer names");
    assert_eq!(archive2.entries.len(), 2);
    assert_eq!(
        archive2.get_bytes("first.sod"),
        Some([1, 2, 3, 4].as_slice())
    );
    assert_eq!(
        archive2.get_bytes("0001.bin"),
        Some([5, 6, 7, 8].as_slice())
    );
}

#[test]
fn test_challenge_res_zero_byte_entry_in_middle() {
    // 3 payloads: 10 bytes, 0 bytes, 10 bytes
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());

    let ofs0: u32 = 24; // N = 5 offsets
    let ofs1: u32 = 24 + 18; // name table: "A.DAT\0B.DAT\0C.DAT\0" (18 bytes)
    let ofs2: u32 = ofs1 + 10; // A.DAT (10 bytes)
    let ofs3: u32 = ofs2; // B.DAT (0 bytes: ofs3 == ofs2)
    let ofs4: u32 = ofs3 + 10; // C.DAT (10 bytes)

    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());
    data.extend_from_slice(&ofs3.to_le_bytes());
    data.extend_from_slice(&ofs4.to_le_bytes());

    data.extend_from_slice(b"A.DAT\0B.DAT\0C.DAT\0");
    let p_a = [0xAAu8; 10];
    let p_c = [0xCCu8; 10];
    data.extend_from_slice(&p_a);
    // B.DAT has 0 bytes (no data inserted)
    data.extend_from_slice(&p_c);

    let archive = parse_res(&data).expect("parse res with zero-byte middle entry");
    assert_eq!(archive.entries.len(), 3);

    let entry_b = archive.get("B.DAT").expect("B.DAT");
    assert_eq!(entry_b.data.len(), 0);
    assert_eq!(entry_b.source_offset, ofs2);
    assert_eq!(archive.get_bytes("b.dat"), Some([].as_slice()));

    assert_eq!(archive.get_bytes("a.dat"), Some(p_a.as_slice()));
    assert_eq!(archive.get_bytes("c.dat"), Some(p_c.as_slice()));
}

#[test]
fn test_challenge_res_trailing_padding_tolerance() {
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());

    let ofs0: u32 = 16;
    let ofs1: u32 = 16 + 6; // name table "A\0\0\0\0\0"
    let ofs2: u32 = ofs1 + 4; // payload 4 bytes
    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());

    data.extend_from_slice(b"A.DAT\0");
    data.extend_from_slice(&[0x11, 0x22, 0x33, 0x44]);

    // Add 128 bytes of arbitrary trailing padding (e.g. sector alignment on disk)
    data.extend_from_slice(&[0xEE; 128]);

    let archive = parse_res(&data).expect("parse res with trailing padding");
    assert_eq!(archive.entries.len(), 1);
    assert_eq!(
        archive.get_bytes("a.dat"),
        Some([0x11, 0x22, 0x33, 0x44].as_slice())
    );
}

#[test]
fn test_challenge_all_zero_byte_final_entry() {
    // 3 entries: ID 0x0001 (10 bytes), ID 0x0002 (5 bytes), ID 0x0003 (0 bytes at end)
    let num: u16 = 3;
    let header_size = 2 + 3 * 2 + 3 * 4; // 20 bytes
    let off0: u32 = header_size as u32;
    let off1: u32 = 30; // 10 bytes
    let off2: u32 = 35; // 5 bytes
    // Total container length = 35 bytes (so entry 2 has end = 35 -> 0 bytes)

    let mut data = Vec::new();
    data.extend_from_slice(&num.to_le_bytes());
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&2u16.to_le_bytes());
    data.extend_from_slice(&3u16.to_le_bytes());
    data.extend_from_slice(&off0.to_le_bytes());
    data.extend_from_slice(&off1.to_le_bytes());
    data.extend_from_slice(&off2.to_le_bytes());

    data.extend_from_slice(&[0x11; 10]);
    data.extend_from_slice(&[0x22; 5]);
    assert_eq!(data.len(), 35);

    let archive = parse_all(&data).expect("parse_all with 0-byte final entry");
    assert_eq!(archive.entries.len(), 3);

    let e0 = archive.get("RES_0001.BIN").expect("RES_0001.BIN");
    assert_eq!(e0.data.len(), 10);
    assert_eq!(e0.data, vec![0x11; 10]);

    let e1 = archive.get("RES_0002.BIN").expect("RES_0002.BIN");
    assert_eq!(e1.data.len(), 5);
    assert_eq!(e1.data, vec![0x22; 5]);

    let e2 = archive.get("RES_0003.BIN").expect("RES_0003.BIN");
    assert_eq!(e2.data.len(), 0);
    assert_eq!(e2.source_offset, 35);
    assert_eq!(archive.get_bytes("res_0003.bin"), Some([].as_slice()));
}

#[test]
fn test_challenge_all_all_zero_byte_entries() {
    // 4 entries, all with 0 bytes
    let num: u16 = 4;
    let header_size = (2 + 4 * 2 + 4 * 4) as u32; // 2 + 8 + 16 = 26 bytes

    let mut data = Vec::new();
    data.extend_from_slice(&num.to_le_bytes());
    for id in 1..=4u16 {
        data.extend_from_slice(&id.to_le_bytes());
    }
    for _ in 0..4 {
        data.extend_from_slice(&header_size.to_le_bytes()); // all offsets point to end of header
    }
    assert_eq!(data.len(), header_size as usize);

    let archive = parse_all(&data).expect("parse_all with all 0-byte entries");
    assert_eq!(archive.entries.len(), 4);
    for id in 1..=4u16 {
        let name = format!("RES_{id:04X}.BIN");
        let entry = archive.get(&name).unwrap();
        assert_eq!(entry.data.len(), 0);
        assert_eq!(entry.source_offset, header_size);
    }
}

#[test]
fn test_challenge_res_all_zero_byte_entries() {
    // 3 entries, all with 0 bytes payload
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());

    let ofs0: u32 = 24; // N = 5 offsets
    let ofs1: u32 = 24 + 18; // name table: "A.DAT\0B.DAT\0C.DAT\0" (18 bytes)
    let ofs2: u32 = ofs1; // payload 0: 0 bytes
    let ofs3: u32 = ofs1; // payload 1: 0 bytes
    let ofs4: u32 = ofs1; // payload 2: 0 bytes

    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());
    data.extend_from_slice(&ofs3.to_le_bytes());
    data.extend_from_slice(&ofs4.to_le_bytes());

    data.extend_from_slice(b"A.DAT\0B.DAT\0C.DAT\0");

    let archive = parse_res(&data).expect("parse res with all 0-byte payloads");
    assert_eq!(archive.entries.len(), 3);
    for name in &["A.DAT", "B.DAT", "C.DAT"] {
        let entry = archive.get(name).unwrap();
        assert_eq!(entry.data.len(), 0);
        assert_eq!(entry.source_offset, ofs1);
    }
}

#[test]
fn test_challenge_case_insensitivity_100_permutations_and_non_extensions() {
    let mut rng = SimpleRng::new(0xABCD_1234);

    let names = ["FOKKER.SOD", "TEST.BIN", "CHOREO.FLM"];
    let payloads: Vec<Vec<u8>> = (0..names.len()).map(|_| rng.next_bytes(64)).collect();

    let mut name_table_bytes = Vec::new();
    for name in &names {
        name_table_bytes.extend_from_slice(name.as_bytes());
        name_table_bytes.push(0);
    }

    let n = names.len() + 2;
    let ofs0 = (4 * (n + 1)) as u32;

    let mut offsets = Vec::with_capacity(n);
    offsets.push(ofs0);
    let mut current_offset = ofs0 + name_table_bytes.len() as u32;
    offsets.push(current_offset);
    for p in &payloads {
        current_offset += p.len() as u32;
        offsets.push(current_offset);
    }

    let mut container = Vec::new();
    container.extend_from_slice(b"RS");
    container.extend_from_slice(&1u16.to_le_bytes());
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    container.extend_from_slice(&name_table_bytes);
    for p in &payloads {
        container.extend_from_slice(p);
    }

    let archive = parse_res(&container).expect("parse_res");

    // 100 permutations per name
    for (i, name) in names.iter().enumerate() {
        for seed in 0..100u64 {
            let perm = permute_casing(name, seed.wrapping_mul(0x6A09_E667_F3BC_C908));
            assert!(
                archive.get(&perm).is_some(),
                "Lookup must succeed for permuted casing: {perm}"
            );
            assert_eq!(archive.get_bytes(&perm), Some(payloads[i].as_slice()));
        }

        // Substrings / extensions missing must return None
        let stem = name.split('.').next().unwrap();
        assert!(
            archive.get(stem).is_none(),
            "Stem '{stem}' must return None"
        );
        assert!(
            archive.get(&format!("{stem}.DAT")).is_none() || name.ends_with(".DAT"),
            "Different extension must return None"
        );
    }
}

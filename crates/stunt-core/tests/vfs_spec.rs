//! Behavioral specification of the VFS archive parsers (Seam 1): `.RES`, `.ALL` and
//! `detect_and_parse`.
//!
//! Every test here asserts a specific expected result. Panic-freedom fuzzing and matrix tests
//! (random bytes, mutation, sub-header length sweeps) live in `vfs_fuzz.rs`.
//!
//! Covered behaviour:
//! - Bit-exact payload roundtrip and metadata for multi-entry `.RES` (16 and 50 entries) and
//!   `.ALL` (12 entries) containers, including 0-byte, 1-byte and 64 KiB payloads.
//! - Invariant `[I8]`: uppercase DOS 8.3 names and case-insensitive lookup, plus negative
//!   lookups (stems, truncated names, other extensions).
//! - `.RES` name table handling: trimming, unterminated and null-padded names, fallback to
//!   `{index:04X}.BIN` for missing, non-ASCII, control-character and blank names.
//! - `.ALL` payload classification: `FILM` -> `CHOREO.FLM`, leading `0x000C` -> `MODEL_xxxx.SOD`,
//!   everything else (including payloads too short for a magic) -> `RES_xxxx.BIN`.
//! - Zero-length payloads, trailing container padding, and empty (no payload slot) archives.
//! - Structured errors: empty/sub-header buffers, bad magic, first-offset bounds and alignment,
//!   non-monotonic or out-of-bounds offsets, and oversized `.ALL` entry counts.
//! - `detect_and_parse` dispatch and the `VfsError` display/trait contract.

use stunt_core::contracts::ArchiveFormat;
use stunt_core::vfs::{VfsError, detect_and_parse, parse_all, parse_res};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/// `.RES` prefix: magic `"RS"`, version 1, then the little-endian offset table.
fn res_header(offsets: &[u32]) -> Vec<u8> {
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());
    for off in offsets {
        data.extend_from_slice(&off.to_le_bytes());
    }
    data
}

/// A `.RES` header with a single offset table entry `ofs0`, zero-padded to `total_len` bytes.
fn res_with_ofs0(ofs0: u32, total_len: usize) -> Vec<u8> {
    let mut data = res_header(&[ofs0]);
    data.resize(total_len, 0);
    data
}

/// A `.RES` header with the given offset table, zero-padded to `total_len` bytes.
fn res_with_offsets(offsets: &[u32], total_len: usize) -> Vec<u8> {
    let mut data = res_header(offsets);
    data.resize(total_len, 0);
    data
}

/// Build a `.RES` container with a null-separated name table and one payload per name.
///
/// Returns the container bytes and the offset table (`ofs[0]` = name table start,
/// `ofs[1]` = payload 0 start, `ofs[i + 1]` = payload `i` start).
fn build_res_container<S: AsRef<str>>(names: &[S], payloads: &[Vec<u8>]) -> (Vec<u8>, Vec<u32>) {
    // Construct Name Table (null-separated strings)
    let mut name_table_bytes = Vec::new();
    for name in names {
        name_table_bytes.extend_from_slice(name.as_ref().as_bytes());
        name_table_bytes.push(0); // null terminator
    }

    // Number of offsets: N = num_entries + 2
    // ofs[0]: name table start
    // ofs[1]: name table end / payload 0 start
    // ofs[2..N-1]: payload boundaries
    let n = names.len() + 2;
    let ofs0 = (4 * (n + 1)) as u32; // 4 + n*4 = 4*(n+1)

    let mut offsets = Vec::with_capacity(n);
    offsets.push(ofs0);

    let mut current_offset = ofs0 + name_table_bytes.len() as u32;
    offsets.push(current_offset);

    for p in payloads {
        current_offset += p.len() as u32;
        offsets.push(current_offset);
    }
    assert_eq!(offsets.len(), n);

    let mut container = res_header(&offsets);
    container.extend_from_slice(&name_table_bytes);
    for p in payloads {
        container.extend_from_slice(p);
    }
    (container, offsets)
}

/// Build an `.ALL` container: entry count, IDs, offsets, then back-to-back payloads.
///
/// Returns the container bytes and each payload's start offset.
fn build_all_container(ids: &[u16], payloads: &[Vec<u8>]) -> (Vec<u8>, Vec<u32>) {
    let num = ids.len();
    let header_size = 2 + num * 6; // count + ids (2 bytes each) + offsets (4 bytes each)

    let mut offsets = Vec::with_capacity(num);
    let mut current_offset = header_size as u32;
    for p in payloads {
        offsets.push(current_offset);
        current_offset += p.len() as u32;
    }

    let mut container = Vec::new();
    container.extend_from_slice(&(num as u16).to_le_bytes());
    for id in ids {
        container.extend_from_slice(&id.to_le_bytes());
    }
    for off in &offsets {
        container.extend_from_slice(&off.to_le_bytes());
    }
    for p in payloads {
        container.extend_from_slice(p);
    }
    (container, offsets)
}

/// Build a valid two-payload `.RES` skeleton with customized (raw) name table bytes.
fn build_res_with_name_table(names_raw: &[u8]) -> Vec<u8> {
    let ofs0: u32 = 20;
    let ofs1: u32 = 20 + names_raw.len() as u32;
    let ofs2: u32 = ofs1 + 8; // payload 0 (8 bytes)
    let ofs3: u32 = ofs2 + 8; // payload 1 (8 bytes)

    let mut data = res_header(&[ofs0, ofs1, ofs2, ofs3]);
    assert_eq!(data.len(), 20);

    data.extend_from_slice(names_raw);
    data.extend_from_slice(&[0x11u8; 8]); // payload 0
    data.extend_from_slice(&[0x22u8; 8]); // payload 1
    data
}

// ---------------------------------------------------------------------------
// .RES: parsing, names, payloads
// ---------------------------------------------------------------------------

#[test]
fn res_synthetic_minimal_fixture_parses() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let fixture_path = std::path::Path::new(manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
        .join("fixtures")
        .join("synthetic_minimal.res");

    let data = std::fs::read(&fixture_path).expect("read synthetic_minimal.res");
    let archive = parse_res(&data).expect("parse_res must succeed on minimal fixture");

    assert_eq!(archive.format, ArchiveFormat::Res);
    assert_eq!(archive.entries.len(), 2);

    // Verify PLANE.SOD
    let plane = archive.get("PLANE.SOD").expect("PLANE.SOD must be present");
    assert_eq!(plane.name, "PLANE.SOD");
    assert_eq!(plane.source_offset, 40);
    assert_eq!(plane.data.len(), 16);
    assert_eq!(plane.data, &data[40..56]);
    assert!(!plane.was_compressed);

    // Verify PROP.SOD
    let prop = archive.get("PROP.SOD").expect("PROP.SOD must be present");
    assert_eq!(prop.name, "PROP.SOD");
    assert_eq!(prop.source_offset, 56);
    assert_eq!(prop.data.len(), 16);
    assert_eq!(prop.data, &data[56..72]);
    assert!(!prop.was_compressed);

    // Invariant [I8]: Case-insensitive lookups
    assert!(archive.get("plane.sod").is_some());
    assert!(archive.get("Plane.Sod").is_some());
    assert!(archive.get("PLANE.SOD").is_some());
    assert_eq!(archive.get_bytes("plane.sod"), Some(&data[40..56]));
    assert_eq!(archive.get_bytes("prop.sod"), Some(&data[56..72]));
    assert_eq!(archive.get("NONEXISTENT.FILE"), None);
}

#[test]
fn res_names_are_normalized_to_uppercase() {
    // Construct in-memory .RES container:
    // Header (4 bytes): "RS" + version 1
    // Offset table: ofs[0]=24 (N = 24/4 - 1 = 5 offsets: ofs[0..4])
    // ofs[0]=24, ofs[1]=54, ofs[2]=64, ofs[3]=74, ofs[4]=84
    // Name table (bytes 24..54, 30 bytes): "foo.sod\0bar.sod\0baz.bin\0\0\0\0\0\0\0"
    // Payloads:
    // Payload 0 (FOO.SOD): 54..64 (10 bytes)
    // Payload 1 (BAR.SOD): 64..74 (10 bytes)
    // Payload 2 (BAZ.BIN): 74..84 (10 bytes)
    let mut data = res_header(&[24, 54, 64, 74, 84]);
    assert_eq!(data.len(), 24);

    // Name table: 24..54 (30 bytes)
    let names = b"foo.sod\0bar.sod\0baz.bin\0\0\0\0\0\0\0";
    data.extend_from_slice(names);
    assert_eq!(data.len(), 54);

    // Payloads: 54..64, 64..74, 74..84
    let p0 = [0xAAu8; 10];
    let p1 = [0xBBu8; 10];
    let p2 = [0xCCu8; 10];
    data.extend_from_slice(&p0);
    data.extend_from_slice(&p1);
    data.extend_from_slice(&p2);
    assert_eq!(data.len(), 84);

    let archive = parse_res(&data).expect("parse custom .RES");
    assert_eq!(archive.format, ArchiveFormat::Res);
    assert_eq!(archive.entries.len(), 3);

    // Names normalized to uppercase DOS 8.3
    let foo = archive.get("FOO.SOD").expect("FOO.SOD");
    assert_eq!(foo.name, "FOO.SOD");
    assert_eq!(foo.data, p0);
    assert_eq!(foo.source_offset, 54);

    let bar = archive.get("BAR.SOD").expect("BAR.SOD");
    assert_eq!(bar.name, "BAR.SOD");
    assert_eq!(bar.data, p1);
    assert_eq!(bar.source_offset, 64);

    let baz = archive.get("BAZ.BIN").expect("BAZ.BIN");
    assert_eq!(baz.name, "BAZ.BIN");
    assert_eq!(baz.data, p2);
    assert_eq!(baz.source_offset, 74);

    // Case-insensitive lookups [I8]
    assert_eq!(archive.get_bytes("foo.sod"), Some(p0.as_slice()));
    assert_eq!(archive.get_bytes("Bar.Sod"), Some(p1.as_slice()));
    assert_eq!(archive.get_bytes("BAZ.bin"), Some(p2.as_slice()));
}

#[test]
fn res_name_table_falls_back_to_index_names() {
    // Omitted name table: ofs[0] == ofs[1] (empty name table)
    // ofs[0] = 16, N = 16/4 - 1 = 3 offsets (ofs[0..2])
    // ofs[0]=16, ofs[1]=16, ofs[2]=24
    // Payload 0: 16..24 (8 bytes) -> name should default to "0000.BIN"
    let mut data = res_header(&[16, 16, 24]);
    data.extend_from_slice(&[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);

    let archive = parse_res(&data).expect("parse res with omitted name table");
    assert_eq!(archive.entries.len(), 1);

    let entry = archive.get("0000.BIN").expect("0000.BIN");
    assert_eq!(entry.name, "0000.BIN");
    assert_eq!(entry.source_offset, 16);
    assert_eq!(entry.data, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);

    // Name table containing only binary non-ASCII data
    // ofs[0] = 16, ofs[1] = 20, ofs[2] = 28
    // Name table (16..20): [0xFF, 0xFE, 0xFD, 0xFC] (non-ASCII)
    // Payload 0: 20..28 (8 bytes) -> fallback name "0000.BIN"
    let mut data = res_header(&[16, 20, 28]);
    data.extend_from_slice(&[0xFF, 0xFE, 0xFD, 0xFC]); // non-ascii in name table
    data.extend_from_slice(&[0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]);

    let archive = parse_res(&data).expect("parse res with binary in name table");
    assert_eq!(archive.entries.len(), 1);
    let entry = archive.get("0000.BIN").expect("0000.BIN");
    assert_eq!(entry.data, [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]);

    // Non-ASCII characters (0x80..=0xFF) mixed with a valid name -> name table discarded,
    // fallback to 0000.BIN / 0001.BIN
    let corrupted_names = b"PLANE.SOD\0\x80\xFF\xFE\0";
    let data = build_res_with_name_table(corrupted_names);
    let archive = parse_res(&data).expect("corrupt names should cleanly fallback, not error");
    assert_eq!(archive.entries.len(), 2);
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Control characters (\t, \n, \r) -> fallback to default names
    let ctrl_names = b"PLANE.SOD\0BAD\tNAME.SOD\0";
    let data = build_res_with_name_table(ctrl_names);
    let archive = parse_res(&data).expect("ctrl char in names should fallback");
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Empty / whitespace names -> trimmed to empty -> fallback to default names
    let whitespace_names = b"   \0  \t  \0";
    let data = build_res_with_name_table(whitespace_names);
    let archive = parse_res(&data).expect("whitespace names fallback");
    assert!(archive.get("0000.BIN").is_some());
    assert!(archive.get("0001.BIN").is_some());

    // Fewer names than payloads (only 1 name for 2 payloads)
    let short_names = b"single.sod\0";
    let data = build_res_with_name_table(short_names);
    let archive = parse_res(&data).expect("short name table should parse");
    assert_eq!(archive.entries.len(), 2);
    assert!(archive.get("SINGLE.SOD").is_some());
    assert!(archive.get("0001.BIN").is_some()); // payload 1 defaults to 0001.BIN

    // Fewer names than payloads, with payload bytes verified: the remainder falls back to
    // {:04X}.BIN
    // N = 4 offsets (ofs[0..3]) -> 2 payloads.
    // Name table only contains 1 name "FIRST.SOD\0" (10 bytes).
    // ofs0 = 20, ofs1 = 30 (name table end), ofs2 = 34 (payload 0), ofs3 = 38 (payload 1)
    let mut data2 = res_header(&[20, 30, 34, 38]);
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
fn res_name_table_trims_and_normalizes_names() {
    // Whitespace in names: names with leading/trailing spaces must be trimmed
    // N = 3 offsets (ofs[0], ofs[1], ofs[2]) -> ofs[0] = 16
    // Name table: "  TRIMMED.SOD  \0" (16 bytes), payload: 8 bytes
    let mut data = res_header(&[16, 16 + 16, 16 + 16 + 8]);
    data.extend_from_slice(b"  TRIMMED.SOD  \0");
    let payload = [0x42u8; 8];
    data.extend_from_slice(&payload);

    let archive = parse_res(&data).expect("parse res with spaces");
    assert_eq!(archive.entries.len(), 1);

    // Should be trimmed and uppercase
    assert!(archive.get("TRIMMED.SOD").is_some());
    assert!(archive.get("trimmed.sod").is_some());
    assert_eq!(archive.get_bytes("trimmed.sod"), Some(payload.as_slice()));

    // Names with leading/trailing spaces -> trimmed and normalized (two payloads)
    let padded_names = b"  plane.sod  \0  prop.sod \0";
    let data = build_res_with_name_table(padded_names);
    let archive = parse_res(&data).expect("padded names should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());
    assert!(archive.get("plane.sod").is_some());

    // Unterminated name (no trailing null)
    let unterminated_names = b"plane.sod\0prop.sod";
    let data = build_res_with_name_table(unterminated_names);
    let archive = parse_res(&data).expect("unterminated name should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());

    // Consecutive nulls (empty entries)
    let null_padded = b"\0\0PLANE.SOD\0\0\0PROP.SOD\0\0";
    let data = build_res_with_name_table(null_padded);
    let archive = parse_res(&data).expect("null padded name table should parse");
    assert!(archive.get("PLANE.SOD").is_some());
    assert!(archive.get("PROP.SOD").is_some());
}

#[test]
fn res_multi_entry_roundtrip_16_entries_is_bit_exact() {
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
    let (container, offsets) = build_res_container(&names, &payloads);

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
fn res_large_container_roundtrip_50_entries() {
    let mut rng = SimpleRng::new(0x50_50_50_50);

    let count = 50;
    let mut names = Vec::with_capacity(count);
    let mut payloads = Vec::with_capacity(count);

    for i in 0..count {
        names.push(format!("ASSET_{i:03}.DAT"));
        let sz = (i * 137 + 11) % 5000;
        payloads.push(rng.next_bytes(sz));
    }

    let (container, offsets) = build_res_container(&names, &payloads);

    let archive = parse_res(&container).expect("parse_res 50 entries");
    assert_eq!(archive.entries.len(), count);

    for (i, name) in names.iter().enumerate() {
        let entry = archive.get(name).expect("entry must exist");
        assert_eq!(&entry.data, &payloads[i]);
        assert_eq!(entry.source_offset, offsets[i + 1]);
    }
}

#[test]
fn res_trailing_padding_is_ignored() {
    let ofs0: u32 = 16;
    let ofs1: u32 = 16 + 6; // name table "A.DAT\0"
    let ofs2: u32 = ofs1 + 4; // payload 4 bytes
    let mut data = res_header(&[ofs0, ofs1, ofs2]);

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
fn res_zero_length_payloads_are_valid_entries() {
    // Zero-length payload in the middle: 3 payloads of 10 bytes, 0 bytes, 10 bytes
    let ofs0: u32 = 24; // N = 5 offsets
    let ofs1: u32 = 24 + 18; // name table: "A.DAT\0B.DAT\0C.DAT\0" (18 bytes)
    let ofs2: u32 = ofs1 + 10; // A.DAT (10 bytes)
    let ofs3: u32 = ofs2; // B.DAT (0 bytes: ofs3 == ofs2)
    let ofs4: u32 = ofs3 + 10; // C.DAT (10 bytes)
    let mut data = res_header(&[ofs0, ofs1, ofs2, ofs3, ofs4]);

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

    // Every named payload has zero length (3 payloads, all offsets equal)
    let ofs0: u32 = 24; // N = 5 offsets
    let ofs1: u32 = 24 + 18; // name table: "A.DAT\0B.DAT\0C.DAT\0" (18 bytes)
    let mut data = res_header(&[ofs0, ofs1, ofs1, ofs1, ofs1]);
    data.extend_from_slice(b"A.DAT\0B.DAT\0C.DAT\0");

    let archive = parse_res(&data).expect("parse res with all 0-byte payloads");
    assert_eq!(archive.entries.len(), 3);
    for name in &["A.DAT", "B.DAT", "C.DAT"] {
        let entry = archive.get(name).unwrap();
        assert_eq!(entry.data.len(), 0);
        assert_eq!(entry.source_offset, ofs1);
    }

    // Zero-length payloads without a name table: start == end for all payloads, so the
    // entries take the fallback names
    let data = res_header(&[20, 20, 20, 20]);

    let archive = parse_res(&data).expect("zero-length payloads in .RES should succeed");
    assert_eq!(archive.format, ArchiveFormat::Res);
    // payload_count = 4 - 2 = 2 entries: 0000.BIN and 0001.BIN with len 0
    assert_eq!(archive.entries.len(), 2);
    assert_eq!(archive.get_bytes("0000.BIN"), Some([].as_slice()));
    assert_eq!(archive.get_bytes("0001.BIN"), Some([].as_slice()));
}

#[test]
fn res_without_payload_slots_yields_empty_archive() {
    // Empty table (N < 2, ofs[0] == 8): N = 8/4 - 1 = 1
    let empty_table = res_header(&[8]);
    let archive = parse_res(&empty_table).expect("empty table yields empty archive");
    assert_eq!(archive.entries.len(), 0);

    // ofs0 = 12: N = (12/4) - 1 = 2 offsets (ofs0, ofs1).
    // payload_count = N - 2 = 0.
    // ofs0 = 12, ofs1 = 12
    let data = res_header(&[12, 12]);
    assert_eq!(data.len(), 12);

    let archive = parse_res(&data).expect("N=2 boundary in .RES must produce empty archive");
    assert_eq!(archive.entries.len(), 0);

    // What if ofs1 is 20, with 8 bytes between 12 and 20?
    let mut data2 = res_header(&[12, 20]);
    data2.extend_from_slice(b"FOOBARBA"); // name slice, but 0 payloads
    let archive2 = parse_res(&data2).expect("N=2 with name slice must produce empty archive");
    assert_eq!(archive2.entries.len(), 0);
}

// ---------------------------------------------------------------------------
// .RES: structured errors
// ---------------------------------------------------------------------------

#[test]
fn res_rejects_bad_magic() {
    assert_eq!(
        parse_res(b"XX\x01\x00\x14\x00\x00\x00"),
        Err(VfsError::InvalidMagic {
            expected: "RS",
            actual: *b"XX",
        })
    );

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

#[test]
fn res_rejects_invalid_first_offset() {
    // ofs0 < 8 (inside the fixed header): every value 0..=7
    for bad_ofs in 0..8u32 {
        let res = parse_res(&res_with_ofs0(bad_ofs, 40));
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "ofs0={bad_ofs} must be rejected as InvalidOffsetTable"
        );
    }
    // ofs0 = 4 in a bare 8-byte buffer
    assert!(matches!(
        parse_res(&res_with_ofs0(4, 8)),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // ofs0 unaligned to 4 bytes
    for unaligned in [9u32, 10, 11, 13, 14, 15, 17, 18, 19] {
        let res = parse_res(&res_with_ofs0(unaligned, 64));
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "unaligned ofs0={unaligned} must be rejected as InvalidOffsetTable"
        );
    }
    // ofs0 = 9 in an 18-byte buffer
    assert!(matches!(
        parse_res(&res_with_ofs0(9, 18)),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // ofs0 beyond the buffer: u32::MAX, u32::MAX - 1, etc.
    for huge_ofs in [u32::MAX, u32::MAX - 1, u32::MAX - 3, 0x8000_0000] {
        let res = parse_res(&res_with_ofs0(huge_ofs, 32));
        assert!(
            matches!(res, Err(VfsError::UnexpectedEof { .. })),
            "huge ofs0={huge_ofs} beyond data.len() must return UnexpectedEof"
        );
    }
    // ofs0 = 100 in a bare 8-byte buffer reports exact lengths
    assert_eq!(
        parse_res(&res_with_ofs0(100, 8)),
        Err(VfsError::UnexpectedEof {
            expected: 100,
            actual: 8,
        })
    );
}

#[test]
fn res_rejects_non_monotonic_and_out_of_bounds_offsets() {
    // Table with N = 4 offsets (ofs[0]=20, ofs[1]=30, ofs[2]=40, ofs[3]=50),
    // then perturb each position to be non-monotonic or out of bounds.
    let base_offsets: [u32; 4] = [20, 30, 40, 50];

    // Non-monotonic pairs: offsets[i+1] < offsets[i]
    for i in 0..3 {
        let mut offsets = base_offsets;
        // Make index i+1 smaller than index i
        offsets[i + 1] = offsets[i] - 1;

        let res = parse_res(&res_with_offsets(&offsets, 100));
        assert!(
            matches!(res, Err(VfsError::InvalidOffsetTable { .. })),
            "Non-monotonic offset at index {} must return InvalidOffsetTable",
            i + 1
        );
    }

    // N = 3: ofs[0] = 16, ofs[1] = 24, ofs[2] = 20 (< ofs[1]!)
    let mut non_monotonic = res_header(&[16, 24, 20]);
    non_monotonic.extend_from_slice(&[0; 16]);
    assert!(matches!(
        parse_res(&non_monotonic),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // Out-of-bounds offset in table
    for i in 1..4 {
        let mut offsets = base_offsets;
        offsets[i] = 200; // beyond data.len() = 100

        let res = parse_res(&res_with_offsets(&offsets, 100));
        assert!(
            matches!(res, Err(VfsError::UnexpectedEof { .. })),
            "Out of bounds offset {i} must return UnexpectedEof"
        );
    }
}

// ---------------------------------------------------------------------------
// .ALL: parsing, classification, payloads
// ---------------------------------------------------------------------------

#[test]
fn all_empty_archive_has_no_entries() {
    let num: u16 = 0;
    let data = num.to_le_bytes();
    let archive = parse_all(&data).expect("empty .ALL archive");
    assert_eq!(archive.format, ArchiveFormat::All);
    assert_eq!(archive.entries.len(), 0);
}

#[test]
fn all_classifies_film_sod_and_raw_payloads() {
    // Construct .ALL container:
    // num = 3
    // IDs: [0x0001, 0x0042, 0x0099]
    // Header size = 2 + 3*2 + 3*4 = 2 + 6 + 12 = 20 bytes
    // Offsets: [20, 32, 44]
    // Payloads:
    // Entry 0 (id 0x0001): 20..32 (12 bytes) starts with b"FILM\x00\x00\x00\x00..." -> "CHOREO.FLM"
    // Entry 1 (id 0x0042): 32..44 (12 bytes) starts with [0x0C, 0x00] (0x000C) -> "MODEL_0042.SOD"
    // Entry 2 (id 0x0099): 44..56 (12 bytes) starts with [0x55, 0xAA] -> "RES_0099.BIN"
    let mut data = Vec::new();
    let num: u16 = 3;
    data.extend_from_slice(&num.to_le_bytes());

    // IDs
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&0x0042u16.to_le_bytes());
    data.extend_from_slice(&0x0099u16.to_le_bytes());

    // Offsets
    let off0: u32 = 20;
    let off1: u32 = 32;
    let off2: u32 = 44;
    data.extend_from_slice(&off0.to_le_bytes());
    data.extend_from_slice(&off1.to_le_bytes());
    data.extend_from_slice(&off2.to_le_bytes());
    assert_eq!(data.len(), 20);

    // Payload 0: FILM
    let mut p0 = vec![0u8; 12];
    p0[0..4].copy_from_slice(b"FILM");
    data.extend_from_slice(&p0);

    // Payload 1: SOD (magic 0x000C)
    let mut p1 = vec![0u8; 12];
    p1[0..2].copy_from_slice(&0x000Cu16.to_le_bytes());
    data.extend_from_slice(&p1);

    // Payload 2: Raw binary
    let mut p2 = vec![0u8; 12];
    p2[0] = 0x55;
    p2[1] = 0xAA;
    data.extend_from_slice(&p2);

    assert_eq!(data.len(), 56);

    let archive = parse_all(&data).expect("parse_all valid");
    assert_eq!(archive.format, ArchiveFormat::All);
    assert_eq!(archive.entries.len(), 3);

    // Verify FILM classification
    let film = archive.get("CHOREO.FLM").expect("CHOREO.FLM");
    assert_eq!(film.name, "CHOREO.FLM");
    assert_eq!(film.source_offset, 20);
    assert_eq!(film.data, p0);

    // Verify SOD classification
    let sod = archive.get("MODEL_0042.SOD").expect("MODEL_0042.SOD");
    assert_eq!(sod.name, "MODEL_0042.SOD");
    assert_eq!(sod.source_offset, 32);
    assert_eq!(sod.data, p1);

    // Verify default BIN classification
    let bin = archive.get("RES_0099.BIN").expect("RES_0099.BIN");
    assert_eq!(bin.name, "RES_0099.BIN");
    assert_eq!(bin.source_offset, 44);
    assert_eq!(bin.data, p2);

    // Invariant [I8]: Case-insensitivity
    assert!(archive.get("choreo.flm").is_some());
    assert!(archive.get("model_0042.sod").is_some());
    assert!(archive.get("res_0099.bin").is_some());
}

#[test]
fn all_classification_requires_full_magic_length() {
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
fn all_multi_entry_roundtrip_12_entries_is_bit_exact() {
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

    let ids: Vec<u16> = specs.iter().map(|spec| spec.id).collect();
    let (container, offsets) = build_all_container(&ids, &payloads);

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
fn all_zero_length_payloads_are_valid_entries() {
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

    // 2 entries where offsets[0] == offsets[1] == data.len()
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

// ---------------------------------------------------------------------------
// .ALL: structured errors
// ---------------------------------------------------------------------------

#[test]
fn all_rejects_invalid_offset_tables() {
    // Buffer shorter than the 2-byte entry count
    assert_eq!(
        parse_all(&[0x01]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 1,
        })
    );

    // Buffer shorter than the header
    let num: u16 = 2; // header size = 2 + 2*2 + 2*4 = 14
    let mut truncated = Vec::new();
    truncated.extend_from_slice(&num.to_le_bytes());
    truncated.extend_from_slice(&[0; 8]); // only 10 bytes
    assert_eq!(
        parse_all(&truncated),
        Err(VfsError::UnexpectedEof {
            expected: 14,
            actual: 10,
        })
    );

    // Huge num = 0xFFFF
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

    // First offset inside header table
    let num: u16 = 1; // header size = 8
    let mut bad_off = Vec::new();
    bad_off.extend_from_slice(&num.to_le_bytes());
    bad_off.extend_from_slice(&1u16.to_le_bytes()); // id
    bad_off.extend_from_slice(&4u32.to_le_bytes()); // offset 4 (< 8!)
    assert!(matches!(
        parse_all(&bad_off),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // num = 2, header_size = 2 + 2*2 + 2*4 = 14: first offset < header_size
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

    // Offset beyond buffer
    let num: u16 = 1;
    let mut beyond = Vec::new();
    beyond.extend_from_slice(&num.to_le_bytes());
    beyond.extend_from_slice(&1u16.to_le_bytes());
    beyond.extend_from_slice(&100u32.to_le_bytes()); // offset 100
    assert_eq!(
        parse_all(&beyond),
        Err(VfsError::UnexpectedEof {
            expected: 100,
            actual: 8,
        })
    );

    // Offset beyond a 20-byte buffer
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

    // Non-monotonic offsets (header size = 14)
    let num: u16 = 2;
    let mut non_monotonic = Vec::new();
    non_monotonic.extend_from_slice(&num.to_le_bytes());
    non_monotonic.extend_from_slice(&1u16.to_le_bytes());
    non_monotonic.extend_from_slice(&2u16.to_le_bytes());
    non_monotonic.extend_from_slice(&20u32.to_le_bytes());
    non_monotonic.extend_from_slice(&16u32.to_le_bytes()); // 16 < 20!
    non_monotonic.extend_from_slice(&[0; 16]);
    assert!(matches!(
        parse_all(&non_monotonic),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // Non-monotonic offsets in .ALL (off[1] < off[0]) in a 50-byte buffer
    let mut data = Vec::new();
    data.extend_from_slice(&2u16.to_le_bytes());
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&2u16.to_le_bytes());
    data.extend_from_slice(&20u32.to_le_bytes()); // off 0 = 20
    data.extend_from_slice(&19u32.to_le_bytes()); // off 1 = 19 < 20
    data.resize(50, 0);

    let res = parse_all(&data);
    assert!(matches!(res, Err(VfsError::InvalidOffsetTable { .. })));
}

// ---------------------------------------------------------------------------
// Shared: empty buffers, dispatch, case-insensitive lookup, error type
// ---------------------------------------------------------------------------

#[test]
fn empty_and_sub_header_buffers_report_unexpected_eof() {
    // .RES needs an 8-byte header
    assert_eq!(
        parse_res(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: 0,
        })
    );
    assert_eq!(
        parse_res(b"RS"),
        Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: 2,
        })
    );

    // .ALL needs a 2-byte entry count
    assert_eq!(
        parse_all(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 0,
        })
    );
    assert_eq!(
        parse_all(&[0x01]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 1,
        })
    );

    // detect_and_parse needs 2 bytes to sniff the magic
    assert_eq!(
        detect_and_parse(&[]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 0,
        })
    );
    assert_eq!(
        detect_and_parse(b"R"),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 1,
        })
    );
}

#[test]
fn detect_and_parse_dispatches_on_res_magic() {
    // Data starting with "RS" -> routes to parse_res
    let res_data = res_header(&[8]);
    let res_archive = detect_and_parse(&res_data).expect("detect res");
    assert_eq!(res_archive.format, ArchiveFormat::Res);

    // Data not starting with "RS" -> routes to parse_all
    let num: u16 = 0;
    let all_data = num.to_le_bytes();
    let all_archive = detect_and_parse(&all_data).expect("detect all");
    assert_eq!(all_archive.format, ArchiveFormat::All);
}

#[test]
fn res_lookup_is_case_insensitive_and_exact_otherwise() {
    // Invariant [I8] Case-Insensitivity Oracle over mixed-case stored names
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
    let (container, _) = build_res_container(&names, &payloads);

    let archive = parse_res(&container).expect("parse_res");

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

    // 100 permutations per name, and stems / other extensions must not match
    let mut rng = SimpleRng::new(0xABCD_1234);

    let names = ["FOKKER.SOD", "TEST.BIN", "CHOREO.FLM"];
    let payloads: Vec<Vec<u8>> = (0..names.len()).map(|_| rng.next_bytes(64)).collect();
    let (container, _) = build_res_container(&names, &payloads);

    let archive = parse_res(&container).expect("parse_res");

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

#[test]
fn all_lookup_is_case_insensitive() {
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

    let (container, _) = build_all_container(&ids, &payloads);

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
fn vfs_error_display_and_traits() {
    let err1 = VfsError::UnexpectedEof {
        expected: 72,
        actual: 40,
    };
    let err2 = VfsError::InvalidMagic {
        expected: "RS",
        actual: [0x58, 0x59],
    };
    let err3 = VfsError::InvalidOffsetTable {
        reason: "out of bounds".to_string(),
    };
    let err4 = VfsError::EntryNotFound {
        name: "MISSING.SOD".to_string(),
    };
    let err5 = VfsError::CorruptedPayload {
        name: "CORRUPT.SOD".to_string(),
        offset: 100,
        len: 50,
    };

    assert_eq!(
        err1.to_string(),
        "unexpected EOF: expected at least 72 bytes, found 40"
    );
    assert_eq!(
        err2.to_string(),
        "invalid container magic: expected \"RS\", found [0x58, 0x59]"
    );
    assert_eq!(err3.to_string(), "invalid offset table: out of bounds");
    assert_eq!(err4.to_string(), "entry not found: MISSING.SOD");
    assert_eq!(
        err5.to_string(),
        "corrupted payload for entry 'CORRUPT.SOD' at offset 100 (len 50)"
    );

    // Verify traits: Clone, PartialEq, Debug, std::error::Error
    let cloned = err1.clone();
    assert_eq!(err1, cloned);
    assert_ne!(err1, err2);
    let debug_str = format!("{err1:?}");
    assert!(debug_str.contains("UnexpectedEof"));

    let std_err: &dyn std::error::Error = &err1;
    assert_eq!(std_err.to_string(), err1.to_string());
}

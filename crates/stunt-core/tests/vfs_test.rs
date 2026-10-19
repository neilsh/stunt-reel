use stunt_core::contracts::ArchiveFormat;
use stunt_core::vfs::{VfsError, detect_and_parse, parse_all, parse_res};

#[test]
fn test_parse_res_synthetic_minimal_fixture() {
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
fn test_parse_res_custom_container_with_names() {
    // Construct in-memory .RES container:
    // Header (4 bytes): "RS" + version 1
    // Offset table: ofs[0]=24 (N = 24/4 - 1 = 5 offsets: ofs[0..4])
    // ofs[0]=24, ofs[1]=54, ofs[2]=64, ofs[3]=74, ofs[4]=84
    // Name table (bytes 24..54, 30 bytes): "FOO.SOD\0BAR.SOD\0BAZ.BIN\0\0\0\0\0\0"
    // Payloads:
    // Payload 0 (FOO.SOD): 54..64 (10 bytes)
    // Payload 1 (BAR.SOD): 64..74 (10 bytes)
    // Payload 2 (BAZ.BIN): 74..84 (10 bytes)
    let mut data = Vec::new();
    // 0..2: Magic "RS"
    data.extend_from_slice(b"RS");
    // 2..4: Version 1
    data.extend_from_slice(&1u16.to_le_bytes());
    // 4..24: 5 offsets (20 bytes)
    let ofs0: u32 = 24;
    let ofs1: u32 = 54;
    let ofs2: u32 = 64;
    let ofs3: u32 = 74;
    let ofs4: u32 = 84;
    data.extend_from_slice(&ofs0.to_le_bytes());
    data.extend_from_slice(&ofs1.to_le_bytes());
    data.extend_from_slice(&ofs2.to_le_bytes());
    data.extend_from_slice(&ofs3.to_le_bytes());
    data.extend_from_slice(&ofs4.to_le_bytes());
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
fn test_parse_res_omitted_name_table() {
    // Container where ofs[0] == ofs[1] (empty name table)
    // ofs[0] = 16, N = 16/4 - 1 = 3 offsets (ofs[0..2])
    // ofs[0]=16, ofs[1]=16, ofs[2]=24
    // Payload 0: 16..24 (8 bytes) -> name should default to "0000.BIN"
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&16u32.to_le_bytes()); // ofs[0]
    data.extend_from_slice(&16u32.to_le_bytes()); // ofs[1]
    data.extend_from_slice(&24u32.to_le_bytes()); // ofs[2]
    data.extend_from_slice(&[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);

    let archive = parse_res(&data).expect("parse res with omitted name table");
    assert_eq!(archive.entries.len(), 1);

    let entry = archive.get("0000.BIN").expect("0000.BIN");
    assert_eq!(entry.name, "0000.BIN");
    assert_eq!(entry.source_offset, 16);
    assert_eq!(entry.data, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);
}

#[test]
fn test_parse_res_binary_in_name_table() {
    // Container where name table contains binary non-ASCII data
    // ofs[0] = 16, ofs[1] = 20, ofs[2] = 28
    // Name table (16..20): [0xFF, 0xFE, 0xFD, 0xFC] (non-ASCII)
    // Payload 0: 20..28 (8 bytes) -> fallback name "0000.BIN"
    let mut data = Vec::new();
    data.extend_from_slice(b"RS");
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&16u32.to_le_bytes()); // ofs[0]
    data.extend_from_slice(&20u32.to_le_bytes()); // ofs[1]
    data.extend_from_slice(&28u32.to_le_bytes()); // ofs[2]
    data.extend_from_slice(&[0xFF, 0xFE, 0xFD, 0xFC]); // non-ascii in name table
    data.extend_from_slice(&[0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]);

    let archive = parse_res(&data).expect("parse res with binary in name table");
    assert_eq!(archive.entries.len(), 1);
    let entry = archive.get("0000.BIN").expect("0000.BIN");
    assert_eq!(entry.data, [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]);
}

#[test]
fn test_parse_res_errors() {
    // 1. Unexpected EOF on small header
    assert_eq!(
        parse_res(b"RS"),
        Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: 2,
        })
    );

    // 2. Invalid magic
    assert_eq!(
        parse_res(b"XX\x01\x00\x14\x00\x00\x00"),
        Err(VfsError::InvalidMagic {
            expected: "RS",
            actual: *b"XX",
        })
    );

    // 3. ofs[0] < 8
    let mut bad_ofs = Vec::new();
    bad_ofs.extend_from_slice(b"RS");
    bad_ofs.extend_from_slice(&1u16.to_le_bytes());
    bad_ofs.extend_from_slice(&4u32.to_le_bytes());
    assert!(matches!(
        parse_res(&bad_ofs),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // 4. ofs[0] not 4-byte aligned
    let mut unaligned = Vec::new();
    unaligned.extend_from_slice(b"RS");
    unaligned.extend_from_slice(&1u16.to_le_bytes());
    unaligned.extend_from_slice(&9u32.to_le_bytes());
    unaligned.extend_from_slice(&[0; 10]);
    assert!(matches!(
        parse_res(&unaligned),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // 5. ofs[0] beyond buffer length
    let mut truncated = Vec::new();
    truncated.extend_from_slice(b"RS");
    truncated.extend_from_slice(&1u16.to_le_bytes());
    truncated.extend_from_slice(&100u32.to_le_bytes());
    assert_eq!(
        parse_res(&truncated),
        Err(VfsError::UnexpectedEof {
            expected: 100,
            actual: 8,
        })
    );

    // 6. Non-monotonic offsets
    let mut non_monotonic = Vec::new();
    non_monotonic.extend_from_slice(b"RS");
    non_monotonic.extend_from_slice(&1u16.to_le_bytes());
    non_monotonic.extend_from_slice(&16u32.to_le_bytes()); // ofs[0] = 16
    non_monotonic.extend_from_slice(&24u32.to_le_bytes()); // ofs[1] = 24
    non_monotonic.extend_from_slice(&20u32.to_le_bytes()); // ofs[2] = 20 (< ofs[1]!)
    non_monotonic.extend_from_slice(&[0; 16]);
    assert!(matches!(
        parse_res(&non_monotonic),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // 7. Empty table (N < 2, ofs[0] == 8)
    let mut empty_table = Vec::new();
    empty_table.extend_from_slice(b"RS");
    empty_table.extend_from_slice(&1u16.to_le_bytes());
    empty_table.extend_from_slice(&8u32.to_le_bytes()); // N = 8/4 - 1 = 1 < 2
    let archive = parse_res(&empty_table).expect("empty table yields empty archive");
    assert_eq!(archive.entries.len(), 0);
}

#[test]
fn test_parse_all_valid_mixed() {
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
fn test_parse_all_empty() {
    let num: u16 = 0;
    let data = num.to_le_bytes();
    let archive = parse_all(&data).expect("empty .ALL archive");
    assert_eq!(archive.format, ArchiveFormat::All);
    assert_eq!(archive.entries.len(), 0);
}

#[test]
fn test_parse_all_errors() {
    // 1. Buffer len < 2
    assert_eq!(
        parse_all(&[0x01]),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 1,
        })
    );

    // 2. Buffer len < header size
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

    // 3. First offset inside header table
    let num: u16 = 1; // header size = 8
    let mut bad_off = Vec::new();
    bad_off.extend_from_slice(&num.to_le_bytes());
    bad_off.extend_from_slice(&1u16.to_le_bytes()); // id
    bad_off.extend_from_slice(&4u32.to_le_bytes()); // offset 4 (< 8!)
    assert!(matches!(
        parse_all(&bad_off),
        Err(VfsError::InvalidOffsetTable { .. })
    ));

    // 4. Offset beyond buffer
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

    // 5. Non-monotonic offsets
    let num: u16 = 2; // header size = 14
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
}

#[test]
fn test_detect_and_parse_dispatch() {
    // 1. Data starting with "RS" -> routes to parse_res
    let mut res_data = Vec::new();
    res_data.extend_from_slice(b"RS");
    res_data.extend_from_slice(&1u16.to_le_bytes());
    res_data.extend_from_slice(&8u32.to_le_bytes());
    let res_archive = detect_and_parse(&res_data).expect("detect res");
    assert_eq!(res_archive.format, ArchiveFormat::Res);

    // 2. Data not starting with "RS" -> routes to parse_all
    let num: u16 = 0;
    let all_data = num.to_le_bytes();
    let all_archive = detect_and_parse(&all_data).expect("detect all");
    assert_eq!(all_archive.format, ArchiveFormat::All);

    // 3. Data shorter than 2 bytes -> UnexpectedEof
    assert_eq!(
        detect_and_parse(b"R"),
        Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: 1,
        })
    );
}

#[test]
fn test_vfs_error_display_and_traits() {
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

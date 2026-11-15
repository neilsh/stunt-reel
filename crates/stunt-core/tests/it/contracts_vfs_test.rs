//! `contracts::vfs` contract tests (Seam 1): archive format display and `[I8]` key normalisation.

use stunt_core::contracts::vfs::*;

#[test]
fn test_archive_format_display() {
    assert_eq!(ArchiveFormat::Res.to_string(), "RES");
    assert_eq!(ArchiveFormat::All.to_string(), "ALL");
}

#[test]
fn test_vfs_archive_case_normalization() {
    let mut archive = VfsArchive::new(ArchiveFormat::Res);
    let entry = VfsEntry {
        name: "fokker.sod".to_string(),
        data: vec![0x12, 0x34, 0x56],
        source_offset: 100,
        was_compressed: false,
    };
    archive.insert(entry);

    // Invariant [I8]: Keys must be normalized to uppercase and lookups case-insensitive
    assert!(archive.get("fokker.sod").is_some());
    assert!(archive.get("FOKKER.SOD").is_some());
    assert!(archive.get("Fokker.Sod").is_some());
    assert_eq!(
        archive.get_bytes("fokker.sod"),
        Some([0x12, 0x34, 0x56].as_slice())
    );
    assert_eq!(archive.get("nonexistent.sod"), None);
    assert_eq!(archive.get_bytes("nonexistent.sod"), None);

    let retrieved = archive.get("FOKKER.SOD").unwrap();
    assert_eq!(retrieved.name, "fokker.sod");
    assert_eq!(retrieved.source_offset, 100);
    assert!(!retrieved.was_compressed);
}

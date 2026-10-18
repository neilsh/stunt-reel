//! Seam 1: VFS Container Archive Contract
//!
//! Reference specs: `[fmt res]`, `[fmt all]`, `[R-VFS-01]`
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use std::collections::BTreeMap;
use std::fmt;

/// Declares the recognized physical archive container format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ArchiveFormat {
    /// Resource archive (`OBJECTS.RES`, `SCENERY1.RES`, `MAIN.RES`).
    /// Governed by `[fmt res]`.
    Res,
    /// Self-contained movie package (`INTRO.ALL`, `STUNT1.ALL`).
    /// Governed by `[fmt all]`.
    All,
}

impl fmt::Display for ArchiveFormat {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ArchiveFormat::Res => write!(f, "RES"),
            ArchiveFormat::All => write!(f, "ALL"),
        }
    }
}

/// Metadata and payload for an extracted archive entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VfsEntry {
    /// Normalized uppercase DOS 8.3 entry name per `[I8]`.
    pub name: String,
    /// Uncompressed payload byte buffer.
    pub data: Vec<u8>,
    /// Byte offset within the container file where payload begins.
    pub source_offset: u32,
    /// True if payload was stored compressed (e.g. LZSS) and decompressed.
    pub was_compressed: bool,
}

/// An unpacked, in-memory virtual filesystem archive.
///
/// Implements `Seam 1: VfsArchive` per `docs/ARCHITECTURE.md`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VfsArchive {
    /// The container format detected at ingest.
    pub format: ArchiveFormat,
    /// Map of uppercase DOS 8.3 filenames to their unpacked byte buffers.
    pub entries: BTreeMap<String, VfsEntry>,
}

impl VfsArchive {
    /// Creates an empty archive container.
    pub fn new(format: ArchiveFormat) -> Self {
        Self {
            format,
            entries: BTreeMap::new(),
        }
    }

    /// Retrieves an entry by its case-insensitive filename per `[I8]`.
    pub fn get(&self, filename: &str) -> Option<&VfsEntry> {
        let key = filename.to_ascii_uppercase();
        self.entries.get(&key)
    }

    /// Retrieves the raw byte slice for a file, if present.
    pub fn get_bytes(&self, filename: &str) -> Option<&[u8]> {
        self.get(filename).map(|e| e.data.as_slice())
    }

    /// Inserts an entry, ensuring the key is normalized to uppercase per `[I8]`.
    pub fn insert(&mut self, entry: VfsEntry) {
        let key = entry.name.to_ascii_uppercase();
        self.entries.insert(key, entry);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}

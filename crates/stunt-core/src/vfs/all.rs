//! Parser for `.ALL` full-movie archive containers.
//!
//! Reference specification: `# [FMT-ALL-CHUNKS]`, `[fmt all]`, `sires.cpp`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::vfs::VfsError;

/// Unpacks a `.ALL` container archive into an in-memory [`VfsArchive`].
///
/// # Layout (`# [FMT-ALL-CHUNKS]`)
/// - Bytes 0..2: 16-bit item count `num: u16` (little-endian)
/// - Bytes 2..(2 + 2*num): Array of `num` 16-bit resource IDs
/// - Bytes (2 + 2*num)..(2 + 6*num): Array of `num` 32-bit byte offsets
/// - Payload data: Entry $i$ bounded by `offsets[i]..offsets[i+1]` (or buffer length for final entry)
/// - Names generated based on payload header:
///   - `b"FILM"` -> `"CHOREO.FLM"`
///   - `0x000C` -> `format!("MODEL_{:04X}.SOD", id)`
///   - Otherwise -> `format!("RES_{:04X}.BIN", id)`
pub fn parse_all(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 2 {
        return Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: data.len(),
        });
    }

    let num = u16::from_le_bytes([data[0], data[1]]) as usize;
    if num == 0 {
        return Ok(VfsArchive::new(ArchiveFormat::All));
    }

    let header_size = 2 + num * 6;
    if data.len() < header_size {
        return Err(VfsError::UnexpectedEof {
            expected: header_size,
            actual: data.len(),
        });
    }

    let mut ids = Vec::with_capacity(num);
    for i in 0..num {
        let pos = 2 + i * 2;
        let id = u16::from_le_bytes([data[pos], data[pos + 1]]);
        ids.push(id);
    }

    let offsets_start = 2 + num * 2;
    let mut offsets = Vec::with_capacity(num);
    for i in 0..num {
        let pos = offsets_start + i * 4;
        let off =
            u32::from_le_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        offsets.push(off);
    }

    // Offset table integrity checks
    if offsets[0] < header_size {
        return Err(VfsError::InvalidOffsetTable {
            reason: format!(
                "first offset {} is inside header table (header size {})",
                offsets[0], header_size
            ),
        });
    }

    for &off in &offsets {
        if off > data.len() {
            return Err(VfsError::UnexpectedEof {
                expected: off,
                actual: data.len(),
            });
        }
    }

    for i in 0..num - 1 {
        if offsets[i + 1] < offsets[i] {
            return Err(VfsError::InvalidOffsetTable {
                reason: format!(
                    "offset at index {} ({}) is less than previous offset at index {} ({})",
                    i + 1,
                    offsets[i + 1],
                    i,
                    offsets[i]
                ),
            });
        }
    }

    let mut archive = VfsArchive::new(ArchiveFormat::All);
    for i in 0..num {
        let id = ids[i];
        let start = offsets[i];
        let end = if i + 1 < num {
            offsets[i + 1]
        } else {
            data.len()
        };

        let payload = &data[start..end];

        let name = if payload.len() >= 4 && &payload[0..4] == b"FILM" {
            "CHOREO.FLM".to_string()
        } else if payload.len() >= 2 && u16::from_le_bytes([payload[0], payload[1]]) == 0x000C {
            format!("MODEL_{id:04X}.SOD")
        } else {
            format!("RES_{id:04X}.BIN")
        };

        let entry = VfsEntry {
            name: name.to_ascii_uppercase(),
            data: payload.to_vec(),
            source_offset: start as u32,
            was_compressed: false,
        };
        archive.insert(entry);
    }

    Ok(archive)
}

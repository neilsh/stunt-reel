//! Parser for `.ALL` full-movie archive containers.
//!
//! Reference specification: `# [FMT-ALL-CHUNKS]`, `[fmt all]`, `sires.cpp`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::reader::ByteReader;
use crate::vfs::{VfsError, check_non_decreasing};

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
///
/// # Errors
/// - [`VfsError::UnexpectedEof`] if `data` is shorter than the 2-byte count or the
///   `2 + 6*num`-byte header, or an offset points past the end of `data`.
/// - [`VfsError::InvalidOffsetTable`] if the first offset lies inside the header or the
///   offsets are not non-decreasing.
pub fn parse_all(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 2 {
        return Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: data.len(),
        });
    }

    let mut head = ByteReader::new(data);
    let num = head.read_u16_le()? as usize;
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
    for _ in 0..num {
        ids.push(head.read_u16_le()?);
    }

    let mut offsets = Vec::with_capacity(num);
    for _ in 0..num {
        offsets.push(head.read_u32_le()? as usize);
    }

    // Offset table integrity checks
    if let Some(&first) = offsets.first()
        && first < header_size
    {
        return Err(VfsError::InvalidOffsetTable {
            reason: format!(
                "first offset {first} is inside header table (header size {header_size})"
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

    check_non_decreasing(&offsets)?;

    let mut archive = VfsArchive::new(ArchiveFormat::All);
    let ends = offsets.iter().skip(1).copied().chain([data.len()]);
    for ((&id, &start), end) in ids.iter().zip(&offsets).zip(ends) {
        // Bounds and order were checked above, so this only fails on a broken invariant.
        let payload = data.get(start..end).ok_or(VfsError::UnexpectedEof {
            expected: end,
            actual: data.len(),
        })?;

        let name = if payload.starts_with(b"FILM") {
            "CHOREO.FLM".to_string()
        } else if let &[lo, hi, ..] = payload
            && u16::from_le_bytes([lo, hi]) == 0x000C
        {
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

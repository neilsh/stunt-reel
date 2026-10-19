//! Parser for `.RES` archive containers.
//!
//! Reference specification: `# [FMT-RES-HEADER]`, `[fmt res]`, `RIPRES.C`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::vfs::VfsError;

/// Unpacks a `.RES` container archive into an in-memory [`VfsArchive`].
///
/// # Layout (`# [FMT-RES-HEADER]`)
/// - Bytes 0..2: 2-byte magic signature `b"RS"` (`0x52, 0x53`)
/// - Bytes 2..4: 16-bit version word (little-endian)
/// - Bytes 4..8: 32-bit `ofs[0]` (little-endian), pointing to Name Table / end of offset table
/// - Offset table: $N = (ofs[0] / 4) - 1$ entries of 32-bit offsets `ofs[0] .. ofs[N-1]`
/// - Name table: null-separated ASCII strings between `ofs[0]` and `ofs[1]`
/// - Entry $i$ payload: `data[ofs[i+1]..ofs[i+2]]`
/// - If Name Table is omitted or empty, names default to `format!("{:04X}.BIN", i)`
pub fn parse_res(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 8 {
        return Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: data.len(),
        });
    }

    if &data[0..2] != b"RS" {
        return Err(VfsError::InvalidMagic {
            expected: "RS",
            actual: [data[0], data[1]],
        });
    }

    let _version = u16::from_le_bytes([data[2], data[3]]);
    let ofs0 = u32::from_le_bytes([data[4], data[5], data[6], data[7]]) as usize;

    if ofs0 < 8 {
        return Err(VfsError::InvalidOffsetTable {
            reason: format!("ofs[0] ({ofs0}) must be >= 8"),
        });
    }

    if ofs0 > data.len() {
        return Err(VfsError::UnexpectedEof {
            expected: ofs0,
            actual: data.len(),
        });
    }

    if !ofs0.is_multiple_of(4) {
        return Err(VfsError::InvalidOffsetTable {
            reason: format!("ofs[0] ({ofs0}) is not 4-byte aligned"),
        });
    }

    let n = (ofs0 / 4) - 1;
    if n < 2 {
        // Table does not have enough offsets to define both name table and payloads
        return Ok(VfsArchive::new(ArchiveFormat::Res));
    }

    let mut offsets = Vec::with_capacity(n);
    for i in 0..n {
        let pos = 4 + i * 4;
        let off =
            u32::from_le_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        offsets.push(off);
    }

    // Offset table integrity checks
    for &off in &offsets {
        if off > data.len() {
            return Err(VfsError::UnexpectedEof {
                expected: off,
                actual: data.len(),
            });
        }
    }

    for i in 0..n - 1 {
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

    // Parse Name Table between ofs[0] and ofs[1]
    let name_start = offsets[0];
    let name_end = offsets[1];
    let name_slice = &data[name_start..name_end];

    let mut names = Vec::new();
    let mut current_name = Vec::new();
    let mut has_non_ascii = false;

    for &b in name_slice {
        if b == 0 {
            if !current_name.is_empty() {
                if let Ok(s) = std::str::from_utf8(&current_name) {
                    names.push(s.to_string());
                } else {
                    has_non_ascii = true;
                    break;
                }
                current_name.clear();
            }
        } else if b.is_ascii_graphic() || b == b' ' {
            current_name.push(b);
        } else {
            has_non_ascii = true;
            break;
        }
    }

    if !current_name.is_empty()
        && !has_non_ascii
        && let Ok(s) = std::str::from_utf8(&current_name)
    {
        names.push(s.to_string());
    }

    if has_non_ascii {
        names.clear();
    }

    let mut archive = VfsArchive::new(ArchiveFormat::Res);
    let payload_count = n - 2;

    for i in 0..payload_count {
        let start = offsets[i + 1];
        let end = offsets[i + 2];
        let payload = &data[start..end];

        let name = if let Some(raw_name) = names.get(i) {
            let trimmed = raw_name.trim();
            if trimmed.is_empty() {
                format!("{i:04X}.BIN")
            } else {
                trimmed.to_ascii_uppercase()
            }
        } else {
            format!("{i:04X}.BIN")
        };

        let entry = VfsEntry {
            name,
            data: payload.to_vec(),
            source_offset: start as u32,
            was_compressed: false,
        };
        archive.insert(entry);
    }

    Ok(archive)
}

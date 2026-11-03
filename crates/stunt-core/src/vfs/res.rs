//! Parser for `.RES` archive containers.
//!
//! Reference specification: `# [FMT-RES-HEADER]`, `[fmt res]`, `RIPRES.C`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::reader::ByteReader;
use crate::vfs::{VfsError, check_non_decreasing};

/// Unpacks a `.RES` container archive into an in-memory [`VfsArchive`].
///
/// # Layout (`# [FMT-RES-HEADER]`)
/// The byte layout is defined by `research/formats/res.ksy` (magic `b"RS"`, `res_index: u8`,
/// `item_count: u8`, `ofs[0]: u32`, offset table); this comment does not restate it.
///
/// # Parser policy
/// - Only `ofs[0]` and the offset table are trusted: it must be at least 8, 4-byte aligned,
///   and the table holds $N = (ofs\[0\] / 4) - 1$ non-decreasing offsets. The header bytes at
///   `0x0002..0x0004` (`res_index`, `item_count`) are not read.
/// - Region 0 (`data[ofs[0]..ofs[1]]`) is treated as the null-separated ASCII name table.
/// - Entry $i$ payload: `data[ofs[i+1]..ofs[i+2]]`
/// - If the name table is omitted or not ASCII, names default to `format!("{:04X}.BIN", i)`
///
/// # Errors
/// - [`VfsError::UnexpectedEof`] if `data` is shorter than 8 bytes, `ofs[0]` or any table
///   offset points past the end of `data`, or the offset table is cut short.
/// - [`VfsError::InvalidMagic`] if `data` does not begin with `b"RS"`.
/// - [`VfsError::InvalidOffsetTable`] if `ofs[0]` is below 8 or not 4-byte aligned, or the
///   offsets are not non-decreasing.
pub fn parse_res(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 8 {
        return Err(VfsError::UnexpectedEof {
            expected: 8,
            actual: data.len(),
        });
    }

    if let &[m0, m1, ..] = data
        && [m0, m1] != *b"RS"
    {
        return Err(VfsError::InvalidMagic {
            expected: "RS",
            actual: [m0, m1],
        });
    }

    let mut head = ByteReader::at(data, 2);
    let _version = head.read_u16_le()?;
    let ofs0 = head.read_u32_le()? as usize;

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
    let mut table = ByteReader::at(data, 4);
    for _ in 0..n {
        offsets.push(table.read_u32_le()? as usize);
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

    check_non_decreasing(&offsets)?;

    // Region 0 (ofs[0]..ofs[1]) is the name table; each later region is one payload.
    // Bounds and order were checked above, so `region` only fails on a broken invariant.
    let region = |(&start, &end): (&usize, &usize)| {
        data.get(start..end)
            .map(|bytes| (start, bytes))
            .ok_or(VfsError::UnexpectedEof {
                expected: end,
                actual: data.len(),
            })
    };
    let mut regions = offsets.iter().zip(offsets.iter().skip(1)).map(region);
    let Some(name_region) = regions.next() else {
        return Ok(VfsArchive::new(ArchiveFormat::Res));
    };
    let (_, name_slice) = name_region?;

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

    for (i, payload) in regions.enumerate() {
        let (start, payload) = payload?;

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

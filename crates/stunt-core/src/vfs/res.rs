//! Parser for `.RES` archive containers.
//!
//! Reference specification: `# [FMT-RES-HEADER]`, `[fmt res]`, `RIPRES.C`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::reader::ByteReader;
use crate::vfs::{VfsError, check_non_decreasing, offset_u32};

/// The raw split of a `.RES` container: its `res_index` and every data region.
///
/// Region 0 is kept: a prop archive's name table, or a scenery archive's first payload.
/// Item `n` of the archive, in the sense of a `.ALL` chunk id, is region `n - 1`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResRegions<'a> {
    /// Byte `0x0002` of the file (`res_index` in `research/formats/res.ksy`).
    pub index: u8,
    /// `data[ofs[i]..ofs[i+1]]` for every adjacent pair of table offsets, in table order.
    pub regions: Vec<&'a [u8]>,
}

/// Splits a `.RES` container into its `res_index` and raw data regions.
///
/// Applies the header and offset-table checks of [`parse_res`] and nothing else: no region
/// is named or classified. A table with fewer than two offsets yields no regions.
///
/// # Errors
/// The same as [`parse_res`].
pub fn res_regions(data: &[u8]) -> Result<ResRegions<'_>, VfsError> {
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
    let index = head.read_u8()?;
    let _item_count = head.read_u8()?;
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
        // Table does not have enough offsets to bound a single region
        return Ok(ResRegions {
            index,
            regions: Vec::new(),
        });
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

    // Bounds and order were checked above, so `get` only fails on a broken invariant.
    let regions = offsets
        .iter()
        .zip(offsets.iter().skip(1))
        .map(|(&start, &end)| {
            data.get(start..end).ok_or(VfsError::UnexpectedEof {
                expected: end,
                actual: data.len(),
            })
        })
        .collect::<Result<Vec<_>, _>>()?;

    Ok(ResRegions { index, regions })
}

/// Unpacks a `.RES` container archive into an in-memory [`VfsArchive`].
///
/// # Layout (`# [FMT-RES-HEADER]`)
/// The byte layout is defined by `research/formats/res.ksy` (magic `b"RS"`, `res_index: u8`,
/// `item_count: u8`, `ofs[0]: u32`, offset table); this comment does not restate it.
///
/// # Parser policy
/// - Only `ofs[0]` and the offset table are trusted: it must be at least 8, 4-byte aligned,
///   and the table holds $N = (ofs\[0\] / 4) - 1$ non-decreasing offsets, checked by [`res_regions`]. The
///   header bytes at `0x0002..0x0004` (`res_index`, `item_count`) are not used.
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
    let split = res_regions(data)?;
    // Region 0 is the name table; each later region is one payload. Regions are contiguous
    // from ofs[0], which the split has already checked.
    let Some((&name_slice, payloads)) = split.regions.split_first() else {
        return Ok(VfsArchive::new(ArchiveFormat::Res));
    };
    let mut start = ByteReader::at(data, 4).read_u32_le()? as usize + name_slice.len();

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

    for (i, &payload) in payloads.iter().enumerate() {
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
            source_offset: offset_u32(start)?,
            was_compressed: false,
        };
        start += payload.len();
        archive.insert(entry);
    }

    Ok(archive)
}

//! Parser for `.ALL` full-movie archive containers.
//!
//! Reference specification: `# [FMT-ALL-CHUNKS]`, `[fmt all]`, `sires.cpp`.
//! Governed by architectural invariant:
//! - `[I8]` Uppercase DOS 8.3 filename normalization

use crate::contracts::vfs::{ArchiveFormat, VfsArchive, VfsEntry};
use crate::reader::ByteReader;
use crate::vfs::{VfsError, check_non_decreasing, offset_add, offset_sub, offset_u32};

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
/// - [`VfsError::InvalidOffsetTable`] if the first offset lies inside the header, the
///   offsets are not non-decreasing, or a payload starts past `u32::MAX`.
pub fn parse_all(data: &[u8]) -> Result<VfsArchive, VfsError> {
    let chunks = all_chunks(data)?;
    // Payloads are contiguous and the last runs to the end of `data`.
    let mut start = offset_sub(
        data.len(),
        chunks.iter().map(|(_, p)| p.len()).sum::<usize>(),
    )?;

    let mut archive = VfsArchive::new(ArchiveFormat::All);
    for (id, payload) in chunks {
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
            source_offset: offset_u32(start)?,
            was_compressed: false,
        };
        start = offset_add(start, payload.len())?;
        archive.insert(entry);
    }

    Ok(archive)
}

/// Splits a `.ALL` container into its chunk ids and payloads, in file order.
///
/// Applies the header and offset-table checks of [`parse_all`] and nothing else. Only the
/// first `num` offsets are read; the last payload runs to the end of `data`, so the sentinel
/// offset a complete archive carries is not trusted.
///
/// # Errors
/// The same as [`parse_all`].
pub fn all_chunks(data: &[u8]) -> Result<Vec<(u16, &[u8])>, VfsError> {
    if data.len() < 2 {
        return Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: data.len(),
        });
    }

    let mut head = ByteReader::new(data);
    let num = head.read_u16_le()? as usize;
    if num == 0 {
        return Ok(Vec::new());
    }

    let header_size = num
        .checked_mul(6)
        .and_then(|n| n.checked_add(2))
        .ok_or_else(|| VfsError::InvalidOffsetTable {
            reason: format!("header of {num} entries overflows"),
        })?;
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

    let ends = offsets.iter().skip(1).copied().chain([data.len()]);
    ids.iter()
        .zip(&offsets)
        .zip(ends)
        .map(|((&id, &start), end)| {
            // Bounds and order were checked above, so this only fails on a broken invariant.
            let payload = data.get(start..end).ok_or(VfsError::UnexpectedEof {
                expected: end,
                actual: data.len(),
            })?;
            Ok((id, payload))
        })
        .collect()
}

/// Packs chunks into a `.ALL` archive, the inverse of [`all_chunks`] for an intact archive.
///
/// Chunks are written in ascending id order whatever their input order: the count, the ids,
/// `num + 1` offsets (the last is the end of the file), then the payloads with no padding,
/// so the header is `6 * num + 6` bytes (`research/makeone-exe/linking.md` § 3).
///
/// # Errors
/// - [`VfsError::DuplicateId`] if two chunks share an id.
/// - [`VfsError::InvalidOffsetTable`] if there are more than `u16::MAX` chunks or an offset
///   would pass `u32::MAX`.
pub fn write_all(chunks: &[(u16, &[u8])]) -> Result<Vec<u8>, VfsError> {
    let mut sorted = chunks.to_vec();
    sorted.sort_by_key(|&(id, _)| id);
    if let Some(pair) = sorted
        .windows(2)
        .find(|w| matches!(w, [a, b] if a.0 == b.0))
        && let Some(&(id, _)) = pair.first()
    {
        return Err(VfsError::DuplicateId { id });
    }

    let count = u16::try_from(sorted.len()).map_err(|_| VfsError::InvalidOffsetTable {
        reason: format!("{} chunks exceed the u16 count", sorted.len()),
    })?;
    // `sorted.len()` fits u16 (checked above), so the product never clamps.
    let header = offset_add(sorted.len().saturating_mul(6), 6)?;
    let total = sorted
        .iter()
        .try_fold(header, |sum, (_, payload)| offset_add(sum, payload.len()))?;
    if u32::try_from(total).is_err() {
        return Err(VfsError::InvalidOffsetTable {
            reason: format!("archive of {total} bytes passes the u32 offset range"),
        });
    }

    let mut out = Vec::with_capacity(total);
    out.extend_from_slice(&count.to_le_bytes());
    for &(id, _) in &sorted {
        out.extend_from_slice(&id.to_le_bytes());
    }
    let mut offset = header;
    for &(_, payload) in &sorted {
        out.extend_from_slice(&offset_u32(offset)?.to_le_bytes());
        offset = offset_add(offset, payload.len())?;
    }
    out.extend_from_slice(&offset_u32(offset)?.to_le_bytes());
    for &(_, payload) in &sorted {
        out.extend_from_slice(payload);
    }
    Ok(out)
}

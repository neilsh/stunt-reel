//! Virtual File System (VFS) archive container parsers.
//!
//! Provides extraction logic for `.RES` and `.ALL` archive containers into
//! in-memory [`VfsArchive`] instances adhering to Seam 1 and Invariant `[I8]`.

mod all;
mod res;

pub use all::{all_chunks, chunk_name, parse_all, write_all};
pub use res::{ResRegions, parse_res, res_regions};

use crate::contracts::vfs::VfsArchive;

/// Errors that can occur during VFS container archive extraction.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum VfsError {
    /// The input buffer was smaller than expected for reading a header or table.
    #[error("unexpected EOF: expected at least {expected} bytes, found {actual}")]
    UnexpectedEof {
        /// Buffer length the parse required at the failure point.
        expected: usize,
        /// Buffer length actually available.
        actual: usize,
    },
    /// Magic signature mismatch (e.g. not `b"RS"` for `.RES` files).
    #[error("invalid container magic: expected {expected:?}, found [0x{:02X}, 0x{:02X}]", .actual[0], .actual[1])]
    InvalidMagic {
        /// Signature the parser expected (e.g. `"RS"`).
        expected: &'static str,
        /// First two bytes found in the stream.
        actual: [u8; 2],
    },
    /// The offset table contains out-of-bounds, unaligned, or non-monotonic values.
    #[error("invalid offset table: {reason}")]
    InvalidOffsetTable {
        /// Human-readable description of the offending table entry.
        reason: String,
    },
    /// The requested entry was not found in the archive.
    #[error("entry not found: {name}")]
    EntryNotFound {
        /// Requested DOS 8.3 entry name, normalized per `[I8]`.
        name: String,
    },
    /// The payload could not be extracted due to size or offset corruption.
    #[error("corrupted payload for entry '{name}' at offset {offset} (len {len})")]
    CorruptedPayload {
        /// Entry name whose payload could not be extracted.
        name: String,
        /// Byte offset of the payload within the archive.
        offset: usize,
        /// Payload length in bytes.
        len: usize,
    },
    /// Two chunks given to [`write_all`] share an id.
    #[error("duplicate chunk id 0x{id:04X}")]
    DuplicateId {
        /// The repeated chunk id.
        id: u16,
    },
}

/// Automatically detects container type and parses the input buffer.
///
/// If `data` begins with `b"RS"`, delegates to [`parse_res`]. Otherwise delegates to [`parse_all`].
///
/// # Errors
/// Returns [`VfsError::UnexpectedEof`] if `data` is shorter than 2 bytes, and otherwise
/// whatever the chosen parser returns.
pub fn detect_and_parse(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 2 {
        return Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: data.len(),
        });
    }

    if data.starts_with(b"RS") {
        parse_res(data)
    } else {
        parse_all(data)
    }
}

/// A byte offset into an archive as the `u32` its offset table and [`VfsEntry`] store.
///
/// [`VfsEntry`]: crate::contracts::VfsEntry
///
/// # Errors
/// [`VfsError::InvalidOffsetTable`] when the offset passes the `u32` range.
fn offset_u32(offset: usize) -> Result<u32, VfsError> {
    u32::try_from(offset).map_err(|_| VfsError::InvalidOffsetTable {
        reason: format!("offset {offset} passes the u32 range"),
    })
}

/// Adds two byte counts, failing with [`VfsError::InvalidOffsetTable`] on `usize` overflow.
fn offset_add(a: usize, b: usize) -> Result<usize, VfsError> {
    a.checked_add(b)
        .ok_or_else(|| VfsError::InvalidOffsetTable {
            reason: format!("offset {a} + {b} overflows"),
        })
}

/// Subtracts two byte counts, failing with [`VfsError::InvalidOffsetTable`] on underflow.
fn offset_sub(a: usize, b: usize) -> Result<usize, VfsError> {
    a.checked_sub(b)
        .ok_or_else(|| VfsError::InvalidOffsetTable {
            reason: format!("offset {a} - {b} underflows"),
        })
}

/// Fails with [`VfsError::InvalidOffsetTable`] at the first offset smaller than the one before it.
fn check_non_decreasing(offsets: &[usize]) -> Result<(), VfsError> {
    for (i, pair) in offsets.windows(2).enumerate() {
        if let &[prev, next] = pair
            && next < prev
        {
            return Err(VfsError::InvalidOffsetTable {
                reason: format!(
                    "offset at index {} ({next}) is less than previous offset at index {i} ({prev})",
                    i.saturating_add(1)
                ),
            });
        }
    }
    Ok(())
}

impl From<crate::reader::Eof> for VfsError {
    fn from(e: crate::reader::Eof) -> Self {
        Self::UnexpectedEof {
            expected: e.expected,
            actual: e.actual,
        }
    }
}

//! Virtual File System (VFS) archive container parsers.
//!
//! Provides extraction logic for `.RES` and `.ALL` archive containers into
//! in-memory [`VfsArchive`] instances adhering to Seam 1 and Invariant `[I8]`.

mod all;
mod res;

pub use all::parse_all;
pub use res::parse_res;

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
}

/// Automatically detects container type and parses the input buffer.
///
/// If `data` begins with `b"RS"`, delegates to [`parse_res`]. Otherwise delegates to [`parse_all`].
pub fn detect_and_parse(data: &[u8]) -> Result<VfsArchive, VfsError> {
    if data.len() < 2 {
        return Err(VfsError::UnexpectedEof {
            expected: 2,
            actual: data.len(),
        });
    }

    if &data[0..2] == b"RS" {
        parse_res(data)
    } else {
        parse_all(data)
    }
}

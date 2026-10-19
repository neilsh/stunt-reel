//! Virtual File System (VFS) archive container parsers.
//!
//! Provides extraction logic for `.RES` and `.ALL` archive containers into
//! in-memory [`VfsArchive`] instances adhering to Seam 1 and Invariant `[I8]`.

mod all;
mod res;

pub use all::parse_all;
pub use res::parse_res;

use crate::contracts::vfs::VfsArchive;
use std::fmt;

/// Errors that can occur during VFS container archive extraction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VfsError {
    /// The input buffer was smaller than expected for reading a header or table.
    UnexpectedEof { expected: usize, actual: usize },
    /// Magic signature mismatch (e.g. not `b"RS"` for `.RES` files).
    InvalidMagic {
        expected: &'static str,
        actual: [u8; 2],
    },
    /// The offset table contains out-of-bounds, unaligned, or non-monotonic values.
    InvalidOffsetTable { reason: String },
    /// The requested entry was not found in the archive.
    EntryNotFound { name: String },
    /// The payload could not be extracted due to size or offset corruption.
    CorruptedPayload {
        name: String,
        offset: usize,
        len: usize,
    },
}

impl fmt::Display for VfsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            VfsError::UnexpectedEof { expected, actual } => {
                write!(
                    f,
                    "unexpected EOF: expected at least {expected} bytes, found {actual}"
                )
            }
            VfsError::InvalidMagic { expected, actual } => {
                write!(
                    f,
                    "invalid container magic: expected {expected:?}, found [0x{:02X}, 0x{:02X}]",
                    actual[0], actual[1]
                )
            }
            VfsError::InvalidOffsetTable { reason } => {
                write!(f, "invalid offset table: {reason}")
            }
            VfsError::EntryNotFound { name } => {
                write!(f, "entry not found: {name}")
            }
            VfsError::CorruptedPayload { name, offset, len } => {
                write!(
                    f,
                    "corrupted payload for entry '{name}' at offset {offset} (len {len})"
                )
            }
        }
    }
}

impl std::error::Error for VfsError {}

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

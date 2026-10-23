//! Procedural `.SOD` display-list geometry transpiler.
//!
//! Provides transpilation from raw `.SOD` bytecode into arena-allocated [`crate::contracts::shape::SodModelIr`]
//! instances adhering to Seam 3 and Invariants `[I1]`, `[I2]`, `[I3]`, `[I5]`.

mod decal;
mod tessellate;
mod vm;

#[cfg(test)]
mod decal_tests;
#[cfg(test)]
mod tessellate_tests;
#[cfg(test)]
mod vm_tests;

pub use decal::{DECAL_FLAG_BIT, EPSILON_DISPLACEMENT};
pub use tessellate::{IDENTITY_MATRIX, transpile_sod, transpile_sod_lenient};
pub use vm::{
    OP_ADDV, OP_BLOCK, OP_CLRV, OP_COLOR, OP_DOT, OP_END, OP_GETV, OP_GVPOLY, OP_GVPOLY16, OP_ID,
    OP_IFVIS, OP_INTV, OP_IPG, OP_LINECOL, OP_MOVETO, OP_NEGV, OP_PERFDISK, OP_PERS, OP_POLYZ,
    OP_PUTV, OP_REJ, OP_RETURN, OP_SHADE16, OP_SHADES, OP_SHLV, OP_SHRV, OP_SORT, OP_SPHERE,
    OP_SUBV, OP_TAP, OP_VEC, OP_VECTORS, OP_ZLINETO, SOD_SCALE_TABLE, SodHeader, SodStop,
    SodStopReason, compute_scale_factor,
};

use std::fmt;

/// Errors that can occur during .SOD display-list parsing or transpilation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SodError {
    /// The input buffer was smaller than expected for reading a header or opcode payload.
    UnexpectedEof {
        /// Buffer length the decode required at the failure point.
        expected: usize,
        /// Buffer length actually available.
        actual: usize,
    },
    /// Magic signature mismatch (expected `0x000C`).
    InvalidMagic {
        /// Opcode word the parser expected as the header sentinel.
        expected: u16,
        /// Opcode word found instead.
        actual: u16,
    },
    /// Unrecognized or invalid opcode in the bytecode stream.
    InvalidOpcode {
        /// Opcode word outside the decoded table.
        opcode: u16,
        /// Byte offset of the opcode within the model payload.
        offset: usize,
    },
    /// A polygon was malformed (e.g. fewer than 3 vertices or corrupted structure).
    MalformedPolygon {
        /// Human-readable description of the malformed polygon.
        reason: String,
    },
    /// An opcode carried operands that violate the established encoding.
    MalformedOpcode {
        /// Opcode whose operands failed validation.
        opcode: u16,
        /// Byte offset of the opcode within the model payload.
        offset: usize,
        /// Human-readable description of the invalid operand.
        reason: String,
    },
    /// `OP_TAP` was reached without a usable anchor table.
    MissingAnchors {
        /// Opcode that requires the anchor table.
        opcode: u16,
        /// Byte offset of the opcode within the model payload.
        offset: usize,
    },
}

impl fmt::Display for SodError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnexpectedEof { expected, actual } => {
                write!(
                    f,
                    "unexpected EOF: expected at least {expected} bytes, found {actual}"
                )
            }
            Self::InvalidMagic { expected, actual } => {
                write!(
                    f,
                    "invalid SOD magic identifier: expected 0x{expected:04X}, found 0x{actual:04X}"
                )
            }
            Self::InvalidOpcode { opcode, offset } => {
                write!(
                    f,
                    "invalid SOD opcode 0x{opcode:04X} at byte offset 0x{offset:04X}"
                )
            }
            Self::MalformedPolygon { reason } => {
                write!(f, "malformed polygon: {reason}")
            }
            Self::MalformedOpcode {
                opcode,
                offset,
                reason,
            } => write!(
                f,
                "malformed SOD opcode 0x{opcode:04X} at byte offset 0x{offset:04X}: {reason}"
            ),
            Self::MissingAnchors { opcode, offset } => write!(
                f,
                "SOD opcode 0x{opcode:04X} at byte offset 0x{offset:04X} requires an anchor table"
            ),
        }
    }
}

impl std::error::Error for SodError {}

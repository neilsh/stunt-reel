//! Procedural `.SOD` display-list geometry transpiler.
//!
//! Provides transpilation from raw `.SOD` bytecode into arena-allocated [`crate::contracts::scene::SodModelIr`]
//! instances adhering to Seam 3 and Invariants `[I1]`, `[I2]`, `[I3]`, `[I5]`.

pub mod decal;
pub mod tessellate;
pub mod vm;

pub use decal::{
    DECAL_FLAG_BIT, EPSILON_DISPLACEMENT, apply_decal_displacement, identify_coplanar_decals,
};
pub use tessellate::{
    IDENTITY_MATRIX, WeldKey, build_sod_model_ir, quantize_weld_key, transpile_sod,
};
pub use vm::{RawPolygon, SOD_SCALE_TABLE, SodHeader, compute_scale_factor, execute_sod_vm};

use std::fmt;

/// Errors that can occur during .SOD display-list parsing or transpilation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SodError {
    /// The input buffer was smaller than expected for reading a header or opcode payload.
    UnexpectedEof { expected: usize, actual: usize },
    /// Magic signature mismatch (expected `0x000C`).
    InvalidMagic { expected: u16, actual: u16 },
    /// Unrecognized or invalid opcode in the bytecode stream.
    InvalidOpcode { opcode: u16, offset: usize },
    /// A polygon was malformed (e.g. fewer than 3 vertices or corrupted structure).
    MalformedPolygon { reason: String },
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
        }
    }
}

impl std::error::Error for SodError {}

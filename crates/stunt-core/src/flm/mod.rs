//! Native `.FLM` choreography evaluator and its oracle-trajectory check.
//!
//! Evaluates binary `.FLM` film streams into [`crate::contracts::trajectory::TrajectoryRecord`]
//! time-series streams adhering to Seam 2 and Invariants `[I1]`, `[I4]`.
//!
//! Slots are authored in DOS axes (GLOSSARY.md); [`SlotState::position_meters`],
//! [`SlotState::rotation_quat`] (the view) and [`SlotState::actor_rotation_quat`] (drawn
//! shapes) convert them to `[I1]`, so every evaluated record, camera included, is already
//! `[I1]` and consumers apply no further axis heuristic.

mod interpolate;
mod oracle;
mod player;
mod timeline;

pub use oracle::{GATE_G04_RMSE_THRESHOLD_METERS, compute_position_rmse};
pub use player::{
    SIF_ANIMATES, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SIF_SHADOW, SIFILM_MAX_OBJ,
    SlotState,
};
pub use timeline::{FilmTimeline, SliceKeyframe, TIMELINE_HZ, TIMELINE_TICK_SECONDS};

/// Camera-space viewing axis that the film's view-slot rotation maps into world space.
///
/// `.FLM` stores each slot's orientation as BAM angles whose rotation maps camera space
/// to world space with `+Z` pointing into the screen, so rotating `+Z` by the view slot's
/// `[I1]` quaternion yields the `[I1]` look direction (research/formats/concepts/coordinates-and-units.md). That equals
/// the DOS-axes look direction with the (-x, -y, z) map applied, because the quaternion
/// already carries `q_z180` ([`SlotState::rotation_quat`]).
pub const CAMERA_FORWARD: [f32; 3] = [0.0, 0.0, 1.0];

/// Distance in meters from the view slot to its look-at point.
///
/// The film stream stores view orientation as a BAM rotation with no range, so the
/// camera target is an arbitrary point along the rotated forward axis.
pub const CAMERA_LOOKAHEAD_METERS: f32 = 1000.0;

/// Errors that can occur during `.FLM` choreography parsing and evaluation.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FlmError {
    /// Magic signature mismatch (expected `b"FILM"`).
    #[error("invalid FILM signature: expected {:?}, found {:?}", .expected.map(|b| b as char), .actual.map(|b| b as char))]
    InvalidSignature {
        /// Signature the parser expected (`b"FILM"`).
        expected: [u8; 4],
        /// Signature bytes found in the stream.
        actual: [u8; 4],
    },
    /// The input buffer was smaller than expected.
    #[error("unexpected EOF: expected at least {expected} bytes, found {actual}")]
    UnexpectedEof {
        /// Buffer length the parse required at the failure point.
        expected: usize,
        /// Buffer length actually available.
        actual: usize,
    },
    /// Malformed time slice or unexpected termination.
    #[error("invalid slice: {reason}")]
    InvalidSlice {
        /// Human-readable description of the malformed slice.
        reason: String,
    },
    /// Unrecognized or invalid opcode in the slice stream.
    #[error("invalid FLM opcode 0x{opcode:02X} at byte offset 0x{offset:04X}")]
    InvalidOpcode {
        /// Opcode byte outside the decoded table.
        opcode: u8,
        /// Byte offset of the opcode within the file.
        offset: usize,
    },
}

impl From<crate::reader::Eof> for FlmError {
    fn from(e: crate::reader::Eof) -> Self {
        Self::UnexpectedEof {
            expected: e.expected,
            actual: e.actual,
        }
    }
}

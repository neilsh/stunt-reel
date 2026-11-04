//! Asset-isolated contracts, parsers, and bytecode VM for *Stunt Island* assets.
//!
//! The crate exposes the four seam contracts (VFS, trajectory, scene graph, parity) plus
//! binary parsers for the `.res`, `.flm`, and `.sod` formats. Every type obeys the system
//! invariants `[I1]`-`[I8]` documented in [`contracts`].

// Not in the workspace lint table: a manifest with `[lints] workspace = true` cannot override
// one lint (Cargo.toml, #162). Offsets and counts read from game files use `checked_*`; bounded
// maths kernels carry an `#[expect]` with the reason.
#![warn(clippy::arithmetic_side_effects)]

pub mod anchor;
pub mod contracts;
pub mod credits;
pub mod flm;
pub mod font;
pub mod link;
pub mod reader;
pub mod scene;
pub mod sod;
pub mod vfs;
pub mod world;

pub use reader::{ByteReader, Eof};

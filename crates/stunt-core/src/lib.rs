//! Cleanroom contracts, parsers, and bytecode VM for *Stunt Island* assets.
//!
//! The crate exposes the four seam contracts (VFS, trajectory, scene graph, parity) plus
//! binary parsers for the `.res`, `.flm`, and `.sod` formats. Every type obeys the system
//! invariants `[I1]`-`[I8]` documented in [`contracts`].
#![deny(unsafe_code)]
#![warn(missing_docs)]

pub mod anchor;
pub mod contracts;
pub mod flm;
pub mod scene;
pub mod sod;
pub mod vfs;
pub mod world;

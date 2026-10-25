//! StuntReel Core Seam Contracts (`crates/stunt-core/src/contracts/mod.rs`)
//!
//! This module defines the immutable type contracts and testing seams
//! establishing the boundary between:
//! - Container extraction (`Seam 1: VfsArchive`)
//! - Flight choreography & trajectory playback (`Seam 2: TrajectoryRecord`)
//! - Shape IR: one decoded `.SOD` shape as a flat node arena (`Seam 3: SodModelIr`)
//! - Visual presentation & parity evaluation (`Seam 4: VisualParityGate`); it has no core
//!   types: the palette side is [`palette`], frames are rendered by `stunt-render`, and the
//!   capture-vs-render report is the `stuntreel parity` subcommand
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I3]` Fixed VGA Mode 13h palette index color correspondence
//! - `[I4]` Decoupled fixed simulation ticks (50 Hz) with sub-tick interpolation
//! - `[I5]` Coplanar decal identification and normal displacement rules
//! - `[I6]` Visual parity acceptance thresholds (SSIM >= 0.88 / 0.90)
//! - `[I7]` Asset isolation and a core limited to small, pure-Rust dependencies (no I/O, windowing, GPU, audio or emulator)
//! - `[I8]` Uppercase DOS 8.3 filename normalization
//!
//! Definitions: `docs/SPEC.md`; the heading for each token is registered in
//! `python/stunt_reel/doc_anchors.py`.

pub mod palette;
pub mod shape;
pub mod trajectory;
pub mod vfs;

pub use palette::*;
pub use shape::*;
pub use trajectory::*;
pub use vfs::*;

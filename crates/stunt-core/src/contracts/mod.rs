//! StuntReel Core Seam Contracts (`crates/stunt-core/src/contracts/mod.rs`)
//!
//! This module defines the immutable type contracts and testing seams
//! establishing the boundary between:
//! - Container extraction (`Seam 1: VfsArchive`)
//! - Flight choreography & trajectory playback (`Seam 2: TrajectoryRecord`)
//! - Procedural display-list scene graph IR (`Seam 3: SodModelIr`)
//! - Visual presentation & parity evaluation (`Seam 4: VisualParityGate`)
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I3]` Fixed VGA Mode 13h palette index color correspondence
//! - `[I4]` Decoupled fixed simulation ticks (20/30 Hz) with sub-tick interpolation
//! - `[I5]` Coplanar decal identification and normal displacement rules
//! - `[I6]` Visual parity acceptance thresholds (SSIM >= 0.88 / 0.90)
//! - `[I8]` Uppercase DOS 8.3 filename normalization

pub mod palette;
pub mod parity;
pub mod scene;
pub mod trajectory;
pub mod vfs;

pub use palette::*;
pub use parity::*;
pub use scene::*;
pub use trajectory::*;
pub use vfs::*;

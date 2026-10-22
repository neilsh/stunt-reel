//! Binary glTF 2.0 (`.glb`) export of decoded Stunt Island shapes and film scene frames.
//!
//! The exporter turns the Seam 3 intermediate representation
//! ([`stunt_core::contracts::SodModelIr`]) and a sampled
//! [`stunt_core::scene::SceneFrame`] into self-contained `.glb` bytes. It has no GPU or
//! windowing dependency.
//!
//! # Invariants
//!
//! - `[I1]` Right-handed metric coordinates (`+X` right, `+Y` up, `-Z` forward) are already
//!   glTF's basis, so positions, normals and matrices are copied unchanged. Column-major
//!   `local_matrix` / `world_matrix` values are glTF's `matrix` layout.
//! - `[I3]` Each vertex's Mode 13h palette index is exported as a `COLOR_0` attribute through
//!   [`stunt_core::contracts::get_palette_rgb_float`], and the single material is
//!   `KHR_materials_unlit`, so the authentic palette colours are shown without lighting.
//! - `[I5]` Coplanar decal slices are already displaced by 0.001 m along their normal by the
//!   SOD tessellator (`stunt_core::sod::EPSILON_DISPLACEMENT`); the exporter copies those
//!   positions and does not displace them a second time.
//!
//! # Layout
//!
//! - [`export_shape`]: one model, one glTF node per [`stunt_core::contracts::SodNode`].
//! - [`export_scene_frame`]: camera, optional `WORLD`, and one node per actor, with each
//!   distinct shape's meshes and accessors written once and shared by every instance.
//! - [`summarize`]: counts read back from `.glb` bytes.
#![deny(unsafe_code)]
#![warn(missing_docs)]

mod error;
mod glb;
mod scene_frame;
mod shape;

pub use error::GltfError;
pub use glb::{GlbSummary, summarize};
pub use scene_frame::{camera_rotation, export_scene_frame};
pub use shape::export_shape;

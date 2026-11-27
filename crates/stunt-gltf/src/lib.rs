//! Binary glTF 2.0 (`.glb`) export of decoded Stunt Island shapes, film scene frames and
//! animated films.
//!
//! The exporter turns the Seam 3 intermediate representation
//! ([`stunt_core::contracts::SodModelIr`]) and a sampled
//! [`stunt_core::scene::SceneFrame`] into self-contained `.glb` bytes. It has no GPU or
//! windowing dependency.
//!
//! # Invariants
//!
//! - `[I1]` Right-handed metric coordinates (`+X` right, `+Y` up, `-Z` forward) are already
//!   glTF's basis, so positions, normals and matrices are copied unchanged, except that a
//!   line or disc vertex, whose IR `normal` is not a surface normal, exports a unit one. Column-major
//!   `local_matrix` / `world_matrix` values are glTF's `matrix` layout.
//! - `[I3]` Each vertex's Mode 13h palette index is exported as a `COLOR_0` attribute through
//!   [`stunt_core::contracts::get_palette_rgb_float`], and the single material is
//!   `KHR_materials_unlit`, so the authentic palette colours are shown without lighting.
//! - `[I5]` Coplanar decal slices lie in their base's plane; glTF has no depth bias or draw
//!   order, so the exporter lifts them `stunt_core::sod::EPSILON_DISPLACEMENT` toward their
//!   front (the renderer does not).
//!
//! # Layout
//!
//! - [`export_shape`]: one model, one glTF node per [`stunt_core::contracts::SodNode`].
//! - [`export_scene_frame`]: camera, optional `WORLD`, the view-facing props and one node per
//!   actor, with each distinct shape's meshes and accessors written once and shared by every
//!   instance.
//! - [`export_film`]: the same scene over a span of ticks, with one animation moving the
//!   camera, the actors and the view-facing props (`[I4]`: sampled at each 50 Hz tick).
//! - [`summarize`]: counts read back from `.glb` bytes.

mod error;
mod film;
mod glb;
mod scene_frame;
mod shape;

pub use error::GltfError;
pub use film::{
    CUT_EPSILON, FilmExportOptions, FilmGlb, ROTATION_TOLERANCE, TRANSLATION_TOLERANCE, export_film,
};
pub use glb::{GlbSummary, summarize};
pub use scene_frame::{camera_rotation, export_scene_frame};
pub use shape::export_shape;

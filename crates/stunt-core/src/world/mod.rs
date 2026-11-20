//! Static island world: ocean, terrain, and placed scenery props, built without a GPU.
//!
//! The world is the part of a film scene that never moves (GLOSSARY.md: **World**). It is
//! assembled from three byte inputs that the caller locates and reads:
//!
//! - the anchor table (`ANCHORPT.DAT`, parsed by [`crate::anchor::parse_anchor_table`]), the same
//!   records `OP_TAP` resolves against (ADR-0001);
//! - `MAP.BIN`, whose 30-byte patches index that table to form terrain polygons;
//! - `SCENERY.scn`, a BSP tree of prop placements referencing shapes by resource ID.
//!
//! [`build_world`] merges them with the decoded shapes of the film's archive into one
//! [`crate::contracts::SodModelIr`] that is drawn with an identity transform. This module never touches the
//! filesystem: where those files live is the caller's concern.
//!
//! Where the props stand is the `scenery` module's question (GLOSSARY.md: **Placement**,
//! **Scenery walk**); this module builds the meshes around its answer.
//!
//! Anchor records are raw island coordinates mapped to `[I1]` by
//! [`crate::anchor::AnchorPoint::register_position`]; placements apply the same `(-x, -y, z)`
//! mapping. Mesh output follows `[I2]` (flat arena), `[I3]` (palette indices), and `[I5]`
//! (props' coplanar decals go into a separate batch so renderers can depth-bias them).

mod assemble;
mod map_bin;
mod mesh;
mod placed;
mod scenery;
mod tap_props;
mod terrain;

pub use assemble::{FacingProp, World, WorldInputs, build_world};
pub use mesh::{GROUND_NODE, PropRun};
pub use placed::{PlacementRecord, PlacementRecords};
pub use scenery::{
    PartitionStep, SceneryShapes, ScnNode, ScnStop, ScnStopReason, Split, scenery_shape_ids,
};
pub use tap_props::{TapFailure, TapFailureReason};
pub use terrain::{GroundPlane, TerrainSurface};

#[cfg(test)]
mod test_support;

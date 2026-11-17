//! Film scene: a [`crate::flm::FilmTimeline`] bound to the shapes and world it plays in, without a GPU.
//!
//! A film scene is the data a renderer needs to draw any moment of a film (GLOSSARY.md:
//! **Film scene**, **Scene frame**). [`FilmScene::frame`] samples the timeline and pairs each
//! actor with the shape its `shape_id` names, producing a [`SceneFrame`] of plain data in
//! `[I1]` metres. Nothing here touches the filesystem or a graphics API: callers locate the
//! files and hand over their bytes ([`SceneInputs`]) or pre-built parts ([`FilmScene::new`]).
//!
//! Shapes come from a film's `.ALL` archive or straight from the game's `RES` files
//! ([`ShapeSource`]); a stock archive chunk is a copy of a `RES` item, so both give the same
//! shape for an id (`research/makeone-exe/linking.md` §§ 2 and 7). Archive chunk names follow
//! `# [FMT-ALL-CHUNKS]` (`MODEL_%04X.SOD`, `[I8]`): the hex in the name is the resource ID that
//! `ActorTransform::shape_id` carries. Chunks that stop at an
//! opcode outside the decoded table keep the geometry parsed so far and carry the stop in
//! their decode record, so a partial shape is still a value with provenance. The anchor
//! table follows ADR-0001.

mod bank;
mod film;
mod projection;
mod shadow;
mod shapes;
mod sprite;

pub use self::bank::{PREVIOUS_FRAME_TICKS, angle_bank};
pub use self::film::{
    ActorDraw, FilmScene, SceneError, SceneFrame, SceneInputs, SceneReport, SpriteDraw, WorldStats,
};
pub use self::projection::ViewCamera;
pub use self::shapes::{
    ArchiveShapes, RelitShapes, ShapeSource, SkippedChunk, decode_archive_shapes, decode_res_shapes,
};

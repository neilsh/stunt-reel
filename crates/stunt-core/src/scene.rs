//! Film scene: a [`FilmTimeline`] bound to the shapes and world it plays in, without a GPU.
//!
//! A film scene is the data a renderer needs to draw any moment of a film (GLOSSARY.md:
//! **Film scene**, **Scene frame**). [`FilmScene::frame`] samples the timeline and pairs each
//! actor with the shape its `shape_id` names, producing a [`SceneFrame`] of plain data in
//! `[I1]` metres. Nothing here touches the filesystem or a graphics API: callers locate the
//! files and hand over their bytes ([`SceneInputs`]) or pre-built parts ([`FilmScene::new`]).
//!
//! Archive chunk names follow `# [FMT-ALL-CHUNKS]` (`MODEL_%04X.SOD`, `[I8]`): the hex in the
//! name is the resource ID that `ActorTransform::shape_id` carries. Chunks that stop at an
//! opcode outside the decoded table keep the geometry parsed so far and are reported as
//! partial in [`SceneReport`]. The anchor table follows ADR-0001.

use std::collections::HashMap;
use std::fmt;

use crate::contracts::{CameraTransform, PaletteControls, SodModelIr};
use crate::flm::{FilmTimeline, FlmError};
use crate::sod::{SodAnchorPoint, SodError, SodStop, transpile_sod_lenient};
use crate::vfs::VfsError;
use crate::world::{World, WorldBounds, WorldInputs, build_world, parse_anchor_table};

/// Column-major identity matrix.
const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Raw bytes of the files that make up one film scene; the caller locates and reads them.
#[derive(Clone, Copy, Debug)]
pub struct SceneInputs<'a> {
    /// `.FLM` film bytes.
    pub film: &'a [u8],
    /// `.ALL` archive bytes carrying the `MODEL_%04X.SOD` shapes, if any.
    pub archive: Option<&'a [u8]>,
    /// `ANCHORPT.DAT` bytes: the table `OP_TAP` and the terrain resolve against.
    pub anchors: Option<&'a [u8]>,
    /// `MAP.BIN` bytes (terrain patches).
    pub map: Option<&'a [u8]>,
    /// `SCENERY.scn` bytes (prop placements).
    pub scenery: Option<&'a [u8]>,
}

/// Why a film scene could not be built.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SceneError {
    /// The film header was unreadable.
    Film(FlmError),
    /// The `.ALL` archive container was malformed.
    Archive(VfsError),
}

impl fmt::Display for SceneError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Film(e) => write!(f, "film: {e}"),
            Self::Archive(e) => write!(f, "archive: {e}"),
        }
    }
}

impl std::error::Error for SceneError {}

/// An archive `MODEL_*.SOD` chunk that could not be decoded at all.
#[derive(Debug, Clone, PartialEq)]
pub struct SkippedChunk {
    /// Archive entry name, e.g. `MODEL_0042.SOD`.
    pub name: String,
    /// The decode failure.
    pub error: SodError,
}

/// Size and extent of the built static world.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WorldStats {
    /// Terrain patches placed.
    pub terrain_patches: usize,
    /// Distinct static props placed.
    pub props_placed: usize,
    /// Bounds of the world mesh in `[I1]` metres.
    pub bounds: WorldBounds,
}

/// What happened while loading a scene: data for the caller to print or assert on.
#[derive(Debug, Clone, PartialEq)]
pub struct SceneReport {
    /// Chunks that failed to decode and were dropped.
    pub skipped: Vec<SkippedChunk>,
    /// Shapes kept with only the geometry parsed before an unrecognized opcode.
    pub partial: Vec<(u16, SodStop)>,
    /// True when a non-empty anchor table was supplied.
    pub anchors_loaded: bool,
    /// Why film decoding stopped before the epilogue; `None` for a complete film.
    pub film_stop: Option<FlmError>,
    /// Statistics of the built world; `None` when there is no world.
    pub world: Option<WorldStats>,
}

/// Shapes decoded from one `.ALL` archive.
#[derive(Debug, Clone, Default)]
pub struct ArchiveShapes {
    /// Decoded models keyed by the resource ID in their chunk name.
    pub shapes: HashMap<u16, SodModelIr>,
    /// Chunks that failed to decode.
    pub skipped: Vec<SkippedChunk>,
    /// Shapes that decoded only up to an unrecognized opcode.
    pub partial: Vec<(u16, SodStop)>,
}

/// Decodes every `MODEL_%04X.SOD` chunk of `.ALL` bytes, resolving `OP_TAP` against `anchors`.
///
/// Other chunks are ignored. An empty `anchors` table is treated as absent.
pub fn decode_archive_shapes(
    archive: &[u8],
    anchors: &[SodAnchorPoint],
) -> Result<ArchiveShapes, VfsError> {
    let archive = crate::vfs::parse_all(archive)?;
    let anchor_slice = (!anchors.is_empty()).then_some(anchors);

    let mut out = ArchiveShapes::default();
    for entry in archive.entries.values() {
        let Some(shape_id) = model_shape_id(&entry.name) else {
            continue;
        };
        match transpile_sod_lenient(&entry.data, &entry.name, anchor_slice) {
            Ok((ir, stop)) => {
                if let Some(stop) = stop {
                    out.partial.push((shape_id, stop));
                }
                out.shapes.insert(shape_id, ir);
            }
            Err(error) => out.skipped.push(SkippedChunk {
                name: entry.name.clone(),
                error,
            }),
        }
    }
    Ok(out)
}

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}

/// One drawable actor in a [`SceneFrame`].
#[derive(Debug, Clone, PartialEq)]
pub struct ActorDraw {
    /// Key of the shape to draw, as accepted by [`FilmScene::shape`].
    pub shape_id: u16,
    /// Column-major model-to-world matrix in `[I1]`.
    pub world_matrix: [f32; 16],
    /// Visibility state mask of the actor at this tick.
    pub state_mask: u16,
    /// Distance in metres from the camera eye to the actor position.
    pub distance: f32,
}

/// Everything to draw at one tick.
#[derive(Debug, Clone, PartialEq)]
pub struct SceneFrame {
    /// Sampled film tick (50 Hz, fractional for sub-tick interpolation `[I4]`).
    pub tick: f32,
    /// Camera at this tick.
    pub camera: CameraTransform,
    /// True when [`FilmScene::world`] should be drawn with an identity transform.
    pub world: bool,
    /// One draw per actor whose shape is in the table. Actors sharing a shape each get
    /// their own draw; there is no de-duplication.
    pub actors: Vec<ActorDraw>,
    /// Film variables the palette is built from at this tick.
    pub palette: PaletteControls,
}

/// A film with the shapes and static world it plays against.
#[derive(Debug, Clone)]
pub struct FilmScene {
    timeline: FilmTimeline,
    shapes: HashMap<u16, SodModelIr>,
    world: Option<World>,
    /// Set for a loose model bound with no actors in the film: drawn at the origin.
    origin_shape: Option<u16>,
}

impl FilmScene {
    /// Assembles a scene from already-built parts.
    #[must_use]
    pub fn new(
        timeline: FilmTimeline,
        shapes: HashMap<u16, SodModelIr>,
        world: Option<World>,
    ) -> Self {
        Self {
            timeline,
            shapes,
            world,
            origin_shape: None,
        }
    }

    /// Builds a scene around one loose model that has no archive.
    ///
    /// The model is keyed under the first actor with a nonzero `shape_id` at the first
    /// keyframe, falling back to the first actor. A film with no actors there gets a single
    /// draw at the origin with an identity matrix whenever a frame has no actors.
    #[must_use]
    pub fn with_single_model(timeline: FilmTimeline, model: SodModelIr) -> Self {
        let actors = timeline
            .slices()
            .first()
            .map_or(&[][..], |slice| slice.record.actors.as_slice());
        let bound = actors
            .iter()
            .find(|a| a.shape_id != 0)
            .or_else(|| actors.first())
            .map(|a| a.shape_id);
        let key = bound.unwrap_or(0);
        let mut scene = Self::new(timeline, HashMap::from([(key, model)]), None);
        if bound.is_none() {
            scene.origin_shape = Some(key);
        }
        scene
    }

    /// Parses `inputs` into a scene plus a report of what loaded.
    ///
    /// Only an unreadable film header or archive container is an error; per-chunk decode
    /// failures, partial shapes, and a truncated film are reported, not fatal. The world is
    /// built from the decoded shapes and whichever of anchors, map and scenery were given.
    pub fn load(inputs: &SceneInputs<'_>) -> Result<(Self, SceneReport), SceneError> {
        let timeline = FilmTimeline::from_bytes(inputs.film).map_err(SceneError::Film)?;
        Self::load_with_timeline(timeline, inputs)
    }

    /// Like [`Self::load`], but plays an already-built `timeline`; `inputs.film` is ignored.
    ///
    /// For callers that supply their own timeline (e.g. a synthetic one) yet still want the
    /// archive shapes and world.
    pub fn load_with_timeline(
        timeline: FilmTimeline,
        inputs: &SceneInputs<'_>,
    ) -> Result<(Self, SceneReport), SceneError> {
        let anchors = inputs.anchors.map(parse_anchor_table).unwrap_or_default();

        let decoded = match inputs.archive {
            Some(bytes) => decode_archive_shapes(bytes, &anchors).map_err(SceneError::Archive)?,
            None => ArchiveShapes::default(),
        };

        let eyes: Vec<[f32; 3]> = timeline
            .slices()
            .iter()
            .map(|slice| slice.record.camera.eye)
            .collect();
        let world = build_world(
            &WorldInputs {
                anchors: &anchors,
                map: inputs.map,
                scenery: inputs.scenery,
                view_eyes: &eyes,
            },
            &decoded.shapes,
        );
        let report = SceneReport {
            skipped: decoded.skipped,
            partial: decoded.partial,
            anchors_loaded: !anchors.is_empty(),
            film_stop: timeline.stop_reason().cloned(),
            world: world.as_ref().map(|w| WorldStats {
                terrain_patches: w.terrain_patches,
                props_placed: w.props_placed,
                bounds: w.bounds,
            }),
        };
        Ok((Self::new(timeline, decoded.shapes, world), report))
    }

    /// The film timeline (use `cues_between` for audio).
    #[must_use]
    pub fn timeline(&self) -> &FilmTimeline {
        &self.timeline
    }

    /// The shape bound to `shape_id`, if the scene has one.
    #[must_use]
    pub fn shape(&self, shape_id: u16) -> Option<&SodModelIr> {
        self.shapes.get(&shape_id)
    }

    /// Every shape with its key, in no particular order.
    pub fn shapes(&self) -> impl Iterator<Item = (u16, &SodModelIr)> {
        self.shapes.iter().map(|(id, ir)| (*id, ir))
    }

    /// The static world, drawn with an identity transform.
    #[must_use]
    pub fn world(&self) -> Option<&World> {
        self.world.as_ref()
    }

    /// Samples the scene at an authored 50 Hz `tick`.
    ///
    /// An empty timeline yields the default camera and no actors.
    #[must_use]
    pub fn frame(&self, tick: f32) -> SceneFrame {
        let world = self.world.is_some();
        let Some(record) = self.timeline.sample(tick) else {
            return SceneFrame {
                tick,
                camera: CameraTransform::default(),
                world,
                actors: Vec::new(),
                palette: PaletteControls::default(),
            };
        };
        let eye = record.camera.eye;
        let mut actors: Vec<ActorDraw> = record
            .actors
            .iter()
            .filter(|a| self.shapes.contains_key(&a.shape_id))
            .map(|a| ActorDraw {
                shape_id: a.shape_id,
                world_matrix: a.world_matrix,
                state_mask: a.state_mask,
                distance: distance(eye, a.position_meters),
            })
            .collect();
        if let Some(shape_id) = self.origin_shape.filter(|_| record.actors.is_empty()) {
            actors.push(ActorDraw {
                shape_id,
                world_matrix: IDENTITY_MATRIX,
                state_mask: 0,
                distance: distance(eye, [0.0; 3]),
            });
        }
        SceneFrame {
            tick,
            camera: record.camera,
            world,
            actors,
            palette: record.palette,
        }
    }
}

fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    let d = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
}

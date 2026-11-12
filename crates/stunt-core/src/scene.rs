//! Film scene: a [`FilmTimeline`] bound to the shapes and world it plays in, without a GPU.
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

use std::collections::HashMap;

use crate::anchor::{AnchorPoint, parse_anchor_table};
use crate::contracts::trajectory::{DEFAULT_CAMERA_LENS, PLAYONE_FOV_Y_DEGREES};
use crate::contracts::{ActorTransform, CameraTransform, PaletteControls, ShapeExtent, SodModelIr};
use crate::credits::CreditLines;
use crate::flm::{FilmTimeline, FlmError};
use crate::font::PFont;
use crate::link::{LinkError, shape_chunks};
use crate::sod::{
    DecodeMode, EPSILON_DISPLACEMENT, ShadeLight, SodError, SodStopReason, decode_sod_lit,
};
use crate::vfs::{ResRegions, VfsError};
use crate::world::{GroundPlane, ScnStop, TapFailure, World, WorldInputs, build_world};

/// Column-major identity matrix.
const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Raw bytes of the files that make up one film scene; the caller locates and reads them.
#[derive(Clone, Copy, Debug)]
pub struct SceneInputs<'a> {
    /// `.FLM` film bytes.
    pub film: &'a [u8],
    /// Where the shapes come from, if anywhere.
    pub shapes: Option<ShapeSource<'a>>,
    /// `ANCHORPT.DAT` bytes: the table `OP_TAP` and the terrain resolve against.
    pub anchors: Option<&'a [u8]>,
    /// `MAP.BIN` bytes (terrain patches).
    pub map: Option<&'a [u8]>,
    /// `SCENERY.scn` bytes (prop placements).
    pub scenery: Option<&'a [u8]>,
}

/// Where a scene's shapes come from.
#[derive(Clone, Copy, Debug)]
pub enum ShapeSource<'a> {
    /// `.ALL` archive bytes carrying the `MODEL_%04X.SOD` shapes.
    Archive(&'a [u8]),
    /// The game's `RES` files, split, read as [`decode_res_shapes`] reads them; files without
    /// shapes are ignored.
    Res(&'a [ResRegions<'a>]),
}

/// Why a film scene could not be built.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum SceneError {
    /// The film header was unreadable.
    #[error("film: {0}")]
    Film(FlmError),
    /// The `.ALL` archive container was malformed.
    #[error("archive: {0}")]
    Archive(VfsError),
    /// The `RES` files do not form one shape set: two share an index, or one has too many
    /// items.
    #[error("RES files: {0}")]
    Res(LinkError),
}

/// A `MODEL_*.SOD` chunk that could not be decoded at all.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SkippedChunk {
    /// Archive entry name, e.g. `MODEL_0042.SOD`; a `RES` item is named as its chunk would be.
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
    /// Extent of the world mesh in `[I1]` metres.
    pub bounds: ShapeExtent,
    /// Why the `SCENERY.scn` walk ended early (cycle, budget, depth or a malformed node);
    /// `None` when it ran to the end or there was no scenery.
    pub scenery_stop: Option<ScnStop>,
}

/// What happened while loading a scene: data for the caller to print or assert on.
#[derive(Debug, Clone, PartialEq)]
pub struct SceneReport {
    /// Chunks that failed to decode and were dropped.
    pub skipped: Vec<SkippedChunk>,
    /// True when a non-empty anchor table was supplied.
    pub anchors_loaded: bool,
    /// Why film decoding stopped before the epilogue; `None` for a complete film.
    pub film_stop: Option<FlmError>,
    /// Statistics of the built world; `None` when there is no world.
    pub world: Option<WorldStats>,
    /// Placed `OP_TAP` shapes the world drew partly or not at all ([`World::tap_failures`]).
    pub tap_failures: Vec<TapFailure>,
}

/// Shapes decoded from one [`ShapeSource`].
#[derive(Debug, Clone, Default)]
pub struct ArchiveShapes {
    /// Decoded models keyed by the resource ID in their chunk name.
    ///
    /// A shape that stopped at an unrecognized opcode is still here: its
    /// [`crate::contracts::SodModelIr::decode`] record carries the stop, so partiality
    /// travels with the shape rather than as a parallel list.
    pub shapes: HashMap<u16, SodModelIr>,
    /// Chunks that failed to decode.
    pub skipped: Vec<SkippedChunk>,
    /// Streams of the shapes that run `OP_TAP`, kept only when anchors were supplied. A tapped
    /// point depends on where the shape is placed, so the world decodes these again per
    /// placement ([`WorldInputs::anchored_shapes`]).
    pub anchored: HashMap<u16, Vec<u8>>,
}

/// Decodes every `MODEL_%04X.SOD` chunk of `.ALL` bytes, resolving `OP_TAP` against `anchors`
/// and shading `OP_SHADES` normals against `light`.
///
/// Other chunks are ignored. An empty `anchors` table is treated as absent.
///
/// # Errors
/// Returns the [`VfsError`] from [`crate::vfs::parse_all`] if `archive` is not a well-formed
/// `.ALL` container. A single chunk that fails to decode is not an error: it is listed in
/// [`ArchiveShapes::skipped`].
pub fn decode_archive_shapes(
    archive: &[u8],
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> Result<ArchiveShapes, VfsError> {
    let archive = crate::vfs::parse_all(archive)?;
    let chunks = archive.entries.values().filter_map(|entry| {
        model_shape_id(&entry.name).map(|id| (id, entry.name.clone(), entry.data.as_slice()))
    });
    Ok(decode_chunks(chunks, anchors, light))
}

/// Decodes every item of the shape files among `files` as [`decode_archive_shapes`] decodes an
/// archive's chunks.
///
/// The same ids, names, anchors, light and lenient decoding, and only the items an archive would
/// name `MODEL_%04X.SOD`.
///
/// # Errors
/// Returns the [`LinkError`] from [`crate::link::shape_chunks`]: two shape files share an
/// index, or one has more than 255 items. A single item that fails to decode is not an error:
/// it is listed in [`ArchiveShapes::skipped`].
pub fn decode_res_shapes(
    files: &[ResRegions<'_>],
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> Result<ArchiveShapes, LinkError> {
    let chunks = shape_chunks(files)?
        .into_iter()
        .filter_map(|(id, payload)| {
            let name = crate::vfs::chunk_name(id, payload);
            model_shape_id(&name).map(|id| (id, name, payload))
        });
    Ok(decode_chunks(chunks, anchors, light))
}

/// Decodes `(shape id, chunk name, payload)` chunks leniently, keeping failures as skipped.
fn decode_chunks<'a>(
    chunks: impl Iterator<Item = (u16, String, &'a [u8])>,
    anchors: &[AnchorPoint],
    light: ShadeLight,
) -> ArchiveShapes {
    let anchor_slice = (!anchors.is_empty()).then_some(anchors);
    let mut out = ArchiveShapes::default();
    for (shape_id, name, data) in chunks {
        // Anchors only matter to `OP_TAP`; a first pass without them shows which shapes tap.
        let mut decoded = decode_sod_lit(data, &name, None, DecodeMode::Lenient, light);
        let taps = decoded.as_ref().is_ok_and(|ir| {
            ir.decode()
                .and_then(|record| record.stop.as_ref())
                .is_some_and(|stop| stop.reason == SodStopReason::MissingAnchors)
        });
        if taps && anchor_slice.is_some() {
            decoded = decode_sod_lit(data, &name, anchor_slice, DecodeMode::Lenient, light);
            out.anchored.insert(shape_id, data.to_vec());
        }
        match decoded {
            Ok(ir) => {
                out.shapes.insert(shape_id, ir);
            }
            Err(error) => out.skipped.push(SkippedChunk { name, error }),
        }
    }
    out
}

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}

/// One drawable actor in a [`SceneFrame`].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ActorDraw {
    /// Key of the shape to draw, as accepted by [`FilmScene::shape`].
    pub shape_id: u16,
    /// Column-major model-to-world matrix in `[I1]`.
    pub world_matrix: [f32; 16],
    /// Visibility state mask of the actor at this tick.
    pub state_mask: u16,
    /// Distance in metres from the camera eye to the actor position.
    pub distance: f32,
    /// Model-to-world matrix of the actor's ground shadow, when its slot casts one
    /// (`SIF_SHADOW`): the actor flattened straight down onto the ground plane under its
    /// origin and lifted by the `[I5]` decal displacement. The shadow is the same shape
    /// drawn again through this matrix in palette index 0 (`research/playone-exe/sod-vm.md`
    /// section 9.1).
    pub shadow_matrix: Option<[f32; 16]>,
}

/// The lens-zoomed camera used to draw a [`SceneFrame`].
///
/// This is a **view** camera, not the authored [`CameraTransform`] a trajectory
/// record carries: [`Self::from_authored`] is the only place the lens zoom is
/// applied, so a record never holds a final field of view.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ViewCamera {
    /// Camera world position in meters `[x, y, z]` per `[I1]`.
    pub eye: [f32; 3],
    /// Look-at point in meters `[x, y, z]`.
    pub target: [f32; 3],
    /// Vertical field of view in degrees after the lens zoom.
    pub fov_degrees: f32,
    /// View roll about the forward axis in radians.
    pub roll_radians: f32,
}

impl ViewCamera {
    /// Applies the authored lens zoom to a trajectory record's camera.
    #[must_use]
    pub fn from_authored(camera: &CameraTransform) -> Self {
        Self {
            eye: camera.eye,
            target: camera.target,
            fov_degrees: camera.lens_fov_degrees(camera.fov_degrees),
            roll_radians: camera.roll_radians,
        }
    }
}

impl Default for ViewCamera {
    fn default() -> Self {
        Self::from_authored(&CameraTransform::default())
    }
}

/// Everything to draw at one tick.
#[derive(Debug, Clone, PartialEq)]
pub struct SceneFrame {
    /// Sampled film tick (50 Hz, fractional for sub-tick interpolation `[I4]`).
    pub tick: f32,
    /// Lens-zoomed camera at this tick.
    pub view: ViewCamera,
    /// The view camera's lens word at this tick, which also scales the scenery's
    /// level-of-detail switch ([`CameraTransform::lod_keeps_subtree`]).
    pub lens: u16,
    /// True when [`FilmScene::world`] should be drawn with an identity transform.
    pub world: bool,
    /// One draw per actor whose shape is in the table. Actors sharing a shape each get
    /// their own draw; there is no de-duplication.
    pub actors: Vec<ActorDraw>,
    /// Film variables the palette is built from at this tick.
    pub palette: PaletteControls,
    /// Credits text on screen at this tick (`0x99` until `0x98`), drawn over the scene.
    pub credits: Option<CreditLines>,
}

/// A film with the shapes and static world it plays against.
#[derive(Debug, Clone)]
pub struct FilmScene {
    timeline: FilmTimeline,
    shapes: HashMap<u16, SodModelIr>,
    world: Option<World>,
    /// Set for a loose model bound with no actors in the film: drawn at the origin.
    origin_shape: Option<u16>,
    /// `PFONT.BIN`, read from the corpus beside the film, for the credits overlay.
    font: Option<PFont>,
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
            font: None,
        }
    }

    /// Draws credits with `font`; without one a scene carries credits but draws none.
    #[must_use]
    pub fn with_font(mut self, font: PFont) -> Self {
        self.font = Some(font);
        self
    }

    /// The credits font, if one was given.
    #[must_use]
    pub fn font(&self) -> Option<&PFont> {
        self.font.as_ref()
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
    /// Per-chunk decode failures, partial shapes and a truncated film are reported in the
    /// [`SceneReport`], not fatal. Anchors, map and scenery are optional.
    ///
    /// # Errors
    /// Returns [`SceneError::Film`] if `inputs.film` fails [`FilmTimeline::from_bytes`], and
    /// otherwise the errors of [`Self::load_with_timeline`].
    pub fn load(inputs: &SceneInputs<'_>) -> Result<(Self, SceneReport), SceneError> {
        let timeline = FilmTimeline::from_bytes(inputs.film).map_err(SceneError::Film)?;
        Self::load_with_timeline(timeline, inputs)
    }

    /// Like [`Self::load`], but plays an already-built `timeline`; `inputs.film` is ignored.
    ///
    /// For callers that supply their own timeline (e.g. a synthetic one) yet still want the
    /// archive shapes and world.
    ///
    /// # Errors
    /// Returns [`SceneError::Archive`] if `inputs.shapes` is an archive that is not a
    /// well-formed `.ALL` container, and [`SceneError::Res`] if it is `RES` files that
    /// [`decode_res_shapes`] refuses. Never returns [`SceneError::Film`], since `timeline` is
    /// already built.
    pub fn load_with_timeline(
        timeline: FilmTimeline,
        inputs: &SceneInputs<'_>,
    ) -> Result<(Self, SceneReport), SceneError> {
        let anchors = inputs.anchors.map(parse_anchor_table).unwrap_or_default();

        // `PLAYONE` lights every object from film variable 13 (`0x196C`); the light the
        // first slice sets is the film's. Actors get it unrotated: their own light is the
        // world light turned by their rotation and the view, which changes every frame.
        let light = ShadeLight::world(
            timeline
                .slices()
                .first()
                .map_or(0, |slice| slice.record.palette.sky),
        );
        let decoded = match inputs.shapes {
            Some(ShapeSource::Archive(bytes)) => {
                decode_archive_shapes(bytes, &anchors, light).map_err(SceneError::Archive)?
            }
            Some(ShapeSource::Res(files)) => {
                decode_res_shapes(files, &anchors, light).map_err(SceneError::Res)?
            }
            None => ArchiveShapes::default(),
        };

        let eyes: Vec<[f32; 3]> = timeline
            .slices()
            .iter()
            .map(|slice| slice.record.camera.eye)
            .collect();
        let cameras: Vec<CameraTransform> = timeline
            .slices()
            .iter()
            .map(|slice| slice.record.camera)
            .collect();
        let max_zoom = max_magnification(&cameras);
        let max_lod_shift = cameras
            .iter()
            .map(|camera| camera.lod_lens_words().1)
            .max()
            .unwrap_or(1);
        let world = build_world(
            &WorldInputs {
                anchors: &anchors,
                map: inputs.map,
                scenery: inputs.scenery,
                view_eyes: &eyes,
                max_zoom,
                max_lod_shift,
                anchored_shapes: &decoded.anchored,
                light,
            },
            &decoded.shapes,
        );
        let report = SceneReport {
            skipped: decoded.skipped,
            anchors_loaded: !anchors.is_empty(),
            film_stop: timeline.stop_reason().cloned(),
            world: world.as_ref().map(|w| WorldStats {
                terrain_patches: w.terrain_patches,
                props_placed: w.props_placed,
                bounds: w.bounds,
                scenery_stop: w.scenery_stop,
            }),
            tap_failures: world
                .as_ref()
                .map(|w| w.tap_failures.clone())
                .unwrap_or_default(),
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
                view: ViewCamera::default(),
                lens: DEFAULT_CAMERA_LENS,
                world,
                actors: Vec::new(),
                palette: PaletteControls::default(),
                credits: None,
            };
        };
        let eye = record.camera.eye;
        let mut actors: Vec<ActorDraw> = record
            .actors
            .iter()
            .filter_map(|a| self.shapes.get(&a.shape_id).map(|shape| (a, shape)))
            .map(|(a, shape)| {
                let world_matrix = actor_world_matrix(a, shape);
                ActorDraw {
                    shape_id: a.shape_id,
                    world_matrix,
                    state_mask: a.state_mask,
                    distance: distance(eye, a.position_meters),
                    shadow_matrix: a
                        .casts_shadow
                        .then(|| self.shadow_matrix(a.position_meters, &world_matrix)),
                }
            })
            .collect();
        if let Some(shape_id) = self.origin_shape.filter(|_| record.actors.is_empty()) {
            actors.push(ActorDraw {
                shape_id,
                world_matrix: IDENTITY_MATRIX,
                state_mask: 0,
                distance: distance(eye, [0.0; 3]),
                shadow_matrix: None,
            });
        }
        SceneFrame {
            tick,
            view: ViewCamera::from_authored(&record.camera),
            lens: record.camera.lens,
            world,
            actors,
            palette: record.palette,
            credits: self.timeline.credits_at(tick).cloned(),
        }
    }

    /// The shadow matrix of an actor at `position` drawn through `world_matrix`.
    ///
    /// PLAYONE solves one ground plane at the actor's x and z (`0x19FC`) and flattens the
    /// whole object onto it (`0x1C0D`), so every vertex lands on that plane, not on the
    /// terrain under its own x and z. The plane here is the terrain triangle under the
    /// origin; with no world it is `y = 0`, as for PLAYONE's null plane (`0x1A12`).
    fn shadow_matrix(&self, position: [f32; 3], world_matrix: &[f32; 16]) -> [f32; 16] {
        let [x, y, z] = position;
        let plane = self
            .world
            .as_ref()
            .map_or(GroundPlane::LEVEL_ZERO, |w| w.ground_plane(x, z, y));
        mat4_mul(&plane.flatten_matrix(EPSILON_DISPLACEMENT), world_matrix)
    }
}

/// The column-major product `a * b`.
fn mat4_mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    let (a_cols, _) = a.as_chunks::<4>();
    let (b_cols, _) = b.as_chunks::<4>();
    let mut out = [0.0; 16];
    let (out_cols, _) = out.as_chunks_mut::<4>();
    for (out_col, b_col) in out_cols.iter_mut().zip(b_cols) {
        for (a_col, &weight) in a_cols.iter().zip(b_col) {
            for (o, &v) in out_col.iter_mut().zip(a_col) {
                *o += v * weight;
            }
        }
    }
    out
}

/// An actor's model-to-world matrix, with its shape's ground offset taken back out.
///
/// The decoder lifts every vertex by the header's `ground_y_offset`, which stands a world
/// prop on the ground it is placed at. Heuristic: a film actor's position is taken as its
/// model origin, so the lift is undone along the actor's own +Y. Drawing actors with the
/// lift put them about 10 rows above the capture on `CTRY.FLM`, and a sweep of the removed
/// fraction peaks at exactly one offset on both films. `PLAYONE.EXE` applies the lift only
/// when it places scene-tree shapes; its actor draw `0x1D5F` does not read it
/// (research/formats/auxiliary/scenery.md section 3.3).
fn actor_world_matrix(actor: &ActorTransform, shape: &SodModelIr) -> [f32; 16] {
    let mut matrix = actor.compute_world_matrix();
    if let Some(header) = shape.decode().map(|record| record.header) {
        let lift = -f32::from(header.ground_y_offset) * header.scale_factor;
        let [_, _, _, _, ux, uy, uz, _, _, _, _, _, tx, ty, tz, _] = &mut matrix;
        *tx += *ux * lift;
        *ty += *uy * lift;
        *tz += *uz * lift;
    }
    matrix
}

fn distance(a: [f32; 3], b: [f32; 3]) -> f32 {
    let d = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
}

/// Largest magnification over PLAYONE's default lens that `cameras` draw, at least 1.0,
/// so a caller-built timeline with a narrow base is covered too. Base and lens interpolate
/// separately between slices, so each interval is bounded by its narrower base under
/// either endpoint's lens: a zero lens keeps the base field of view, so the stronger lens
/// is not always the larger `lens_zoom()`.
fn max_magnification(cameras: &[CameraTransform]) -> f32 {
    let default_half = (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan();
    cameras
        .iter()
        .zip(cameras.iter().skip(1).chain(cameras.last()))
        .flat_map(|(a, b)| {
            let base = a.fov_degrees.min(b.fov_degrees);
            [a, b].map(|lens| {
                let bound = CameraTransform {
                    fov_degrees: base,
                    ..*lens
                };
                let fov = ViewCamera::from_authored(&bound).fov_degrees;
                default_half / (fov.to_radians() / 2.0).tan()
            })
        })
        .filter(|zoom| zoom.is_finite())
        .fold(1.0, f32::max)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::trajectory::DEFAULT_CAMERA_LENS;

    /// The default authored camera with this field of view and lens.
    fn camera(fov_degrees: f32, lens: u16) -> CameraTransform {
        CameraTransform {
            fov_degrees,
            lens,
            ..CameraTransform::default()
        }
    }

    /// The shadow matrix keeps the actor's x and z, puts it on `y = 0` lifted by the
    /// `[I5]` displacement, and drops every model height.
    #[test]
    fn a_shadow_matrix_flattens_the_actor_matrix_onto_the_plane() {
        let translate = [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 5.0, 2.0, 1.0,
        ];
        let flat = GroundPlane::LEVEL_ZERO.flatten_matrix(EPSILON_DISPLACEMENT);
        let shadow = mat4_mul(&flat, &translate);
        assert_eq!(&shadow[12..], &[1.0, EPSILON_DISPLACEMENT, 2.0, 1.0]);
        assert_eq!(&shadow[4..8], &[0.0; 4]);
        assert_eq!(mat4_mul(&IDENTITY_MATRIX, &translate), translate);
    }

    fn drawn_magnification(camera: &CameraTransform) -> f32 {
        let fov = ViewCamera::from_authored(camera).fov_degrees;
        (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan() / (fov.to_radians() / 2.0).tan()
    }

    #[test]
    fn a_zero_lens_beside_a_nonzero_lens_bounds_at_its_full_base() {
        // Lens 0 draws at the full 20 degree base (about 2.22x); lens 4096 widens it.
        let cameras = [camera(20.0, 0), camera(20.0, 4096)];
        let zero = drawn_magnification(&cameras[0]);
        assert!(zero > 2.0, "zero-lens magnification {zero}");
        let bound = max_magnification(&cameras);
        assert!(bound >= zero - 1e-4, "bound {bound} below {zero}");
    }

    #[test]
    fn an_interval_takes_its_narrower_base_under_its_stronger_lens() {
        let cameras = [camera(50.0, DEFAULT_CAMERA_LENS), camera(140.0, u16::MAX)];
        let mixed = drawn_magnification(&camera(50.0, u16::MAX));
        assert!(max_magnification(&cameras) >= mixed - 1e-4);
    }

    #[test]
    fn the_default_lens_bounds_at_one() {
        let cameras = [camera(PLAYONE_FOV_Y_DEGREES, DEFAULT_CAMERA_LENS)];
        assert!((max_magnification(&cameras) - 1.0).abs() < 1e-4);
        assert_eq!(max_magnification(&[]), 1.0);
    }
}

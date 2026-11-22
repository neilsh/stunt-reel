//! The film scene: the timeline bound to its shapes and world, and the frame it draws.

use std::collections::{HashMap, HashSet};

use crate::anchor::parse_anchor_table;
use crate::contracts::trajectory::DEFAULT_CAMERA_LENS;
use crate::contracts::{
    ActorTransform, BankVariables, CameraTransform, PaletteControls, ShapeExtent, SodModelIr,
};
use crate::credits::CreditLines;
use crate::flm::{FilmTimeline, FlmError};
use crate::font::PFont;
use crate::link::LinkError;
use crate::sod::{AngleBank, ShadeLight, faces_view};
use crate::sprite::SpriteImage;
use crate::vfs::VfsError;
use crate::world::{ProbeActor, ScnStop, SlotEntry, TapFailure, World, WorldInputs, build_world};

use super::bank::{PREVIOUS_FRAME_TICKS, angle_bank};
use super::projection::{
    IDENTITY_MATRIX, ViewCamera, camera_heading, distance, facing_matrix, lifted, lod_gate_holds,
    max_magnification, min_corner_depth, transform_point,
};
use super::shadow::ground_shadow;
use super::shapes::{
    ArchiveShapes, RelitShapes, ShapeSource, SkippedChunk, decode_archive_shapes, decode_res_shapes,
};
use super::sprite::sprite_gate_open;

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

/// `[I1]` metres in the DOS axes the scenery tree and `PLAYONE`'s walks use; the map is its
/// own inverse.
fn dos_axes(p: [f32; 3]) -> [f32; 3] {
    [-p[0], -p[1], p[2]]
}

/// One drawable actor in a [`SceneFrame`].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ActorDraw {
    /// Key of the shape to draw, as accepted by [`FilmScene::shape`].
    pub shape_id: u16,
    /// Column-major model-to-world matrix in `[I1]`.
    pub world_matrix: [f32; 16],
    /// The slot's position in world `[I1]` metres, where `PLAYONE` queues the actor's
    /// pending-list entry (image `0x1A90`); [`Self::world_matrix`]'s origin lies off it by
    /// the shape's ground offset.
    pub position: [f32; 3],
    /// Visibility state mask of the actor at this tick.
    pub state_mask: u16,
    /// Distance in metres from the camera eye to the actor position.
    pub distance: f32,
    /// Model-to-world matrix of the actor's ground shadow, when its slot casts one
    /// (`SIF_SHADOW`): the actor flattened straight down onto the ground plane under its
    /// origin and lifted by the `[I5]` decal displacement. The shadow is the same shape
    /// drawn again through this matrix in palette index 0 (`research/playone-exe/sod-vm-frame.md`
    /// section 9.1).
    pub shadow_matrix: Option<[f32; 16]>,
    /// True for the view slot's draw: PLAYONE draws its shadow but not the actor (image
    /// `0x1E26`), so a renderer draws only [`Self::shadow_matrix`] and no sprite.
    pub shadow_only: bool,
    /// The light `OP_SHADES` shades the shape's normals against for this draw: the world
    /// light turned by the actor's rotation ([`ShadeLight::for_actor`]), the world light for
    /// a view-facing draw. A renderer decodes the shape again under it
    /// ([`FilmScene::relit_shapes`]) when it differs from the light the scene decoded under.
    pub light: ShadeLight,
    /// The angle-bank words the shape's `OP_ROTX`, `OP_ROTY` and `OP_ROTZ` read at this tick,
    /// every other word 0 ([`AngleBank::only`]). A renderer decodes the shape again in this
    /// pose ([`FilmScene::relit_shapes`]) unless it is [`AngleBank::REST`], the pose the scene
    /// decoded.
    pub bank: AngleBank,
}

/// One image an actor's shape draws in screen space (`OP_ANIMATE`) in a [`SceneFrame`].
///
/// `PLAYONE` blits it as a square `size` across at the anchor's projected point, palette
/// index 0 transparent, with no depth test of its own (`research/playone-exe/sod-animate.md`),
/// at its slot's place in the scenery walk ([`Self::after`]).
#[derive(Debug, Clone, PartialEq)]
pub struct SpriteDraw {
    /// Image resource of the frame, a key of [`FilmScene::image`].
    pub image_id: u16,
    /// Centre of the square in world `[I1]` metres.
    pub centre: [f32; 3],
    /// Side of the square in metres.
    pub size: f32,
    /// Index into [`SceneFrame::actors`] of the actor whose shape draws it.
    pub actor: usize,
    /// The world's placements the scenery walk draws after this sprite's slot, as ascending
    /// indices into [`World::placements`]' records, only those the world draws
    /// ([`crate::world::PlacementRecords::slot_order`]; `research/playone-exe/scene-walk-actors.md`).
    /// `None` when the walk gives the slot no place: no world, no decoded header for the
    /// slot's extent, or a node on its path that drops it.
    pub after: Option<Vec<u32>>,
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
    /// One draw per actor whose shape is in the table, the view slot's a shadow alone
    /// ([`ActorDraw::shadow_only`]). Actors sharing a shape each get their own draw; there is
    /// no de-duplication.
    pub actors: Vec<ActorDraw>,
    /// The images the actors' shapes draw at this tick, in actor order.
    pub sprites: Vec<SpriteDraw>,
    /// One draw per [`World::view_facing`] prop whose shape is in the table, turned with
    /// this tick's camera heading; drawn as props, never with a shadow.
    pub view_facing: Vec<ActorDraw>,
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
    /// Frames of the shapes' sprites, by resource id.
    images: HashMap<u16, SpriteImage>,
    /// The actors' shape streams, to decode again under each actor's light.
    relit: RelitShapes,
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
            images: HashMap::new(),
            relit: RelitShapes::default(),
        }
    }

    /// Lights each actor by its own rotation, decoding its shape again from `relit`; without
    /// it every actor keeps the shape as the scene decoded it.
    #[must_use]
    pub fn with_relit_shapes(mut self, relit: RelitShapes) -> Self {
        self.relit = relit;
        self
    }

    /// The actors' shape streams and the world light the scene's shapes were decoded under.
    #[must_use]
    pub fn relit_shapes(&self) -> &RelitShapes {
        &self.relit
    }

    /// Draws the shapes' sprites with `images`, keyed by resource id; without them a scene
    /// carries no sprite draws.
    #[must_use]
    pub fn with_images(mut self, images: HashMap<u16, SpriteImage>) -> Self {
        self.images = images;
        self
    }

    /// The image with resource id `id`, if the scene has it.
    #[must_use]
    pub fn image(&self, id: u16) -> Option<&SpriteImage> {
        self.images.get(&id)
    }

    /// Every sprite image with its resource id, in no particular order.
    pub fn images(&self) -> impl Iterator<Item = (u16, &SpriteImage)> {
        self.images.iter().map(|(id, image)| (*id, image))
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
    /// The model is keyed under the first actor other than the view slot with a nonzero
    /// `shape_id` at the first keyframe, falling back to the first such actor. A film with no
    /// such actor there gets a single draw at the origin with an identity matrix whenever a
    /// frame has none.
    #[must_use]
    pub fn with_single_model(timeline: FilmTimeline, model: SodModelIr) -> Self {
        let actors = timeline
            .slices()
            .first()
            .map_or(&[][..], |slice| slice.record.actors.as_slice());
        let mut drawn = actors.iter().filter(|a| !a.view);
        let bound = drawn
            .clone()
            .find(|a| a.shape_id != 0)
            .or_else(|| drawn.next())
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
        let anchors = inputs.anchors.map_or_default(parse_anchor_table);

        // `PLAYONE` lights every object from film variable 13 (`0x196C`); the light the
        // first slice sets is the film's. Shapes decode under it; an actor's own light,
        // turned by its rotation, is set per frame (`ActorDraw::light`).
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
        let min_corner_depth = min_corner_depth(&cameras);
        let world = build_world(
            &WorldInputs {
                anchors: &anchors,
                map: inputs.map,
                scenery: inputs.scenery,
                view_eyes: &eyes,
                max_zoom,
                max_lod_shift,
                min_corner_depth,
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
            tap_failures: world.as_ref().map_or_default(|w| w.tap_failures.clone()),
        };
        let actor_shapes: HashSet<u16> = timeline
            .slices()
            .iter()
            .flat_map(|slice| &slice.record.actors)
            .map(|actor| actor.shape_id)
            .collect();
        let mut streams = decoded.streams;
        streams.retain(|id, _| actor_shapes.contains(id));
        Ok((
            Self::new(timeline, decoded.shapes, world)
                .with_images(decoded.images)
                .with_relit_shapes(RelitShapes::new(streams, light)),
            report,
        ))
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

    /// The scene less every shape [`Self::frame`] can never draw. Kept are any slice's actor
    /// shapes, the world's view-facing props whatever their gates, and the origin shape;
    /// the world mesh holds its baked props' own geometry, so their shapes go.
    #[must_use]
    pub fn drawn_only(mut self) -> Self {
        let actors = self
            .timeline
            .slices()
            .iter()
            .flat_map(|slice| &slice.record.actors)
            .map(|actor| actor.shape_id);
        let props = self
            .world
            .iter()
            .flat_map(|w| &w.view_facing)
            .map(|prop| prop.shape);
        let drawn: HashSet<u16> = actors.chain(props).chain(self.origin_shape).collect();
        self.shapes.retain(|id, _| drawn.contains(id));
        self
    }

    /// Frees the world's mesh ([`World::ir`]) and its [`World::prop_runs`], keeping everything
    /// [`Self::frame`] reads.
    ///
    /// For a caller that has uploaded the mesh and goes on sampling frames. [`Self::world`] then
    /// returns the world with an empty mesh, which an upload after this draws as nothing.
    pub fn release_world_mesh(&mut self) {
        if let Some(world) = &mut self.world {
            world.ir = SodModelIr::new(&world.ir.name);
            world.prop_runs = Vec::new();
        }
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
                sprites: Vec::new(),
                view_facing: Vec::new(),
                palette: PaletteControls::default(),
                credits: None,
            };
        };
        let eye = record.camera.eye;
        let heading = camera_heading(&record.camera);
        let previous = self.previous_bank(tick, record.bank);
        let previous_actors = self
            .timeline
            .sample((tick - PREVIOUS_FRAME_TICKS).max(0.0))
            .map(|record| record.actors);
        let mut actors: Vec<ActorDraw> = record
            .actors
            .iter()
            .filter_map(|a| self.shapes.get(&a.shape_id).map(|shape| (a, shape)))
            .map(|(a, shape)| {
                let own = a.compute_world_matrix();
                let faces = faces_view(shape);
                let world_matrix = if faces {
                    lifted(facing_matrix(heading, a.position_meters), shape)
                } else {
                    lifted(own, shape)
                };
                let light = if faces {
                    self.relit.light()
                } else {
                    self.relit.light().for_actor(a.rotation_quat)
                };
                ActorDraw {
                    shape_id: a.shape_id,
                    world_matrix,
                    position: a.position_meters,
                    state_mask: a.state_mask,
                    distance: distance(eye, a.position_meters),
                    // The shadow entry `0x1C0D` builds its matrix from the slot's own angles
                    // whatever the header says (research/playone-exe/sod-vm-frame.md section 9.1).
                    shadow_matrix: a.casts_shadow.then(|| {
                        let before = previous_actors
                            .iter()
                            .flatten()
                            .find(|p| p.actor_id == a.actor_id)
                            .map_or(a.position_meters, |p| p.position_meters);
                        let top = self.shadow_top(shape, before, a.position_meters);
                        self.shadow_matrix(a.position_meters, top, &lifted(own, shape))
                    }),
                    shadow_only: a.view,
                    light,
                    bank: shape.decode().map_or(AngleBank::REST, |decode| {
                        angle_bank(tick, a.animate(), record.bank, previous)
                            .only(&decode.bank_operands)
                    }),
                }
            })
            .collect();
        let view_facing = self
            .world
            .iter()
            .flat_map(|w| &w.view_facing)
            .filter(|p| self.shapes.contains_key(&p.shape))
            .filter(|p| {
                p.gates
                    .iter()
                    .all(|gate| lod_gate_holds(&record.camera, gate))
            })
            .map(|p| ActorDraw {
                shape_id: p.shape,
                world_matrix: facing_matrix(heading, p.position),
                position: p.position,
                state_mask: 0,
                distance: distance(eye, p.position),
                shadow_matrix: None,
                shadow_only: false,
                light: self.relit.light(),
                bank: AngleBank::REST,
            })
            .collect();
        if let Some(shape_id) = self
            .origin_shape
            .filter(|_| record.actors.iter().all(|a| a.view))
        {
            actors.push(ActorDraw {
                shape_id,
                world_matrix: IDENTITY_MATRIX,
                position: [0.0; 3],
                state_mask: 0,
                distance: distance(eye, [0.0; 3]),
                shadow_matrix: None,
                shadow_only: false,
                light: self.relit.light(),
                bank: AngleBank::REST,
            });
        }
        let sprites = self.sprite_draws(
            tick,
            &record.camera,
            &record.actors,
            &actors,
            (record.bank, previous),
        );
        SceneFrame {
            tick,
            view: ViewCamera::from_authored(&record.camera),
            lens: record.camera.lens,
            world,
            actors,
            sprites,
            view_facing,
            palette: record.palette,
            credits: self.timeline.credits_at(tick).cloned(),
        }
    }

    /// The sprite draws of `draws`, the actor draws [`Self::frame`] made from `actors` in
    /// order, at `tick`, seen by `camera`.
    ///
    /// Each sprite's frame comes from its bank word ([`angle_bank`], with film variables 10
    /// and 12 at this frame and at the previous one). Only an `Always` or a
    /// matching `ActorState` gate is evaluated; a sprite under another gate is drawn, since none has
    /// been seen in a stock shape. A frame whose image the scene lacks is not drawn.
    fn sprite_draws(
        &self,
        tick: f32,
        camera: &CameraTransform,
        actors: &[ActorTransform],
        draws: &[ActorDraw],
        (now, previous): (BankVariables, BankVariables),
    ) -> Vec<SpriteDraw> {
        let drawn = actors
            .iter()
            .filter(|a| self.shapes.contains_key(&a.shape_id));
        let mut out = Vec::new();
        for (index, (actor, draw)) in drawn.zip(draws).enumerate() {
            let Some(shape) = self.shapes.get(&draw.shape_id) else {
                continue;
            };
            let mut after = None;
            for sprite in &shape.sprites {
                if draw.shadow_only || !sprite_gate_open(sprite, draw.state_mask) {
                    continue;
                }
                let phase = angle_bank(tick, actor.animate(), now, previous).word(sprite.selector);
                let Some(image_id) = sprite
                    .frame(phase)
                    .filter(|id| self.images.contains_key(id))
                else {
                    continue;
                };
                // Every sprite of a slot shares its one entry in the walk.
                let after = after
                    .get_or_insert_with(|| self.drawn_after(camera, actor, shape))
                    .clone();
                out.push(SpriteDraw {
                    image_id,
                    centre: transform_point(&draw.world_matrix, sprite.anchor),
                    size: sprite.size,
                    actor: index,
                    after,
                });
            }
        }
        out
    }

    /// The drawn world placements the scenery walk from `camera` draws after `actor`'s
    /// entry, whose shape is `shape` ([`SpriteDraw::after`]).
    fn drawn_after(
        &self,
        camera: &CameraTransform,
        actor: &ActorTransform,
        shape: &SodModelIr,
    ) -> Option<Vec<u32>> {
        let records = &self.world.as_ref()?.placements;
        let header = shape.decode()?.header;
        let entry = SlotEntry {
            position: dos_axes(actor.position_meters),
            extent: SlotEntry::extent_of(header.bounding_size, header.scale_index),
        };
        let after = records.slot_order(dos_axes(camera.eye), dos_axes(camera.target), entry)?;
        Some(
            (0u32..)
                .zip(after.iter().zip(&records.records))
                .filter(|&(_, (&after, record))| after && record.drawn)
                .map(|(index, _)| index)
                .collect(),
        )
    }

    /// Film variables 10 and 12 at the `PLAYONE` frame before the one at `tick`
    /// ([`PREVIOUS_FRAME_TICKS`] earlier, clamped to tick 0), or `now` when the timeline has
    /// no record there.
    fn previous_bank(&self, tick: f32, now: BankVariables) -> BankVariables {
        self.timeline
            .sample((tick - PREVIOUS_FRAME_TICKS).max(0.0))
            .map_or(now, |record| record.bank)
    }

    /// `ground_shadow` against this scene's world, at `top` when a collision box set one.
    fn shadow_matrix(
        &self,
        position: [f32; 3],
        top: Option<f32>,
        world_matrix: &[f32; 16],
    ) -> [f32; 16] {
        ground_shadow(self.world.as_ref(), position, top, world_matrix)
    }

    /// The height of the code-8 collision box `shape`'s slot overlaps between `previous` and
    /// `current`, if any ([`PlacementRecords::shadow_top`]).
    fn shadow_top(&self, shape: &SodModelIr, previous: [f32; 3], current: [f32; 3]) -> Option<f32> {
        let world = self.world.as_ref()?;
        let decode = shape.decode()?;
        world.placements.shadow_top(&ProbeActor {
            previous,
            current,
            extent: f32::from(decode.header.bounding_size) * decode.header.scale_factor,
            has_own_list: !decode.collision.lists.is_empty(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::VisibilityCondition;
    use crate::sod::DecodeMode;
    use crate::world::PlacementRecords;

    /// A shadowed actor over a placed object's code-8 collision box casts its shadow at the
    /// box top; one beside the box keeps the ground (`research/playone-exe/sod-vm-frame.md`
    /// section 9.1).
    #[test]
    fn a_shadow_over_a_code_8_box_lies_at_its_top() {
        use crate::contracts::{
            ActorTransform, BoxCode, CollisionBox, CollisionList, CollisionRecord, ShapeCollision,
            TrajectoryRecord,
        };
        use crate::flm::SliceKeyframe;
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};
        use crate::world::{PlacementRecord, ScnNode, TerrainSurface};

        // Bounding size 2 at one metre a unit: an extent of 2 m.
        let words = [
            OP_ID, 2, 0, 0x0000, 0, OP_IPG, 8, 2, 1, 0, OP_POLYZ, 3, 0, 12, 24,
        ];
        let bytes: Vec<u8> = words
            .iter()
            .chain(&[OP_RETURN])
            .flat_map(|w| w.to_le_bytes())
            .collect();
        let tree = decode_sod(&bytes, "TREE", None, DecodeMode::Strict).expect("decode");
        let slice = |x: f32| {
            let record = TrajectoryRecord {
                tick: 0,
                camera: CameraTransform::default(),
                actors: vec![ActorTransform {
                    actor_id: 0,
                    model_name: "TREE".to_string(),
                    shape_id: 9,
                    rotation_quat: [0.0, 0.0, 0.0, 1.0],
                    position_meters: [x, 6.5, 5.0],
                    state_mask: 0,
                    casts_shadow: true,
                    view: false,
                    joint_angles_bam: Vec::new(),
                }],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
                bank: BankVariables::default(),
            };
            FilmTimeline::new(
                vec![SliceKeyframe {
                    record,
                    tick: 0,
                    tick_duration: 1,
                }],
                Vec::new(),
            )
        };
        // DOS x and z 0 to 10 and y -6 to -2: `[I1]` x -10 to 0 and y 2 to 6, top 6.
        let top = CollisionRecord::Box(CollisionBox {
            min: [0, -6, 0],
            max: [10, -2, 10],
            code: BoxCode::Top,
        });
        let world = World {
            ir: SodModelIr::new("WORLD"),
            terrain_patches: 0,
            props_placed: 1,
            bounds: ShapeExtent {
                min: [0.0; 3],
                max: [0.0; 3],
                radius: 0.0,
            },
            scenery_stop: None,
            terrain: TerrainSurface::default(),
            tap_failures: Vec::new(),
            placements: PlacementRecords {
                records: vec![PlacementRecord {
                    shape: 5,
                    position: [0.0; 3],
                    raw: [0; 3],
                    node: ScnNode(1),
                    stand_in: false,
                    path: None,
                    collision: Some(0),
                    drawn: true,
                    mesh: None,
                }],
                steps: Vec::new(),
                collisions: vec![ShapeCollision {
                    lists: vec![CollisionList {
                        offset: 0,
                        records: vec![top],
                    }],
                    stop: None,
                }],
                collision_scales: vec![1.0],
            },
            view_facing: Vec::new(),
            prop_runs: Vec::new(),
        };
        let shadow_y = |x: f32| {
            let scene = FilmScene::new(
                slice(x),
                HashMap::from([(9, tree.clone())]),
                Some(world.clone()),
            );
            let frame = scene.frame(0.0);
            let [drawn] = frame.actors.as_slice() else {
                panic!("one actor draw");
            };
            drawn.shadow_matrix.expect("the actor casts a shadow")[13]
        };
        let lift = crate::sod::EPSILON_DISPLACEMENT;
        assert!((shadow_y(-5.0) - (6.0 + lift)).abs() < 1e-5, "over the box");
        assert!((shadow_y(-30.0) - lift).abs() < 1e-5, "beside the box");
    }

    /// A view-facing actor drops its own rotation for the camera's heading, while its
    /// shadow keeps the slot's rotation; the world's view-facing props are drawn the same
    /// way, at their own positions.
    #[test]
    fn view_facing_shapes_turn_with_the_camera_heading() {
        use crate::contracts::{ActorTransform, TrajectoryRecord};
        use crate::flm::SliceKeyframe;
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};
        use crate::world::{FacingProp, TerrainSurface};

        let words = [
            OP_ID, 100, 0, 0x0100, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24,
        ];
        let bytes: Vec<u8> = words
            .iter()
            .chain(&[OP_RETURN])
            .flat_map(|w| w.to_le_bytes())
            .collect();
        let tree = decode_sod(&bytes, "TREE", None, DecodeMode::Strict).expect("decode tree");
        // A quarter turn about +X, which the facing draw must discard.
        let half = std::f32::consts::FRAC_1_SQRT_2;
        let actor = ActorTransform {
            actor_id: 0,
            model_name: "TREE".to_string(),
            shape_id: 9,
            rotation_quat: [half, 0.0, 0.0, half],
            position_meters: [4.0, 0.0, 0.0],
            state_mask: 0,
            casts_shadow: true,
            view: false,
            joint_angles_bam: Vec::new(),
        };
        let record = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [0.0, 0.0, 8.0],
                target: [0.0, 0.0, 0.0],
                ..CameraTransform::default()
            },
            actors: vec![actor.clone()],
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
            bank: BankVariables::default(),
        };
        let timeline = FilmTimeline::new(
            vec![SliceKeyframe {
                record,
                tick: 0,
                tick_duration: 1,
            }],
            Vec::new(),
        );
        let world = World {
            ir: SodModelIr::new("WORLD"),
            terrain_patches: 0,
            props_placed: 1,
            bounds: ShapeExtent {
                min: [0.0; 3],
                max: [0.0; 3],
                radius: 0.0,
            },
            scenery_stop: None,
            terrain: TerrainSurface::default(),
            tap_failures: Vec::new(),
            placements: PlacementRecords::default(),
            view_facing: vec![
                FacingProp {
                    shape: 9,
                    position: [-2.0, 1.0, 5.0],
                    gates: Vec::new(),
                },
                // Behind the stand-in branch of a node at the eye: the near test holds there,
                // so this prop is not drawn.
                FacingProp {
                    shape: 9,
                    position: [7.0, 0.0, 0.0],
                    gates: vec![VisibilityCondition::LodBranch {
                        point: [0.0, 0.0, 8.0],
                        ext: 400,
                        splitdist: 600,
                        near: false,
                    }],
                },
            ],
            prop_runs: Vec::new(),
        };
        let scene = FilmScene::new(timeline, HashMap::from([(9, tree)]), Some(world));
        let frame = scene.frame(0.0);

        // The camera looks along -Z, so the heading is a half turn about +Y.
        let turned = |x: f32, y: f32, z: f32| {
            [
                -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, x, y, z, 1.0,
            ]
        };
        let near =
            |a: &[f32; 16], b: &[f32; 16]| a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-6);
        let [drawn] = frame.actors.as_slice() else {
            panic!("one actor draw, got {}", frame.actors.len());
        };
        assert!(near(&drawn.world_matrix, &turned(4.0, 0.0, 0.0)));
        let own = actor.compute_world_matrix();
        let shadow = drawn.shadow_matrix.expect("the actor casts a shadow");
        assert!(near(
            &shadow,
            &scene.shadow_matrix([4.0, 0.0, 0.0], None, &own)
        ));
        let [prop] = frame.view_facing.as_slice() else {
            panic!("one view-facing draw, got {}", frame.view_facing.len());
        };
        assert_eq!(prop.shape_id, 9);
        assert!(near(&prop.world_matrix, &turned(-2.0, 1.0, 5.0)));
        assert_eq!(prop.shadow_matrix, None);
        // A view-facing draw keeps the world light whatever the slot's rotation.
        assert_eq!(drawn.light, ShadeLight::WORLD_0X2D);
        assert_eq!(prop.light, ShadeLight::WORLD_0X2D);
    }

    /// Releasing the world mesh empties it and leaves the frame as it was: the world is still
    /// drawn, the actor keeps its shadow and the view-facing prop its draw.
    #[test]
    fn releasing_the_world_mesh_leaves_frames_unchanged() {
        use crate::contracts::{ActorTransform, SodVertex, TrajectoryRecord};
        use crate::flm::SliceKeyframe;
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};
        use crate::world::{FacingProp, TerrainSurface};

        let words = [
            OP_ID, 100, 0, 0x0100, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24,
        ];
        let bytes: Vec<u8> = words
            .iter()
            .chain(&[OP_RETURN])
            .flat_map(|w| w.to_le_bytes())
            .collect();
        let tree = decode_sod(&bytes, "TREE", None, DecodeMode::Strict).expect("decode tree");
        let record = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [0.0, 0.0, 8.0],
                target: [0.0, 0.0, 0.0],
                ..CameraTransform::default()
            },
            actors: vec![ActorTransform {
                actor_id: 0,
                model_name: "TREE".to_string(),
                shape_id: 9,
                rotation_quat: [0.0, 0.0, 0.0, 1.0],
                position_meters: [4.0, 0.0, 0.0],
                state_mask: 0,
                casts_shadow: true,
                view: false,
                joint_angles_bam: Vec::new(),
            }],
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
            bank: BankVariables::default(),
        };
        let timeline = FilmTimeline::new(
            vec![SliceKeyframe {
                record,
                tick: 0,
                tick_duration: 1,
            }],
            Vec::new(),
        );
        let mut mesh = SodModelIr::new("WORLD");
        let corner = SodVertex {
            position: [0.0; 3],
            normal: [0.0, 1.0, 0.0],
            palette_index: 7,
            flags: 0,
            scenery_class: 0,
            _padding: 0,
        };
        mesh.vertices = vec![corner; 3];
        mesh.indices = vec![0, 1, 2];
        let world = World {
            ir: mesh,
            terrain_patches: 0,
            props_placed: 1,
            bounds: ShapeExtent {
                min: [0.0; 3],
                max: [0.0; 3],
                radius: 0.0,
            },
            scenery_stop: None,
            terrain: TerrainSurface::default(),
            tap_failures: Vec::new(),
            placements: PlacementRecords::default(),
            view_facing: vec![FacingProp {
                shape: 9,
                position: [-2.0, 1.0, 5.0],
                gates: Vec::new(),
            }],
            prop_runs: Vec::new(),
        };
        let mut scene = FilmScene::new(timeline, HashMap::from([(9, tree)]), Some(world));
        let before = scene.frame(0.0);
        assert!(before.world, "the scene draws its world");
        assert_eq!(before.actors.len(), 1);
        assert!(before.actors.iter().all(|a| a.shadow_matrix.is_some()));
        assert_eq!(before.view_facing.len(), 1);

        scene.release_world_mesh();

        let world = scene.world().expect("the world itself stays");
        assert!(world.ir.vertices.is_empty() && world.ir.indices.is_empty());
        assert_eq!(world.ir.name, "WORLD");
        assert_eq!(scene.frame(0.0), before);
    }

    /// A rotated actor is lit by its rotation times the world light, an unrotated one by the
    /// world light, and its kept stream decodes under the world light to the scene's shape.
    #[test]
    fn a_rotated_actor_is_lit_by_its_own_rotation() {
        use crate::contracts::{ActorTransform, TrajectoryRecord};
        use crate::flm::SliceKeyframe;
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, decode_sod};

        let words = [
            OP_ID, 100, 0, 0, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24, OP_RETURN,
        ];
        let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        let shape = decode_sod(&bytes, "BOX", None, DecodeMode::Strict).expect("decode box");
        assert!(!faces_view(&shape));
        let half = std::f32::consts::FRAC_1_SQRT_2;
        let actor = |actor_id, rotation_quat| ActorTransform {
            actor_id,
            model_name: "BOX".to_string(),
            shape_id: 9,
            rotation_quat,
            position_meters: [0.0; 3],
            state_mask: 0,
            casts_shadow: false,
            view: false,
            joint_angles_bam: Vec::new(),
        };
        let pitched = [half, 0.0, 0.0, half];
        let record = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform::default(),
            actors: vec![actor(0, pitched), actor(1, [0.0, 0.0, 0.0, 1.0])],
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
            bank: BankVariables::default(),
        };
        let timeline = FilmTimeline::new(
            vec![SliceKeyframe {
                record,
                tick: 0,
                tick_duration: 1,
            }],
            Vec::new(),
        );
        let streams = HashMap::from([(9, ("BOX".to_string(), bytes))]);
        let scene = FilmScene::new(timeline, HashMap::from([(9, shape.clone())]), None)
            .with_relit_shapes(RelitShapes::new(streams, ShadeLight::WORLD_0X2D));
        let frame = scene.frame(0.0);

        let [turned, level] = frame.actors.as_slice() else {
            panic!("two actor draws, got {}", frame.actors.len());
        };
        assert_eq!(turned.light, ShadeLight::WORLD_0X2D.for_actor(pitched));
        assert_ne!(turned.light, ShadeLight::WORLD_0X2D);
        assert_eq!(level.light, ShadeLight::WORLD_0X2D);
        let relit = scene.relit_shapes();
        assert_eq!(
            relit.decode(9, ShadeLight::WORLD_0X2D, AngleBank::REST),
            Some(shape)
        );
        assert_eq!(
            relit.decode(10, ShadeLight::WORLD_0X2D, AngleBank::REST),
            None
        );
    }

    /// An actor's draw carries the bank words its shape's `ROT*` read, from film variable 10
    /// at the previous frame, and a shape with no `ROT*` draws at rest.
    #[test]
    fn an_actor_draw_carries_the_bank_words_its_shape_reads() {
        use crate::contracts::{ActorTransform, TrajectoryRecord};
        use crate::flm::SliceKeyframe;
        use crate::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, OP_ROTZ, decode_sod};

        let shape_of = |words: &[u16]| {
            let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
            decode_sod(&bytes, "PART", None, DecodeMode::Strict).expect("decode")
        };
        let quad = [OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24, OP_RETURN];
        let plain = shape_of(&[[OP_ID, 100, 0, 0, 0].as_slice(), &quad].concat());
        let turning = shape_of(&[[OP_ID, 100, 0, 0, 0, OP_ROTZ, 0x14].as_slice(), &quad].concat());
        let actor = |actor_id, shape_id| ActorTransform {
            actor_id,
            model_name: String::new(),
            shape_id,
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [0.0; 3],
            state_mask: 0,
            casts_shadow: false,
            view: false,
            joint_angles_bam: Vec::new(),
        };
        let slice = |tick: u32, var10: u16| SliceKeyframe {
            record: TrajectoryRecord {
                tick,
                camera: CameraTransform::default(),
                actors: vec![actor(0, 1), actor(1, 2)],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
                bank: BankVariables { var10, var12: 9 },
            },
            tick,
            tick_duration: 10,
        };
        let timeline = FilmTimeline::new(vec![slice(0, 0x0100), slice(10, 0x0200)], Vec::new());
        let scene = FilmScene::new(timeline, HashMap::from([(1, plain), (2, turning)]), None);
        // Var 10 climbs 25.6 a tick; with no lag word 0x14 takes it at tick 8, 0x0100 + 204.
        let frame = scene.frame(8.0);
        let [still, turned] = frame.actors.as_slice() else {
            panic!("two actor draws, got {}", frame.actors.len());
        };
        assert_eq!(still.bank, AngleBank::REST);
        assert_eq!(turned.bank, AngleBank::new([0, 0, 0xCC00, 0, 0, 0]));
    }

    /// A drawn-only scene keeps every actor shape of every slice and every view-facing prop,
    /// one reachable only behind a level-of-detail gate included, and nothing else.
    #[test]
    fn a_drawn_only_scene_keeps_the_actor_and_view_facing_shapes() {
        use crate::contracts::{ActorTransform, TrajectoryRecord};
        use crate::flm::SliceKeyframe;
        use crate::world::{FacingProp, TerrainSurface};

        let slice = |tick: u32, shape_id: u16| SliceKeyframe {
            record: TrajectoryRecord {
                tick,
                camera: CameraTransform::default(),
                actors: vec![ActorTransform {
                    actor_id: 0,
                    model_name: String::new(),
                    shape_id,
                    rotation_quat: [0.0, 0.0, 0.0, 1.0],
                    position_meters: [0.0; 3],
                    state_mask: 0,
                    casts_shadow: false,
                    view: false,
                    joint_angles_bam: Vec::new(),
                }],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
                bank: BankVariables::default(),
            },
            tick,
            tick_duration: 1,
        };
        // Shape 7 is an actor's but missing from the scene, so nothing can draw it.
        let timeline = FilmTimeline::new(vec![slice(0, 1), slice(10, 2), slice(20, 7)], Vec::new());
        let world = World {
            ir: SodModelIr::new("WORLD"),
            terrain_patches: 0,
            props_placed: 1,
            bounds: ShapeExtent {
                min: [0.0; 3],
                max: [0.0; 3],
                radius: 0.0,
            },
            scenery_stop: None,
            terrain: TerrainSurface::default(),
            tap_failures: Vec::new(),
            placements: PlacementRecords::default(),
            // A tree standing only behind the near branch of a level-of-detail node.
            view_facing: vec![FacingProp {
                shape: 3,
                position: [0.0; 3],
                gates: vec![VisibilityCondition::LodBranch {
                    point: [0.0; 3],
                    ext: 400,
                    splitdist: 600,
                    near: true,
                }],
            }],
            prop_runs: Vec::new(),
        };
        let shapes = (1..=4).map(|id| (id, SodModelIr::new("SHAPE"))).collect();
        let scene = FilmScene::new(timeline, shapes, Some(world));

        let mut drawn: Vec<u16> = scene.drawn_only().shapes().map(|(id, _)| id).collect();
        drawn.sort_unstable();
        assert_eq!(drawn, [1, 2, 3]);
    }
}

//! The film scene: the timeline bound to its shapes and world, and the frame it draws.

use std::collections::{HashMap, HashSet};

use crate::anchor::parse_anchor_table;
use crate::contracts::trajectory::DEFAULT_CAMERA_LENS;
use crate::contracts::{ActorTransform, CameraTransform, PaletteControls, ShapeExtent, SodModelIr};
use crate::credits::CreditLines;
use crate::flm::{FilmTimeline, FlmError};
use crate::font::PFont;
use crate::link::LinkError;
use crate::sod::{ShadeLight, faces_view};
use crate::sprite::SpriteImage;
use crate::vfs::VfsError;
use crate::world::{ScnStop, TapFailure, World, WorldInputs, build_world};

use super::projection::{
    IDENTITY_MATRIX, ViewCamera, camera_heading, distance, facing_matrix, lifted, lod_gate_holds,
    max_magnification, min_corner_depth, transform_point,
};
use super::shadow::ground_shadow;
use super::shapes::{
    ArchiveShapes, ShapeSource, SkippedChunk, decode_archive_shapes, decode_res_shapes,
};
use super::sprite::{bank_word, sprite_gate_open};

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

/// One image an actor's shape draws in screen space (`OP_ANIMATE`) in a [`SceneFrame`].
///
/// `PLAYONE` blits it as a square `size` across at the anchor's projected point, palette
/// index 0 transparent, with no depth test of its own (`research/playone-exe/sod-animate.md`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SpriteDraw {
    /// Image resource of the frame, a key of [`FilmScene::image`].
    pub image_id: u16,
    /// Centre of the square in world `[I1]` metres.
    pub centre: [f32; 3],
    /// Side of the square in metres.
    pub size: f32,
    /// Index into [`SceneFrame::actors`] of the actor whose shape draws it.
    pub actor: usize,
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
        }
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
        let anchors = inputs.anchors.map_or_default(parse_anchor_table);

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
        Ok((
            Self::new(timeline, decoded.shapes, world).with_images(decoded.images),
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
        let mut actors: Vec<ActorDraw> = record
            .actors
            .iter()
            .filter_map(|a| self.shapes.get(&a.shape_id).map(|shape| (a, shape)))
            .map(|(a, shape)| {
                let own = a.compute_world_matrix();
                let world_matrix = if faces_view(shape) {
                    lifted(facing_matrix(heading, a.position_meters), shape)
                } else {
                    lifted(own, shape)
                };
                ActorDraw {
                    shape_id: a.shape_id,
                    world_matrix,
                    state_mask: a.state_mask,
                    distance: distance(eye, a.position_meters),
                    // The shadow entry `0x1C0D` builds its matrix from the slot's own angles
                    // whatever the header says (research/playone-exe/sod-vm.md section 9.1).
                    shadow_matrix: a
                        .casts_shadow
                        .then(|| self.shadow_matrix(a.position_meters, &lifted(own, shape))),
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
                state_mask: 0,
                distance: distance(eye, p.position),
                shadow_matrix: None,
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
        let sprites = self.sprite_draws(tick, &record.actors, &actors);
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
    /// order, at `tick`.
    ///
    /// Each sprite's frame comes from its bank word ([`bank_word`]). Only an `Always` or a
    /// matching `ActorState` gate is evaluated; a sprite under another gate is drawn, since none has
    /// been seen in a stock shape. A frame whose image the scene lacks is not drawn.
    fn sprite_draws(
        &self,
        tick: f32,
        actors: &[ActorTransform],
        draws: &[ActorDraw],
    ) -> Vec<SpriteDraw> {
        let drawn = actors
            .iter()
            .filter(|a| self.shapes.contains_key(&a.shape_id));
        let mut out = Vec::new();
        for (index, (actor, draw)) in drawn.zip(draws).enumerate() {
            let Some(shape) = self.shapes.get(&draw.shape_id) else {
                continue;
            };
            for sprite in &shape.sprites {
                if !sprite_gate_open(sprite, draw.state_mask) {
                    continue;
                }
                let phase = bank_word(sprite.selector, tick, actor.animate());
                let Some(image_id) = sprite
                    .frame(phase)
                    .filter(|id| self.images.contains_key(id))
                else {
                    continue;
                };
                out.push(SpriteDraw {
                    image_id,
                    centre: transform_point(&draw.world_matrix, sprite.anchor),
                    size: sprite.size,
                    actor: index,
                });
            }
        }
        out
    }

    /// The shadow matrix of an actor at `position` drawn through `world_matrix`.
    ///
    /// PLAYONE solves one ground plane at the actor's x and z (`0x19FC`) and flattens the
    /// whole object onto it (`0x1C0D`), so every vertex lands on that plane, not on the
    /// terrain under its own x and z. The plane here is the terrain triangle under the
    /// origin; with no world it is `y = 0`, as for PLAYONE's null plane (`0x1A12`).
    fn shadow_matrix(&self, position: [f32; 3], world_matrix: &[f32; 16]) -> [f32; 16] {
        ground_shadow(self.world.as_ref(), position, world_matrix)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::VisibilityCondition;
    use crate::sod::DecodeMode;

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
        assert!(near(&shadow, &scene.shadow_matrix([4.0, 0.0, 0.0], &own)));
        let [prop] = frame.view_facing.as_slice() else {
            panic!("one view-facing draw, got {}", frame.view_facing.len());
        };
        assert_eq!(prop.shape_id, 9);
        assert!(near(&prop.world_matrix, &turned(-2.0, 1.0, 5.0)));
        assert_eq!(prop.shadow_matrix, None);
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
                    joint_angles_bam: Vec::new(),
                }],
                audio_cues: Vec::new(),
                palette: PaletteControls::default(),
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
        };
        let shapes = (1..=4).map(|id| (id, SodModelIr::new("SHAPE"))).collect();
        let scene = FilmScene::new(timeline, shapes, Some(world));

        let mut drawn: Vec<u16> = scene.drawn_only().shapes().map(|(id, _)| id).collect();
        drawn.sort_unstable();
        assert_eq!(drawn, [1, 2, 3]);
    }
}

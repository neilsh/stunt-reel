//! Draws a [`SceneFrame`] of a [`FilmScene`]: the world plus one draw per actor.
//!
//! Every shape is uploaded once. An actor whose light differs from the scene's
//! ([`stunt_core::scene::ActorDraw::light`]), or whose shape's parts are turned by the angle
//! bank ([`stunt_core::scene::ActorDraw::bank`]), draws its own copy of its shape decoded under
//! that light and bank, since `OP_SHADES` bakes the light into the colours and the `ROT*`
//! opcodes turn the parts as the shape decodes; the copy is kept while the actor draws the same
//! shape, and a new light or bank rewrites its vertices only when they change.
//! Each draw, the world's included, gets its own per-draw uniform, a [`ModelUniform`] at its
//! own dynamic offset in one uniform buffer, so two actors sharing a shape render at their own
//! poses within one render pass. Its matrix is eye-relative ([`eye_relative_matrix`]): the
//! camera uniform carries no translation. [`SceneRenderer::prepare`] uploads every per-draw
//! uniform of a frame with one `Queue::write_buffer` before the pass is submitted, never one per
//! draw (`research/parity/lavapipe-render-time.md`).
//!
//! Frame use is two-phase because a render pass borrows its bind groups: call
//! [`SceneRenderer::prepare`] (uploads camera and matrices, may grow the uniform buffer), then
//! [`SceneRenderer::draw`] inside the pass. Opaque base meshes of every draw precede the
//! decal meshes of every draw per `[I5]`, which write no depth, so a later decal covers an
//! earlier one wherever both pass against the base. An actor that casts a shadow gets a second draw of
//! its shape, flattened onto the ground and filled in palette index 0, which lies on the
//! terrain and so goes in the decal pass whole, through a pipeline that culls no faces.
//!
//! A sprite (`OP_ANIMATE`, [`SpriteDraw`]) is its image uploaded once as a unit square of
//! one quad per run of equal pixels, index 0 left out, drawn through a per-draw uniform whose matrix
//! turns the square to face the camera at the sprite's centre and size, in its actor's layer.
//! A sprite the scenery walk gives a place ([`SpriteDraw::after`]) is drawn after every other
//! draw, with no depth test, then the world's props the walk draws after it are drawn again
//! from their own runs of the world mesh, so they cover it; the world's main draw leaves them
//! out. The world stays depth-tested throughout (`research/parity/painter-order.md`).
//!
//! A view-facing prop whose box ([`GpuModel::bounds`]) lies wholly outside the view frustum is
//! skipped, as the world's off-screen nodes are, since it would cover no pixel
//! ([`GpuModel::in_frustum`] keeps a prop with discs under a lens other than the default; the
//! world's walk keeps a node whose subtree holds discs likewise).
//!
//! Complies with `[I1]` (frames arrive in right-handed metres) and `[I5]`.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use glam::{Mat4, Vec3};

use stunt_core::contracts::{
    CameraTransform, NodeKind, SCENERY_OCEAN, SCENERY_TERRAIN, SodModelIr, SodVertex,
    VERTEX_FLAG_PRESHADED, VisibilityCondition,
};
use stunt_core::scene::{FilmScene, RelitShapes, SceneFrame, SpriteDraw};
use stunt_core::sod::{AngleBank, ShadeLight};
use stunt_core::sprite::SpriteImage;
use stunt_core::world::{ArenaSpan, MeshSpans, World};

use crate::camera::{CameraController, CameraGpuResources, eye_relative_matrix};
use crate::mesh::{GpuMeshSlice, GpuModel, prop_runs_group};
use crate::outline::{Outlined, outlined};
use crate::palette::PaletteLut;
use crate::pipeline::{
    LAYER_FIRST_ACTOR, LAYER_PROP, ModelUniform, PROP_RUNS_GROUP, RenderPipelines,
};
use crate::renderer::UploadTimes;
use stunt_core::contracts::{NodeId, SodNode, arena_index};

/// Which uploaded model a prepared draw uses.
#[derive(Clone, Copy, Debug)]
enum Target {
    /// The static world, drawn through the per-draw uniform with this index.
    World { uniform: usize },
    /// An actor shape drawn through the per-draw uniform with this index.
    Shape { shape_id: u16, uniform: usize },
    /// The actor with this index in the frame, drawn from its shape decoded under its own
    /// light through the per-draw uniform with this index.
    Lit { actor: usize, uniform: usize },
    /// A sprite's image drawn through the per-draw uniform with this index.
    Image { image_id: u16, uniform: usize },
}

/// Sprites at one place in the scenery walk, then the world's props the walk draws after
/// them and before the next place, and the actors nearer the eye than the sprites.
#[derive(Debug)]
struct WalkStep {
    /// The sprites, drawn with no depth test.
    sprites: Vec<PreparedDraw>,
    /// The props, through the world's uniform.
    props: PreparedDraw,
    /// The actors whose view depth is less than the sprites' slot's and not less than the
    /// next step's (`PLAYONE`'s entry sort draws the larger depth first).
    actors: Vec<PreparedDraw>,
}

/// Where the world mesh holds each placement, for drawing some apart from the rest.
#[derive(Debug, Default)]
struct WorldPlacements {
    /// The `WORLD_BASE` node, whose one slice holds the ungated props' base triangles, and
    /// its index run (`stunt_core::world` builds both).
    base: Option<(NodeId, ArenaSpan)>,
    /// The `WORLD_DECAL` node, which holds their decals, and its index run.
    decal: Option<(NodeId, ArenaSpan)>,
    /// Each placement record's spans, in record order.
    spans: Vec<Option<MeshSpans>>,
    /// The record each node was made for alone, by node id.
    owner: Vec<Option<u32>>,
}

impl WorldPlacements {
    fn new(world: &World) -> Self {
        let mesh_node = |name: &str| {
            world
                .ir
                .nodes
                .iter()
                .find(|n| n.name == name)
                .and_then(|n| {
                    let NodeKind::Mesh {
                        index_offset,
                        index_count,
                        ..
                    } = n.kind
                    else {
                        return None;
                    };
                    let end = index_offset.checked_add(index_count)?;
                    Some((
                        n.id,
                        ArenaSpan {
                            start: index_offset,
                            end,
                        },
                    ))
                })
        };
        let spans: Vec<Option<MeshSpans>> =
            world.placements.records.iter().map(|r| r.mesh).collect();
        let mut owner = vec![None; world.ir.nodes.len()];
        for (record, span) in (0u32..).zip(&spans) {
            for node in span.iter().flat_map(|s| s.nodes.start..s.nodes.end) {
                if let Some(slot) = owner.get_mut(node as usize) {
                    *slot = Some(record);
                }
            }
        }
        Self {
            base: mesh_node("WORLD_BASE"),
            decal: mesh_node("WORLD_DECAL"),
            spans,
            owner,
        }
    }

    /// Where the world's base and decal slices may be cut, ascending: their ends and every
    /// placement's span ends in them.
    fn marks(&self) -> Vec<u32> {
        let nodes = [self.base, self.decal].into_iter().flatten();
        let mut marks: Vec<u32> = nodes
            .flat_map(|(_, run)| [run.start, run.end])
            .chain(
                self.spans
                    .iter()
                    .flatten()
                    .flat_map(|s| [s.base.start, s.base.end, s.decal.start, s.decal.end]),
            )
            .collect();
        marks.sort_unstable();
        marks.dedup();
        marks
    }

    /// The world draw's base or decal slices (`decals`), each with its node, less the props
    /// `rank` puts after a sprite, which go to `steps` by rank (rank 1 to the first); `None`
    /// when `cut` (a node, then the start and end of the run of indices to keep) cannot cut a
    /// slice there.
    fn split(
        &self,
        slices: Vec<(NodeId, GpuMeshSlice)>,
        rank: &[usize],
        decals: bool,
        steps: &mut [Vec<GpuMeshSlice>],
        cut: impl Fn(NodeId, u32, u32) -> Option<GpuMeshSlice>,
    ) -> Option<Vec<GpuMeshSlice>> {
        let batch = if decals { self.decal } else { self.base };
        let mut kept = Vec::with_capacity(slices.len());
        for (node, slice) in slices {
            if batch.is_some_and(|(id, _)| id == node) {
                let moved = (0..).zip(&self.spans).filter_map(|(record, spans)| {
                    let span = spans.map(|s| if decals { s.decal } else { s.base })?;
                    let rank = rank.get(record).copied().unwrap_or(0);
                    (rank > 0 && !span.is_empty()).then_some((span, rank))
                });
                kept.extend(cut_out(slice, moved, steps, |start, end| {
                    cut(node, start, end)
                })?);
                continue;
            }
            let owner = self.owner.get(node.0 as usize).copied().flatten();
            let rank = owner
                .and_then(|r| rank.get(r as usize))
                .copied()
                .unwrap_or(0);
            match rank.checked_sub(1).and_then(|step| steps.get_mut(step)) {
                Some(step) => step.push(slice),
                None => kept.push(slice),
            }
        }
        Some(kept)
    }
}

/// `whole` less the `moved` spans (ascending, each with its rank), which go to `steps` by
/// rank; `whole` itself when none moves. `None` when `cut` cannot cut `whole` at a span's
/// ends.
fn cut_out(
    whole: GpuMeshSlice,
    moved: impl Iterator<Item = (ArenaSpan, usize)>,
    steps: &mut [Vec<GpuMeshSlice>],
    cut: impl Fn(u32, u32) -> Option<GpuMeshSlice>,
) -> Option<Vec<GpuMeshSlice>> {
    let end = whole.index_offset.checked_add(whole.index_count)?;
    let mut at = whole.index_offset;
    let mut kept = Vec::new();
    for (span, rank) in moved {
        if span.start < at || span.end > end {
            return None;
        }
        if span.start > at {
            kept.push(cut(at, span.start)?);
        }
        steps
            .get_mut(rank.checked_sub(1)?)?
            .push(cut(span.start, span.end)?);
        at = span.end;
    }
    if at == whole.index_offset {
        return Some(vec![whole]);
    }
    if at < end {
        kept.push(cut(at, end)?);
    }
    Some(kept)
}

/// One draw ready to encode: visible ground, base and decal slices of a target.
#[derive(Debug)]
struct PreparedDraw {
    target: Target,
    /// The world's flat-ground slices in draw order; empty for every other target.
    ground: Vec<GpuMeshSlice>,
    base: Vec<GpuMeshSlice>,
    decals: Vec<GpuMeshSlice>,
    /// A ground shadow, drawn through the shadow pipeline, which culls no faces.
    shadow: bool,
}

/// A frame's per-draw uniforms: [`ModelUniform`]s `stride` bytes apart, staged during
/// `prepare` and uploaded with one `write_buffer` to a uniform buffer that one bind group
/// shows at each one's dynamic offset.
#[derive(Debug)]
struct DrawUniforms {
    /// Bytes between uniforms: a [`ModelUniform`] rounded up to the device's uniform offset
    /// alignment.
    stride: usize,
    /// This frame's uniforms, packed `stride` apart.
    staged: Vec<u8>,
    /// `None` until a frame has a uniform to upload.
    gpu: Option<DrawUniformBuffer>,
}

/// The uniform buffer behind [`DrawUniforms`], `capacity` uniforms long, and its bind group.
#[derive(Debug)]
struct DrawUniformBuffer {
    buffer: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    capacity: usize,
}

impl DrawUniforms {
    fn new(device: &wgpu::Device) -> Self {
        Self {
            stride: size_of::<ModelUniform>()
                .next_multiple_of(device.limits().min_uniform_buffer_offset_alignment as usize),
            staged: Vec::new(),
            gpu: None,
        }
    }

    /// Empties the staged uniforms for a new frame.
    fn clear(&mut self) {
        self.staged.clear();
    }

    /// Stages `uniform` after the others and returns its index.
    fn push(&mut self, uniform: &ModelUniform) -> usize {
        let index = self.staged.len() / self.stride;
        self.staged.extend_from_slice(bytemuck::bytes_of(uniform));
        self.staged.resize((index + 1) * self.stride, 0);
        index
    }

    /// Writes the staged uniforms with one `write_buffer`, first growing the buffer to the next
    /// power of two that holds them (at least double its capacity); it never shrinks.
    fn upload(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        layout: &wgpu::BindGroupLayout,
    ) {
        let needed = self.staged.len() / self.stride;
        if needed == 0 {
            return;
        }
        let capacity = self.gpu.as_ref().map_or(0, |gpu| gpu.capacity);
        if needed > capacity {
            let capacity = needed.next_power_of_two().max(capacity * 2);
            self.gpu = Some(self.new_buffer(device, layout, capacity));
        }
        if let Some(gpu) = &self.gpu {
            queue.write_buffer(&gpu.buffer, 0, &self.staged);
        }
    }

    /// The bind group and dynamic offset of uniform `index`; `None` before any upload, or
    /// for an offset past `u32`.
    fn binding(&self, index: usize) -> Option<(&wgpu::BindGroup, u32)> {
        let offset = u32::try_from(index * self.stride).ok()?;
        Some((&self.gpu.as_ref()?.bind_group, offset))
    }

    fn new_buffer(
        &self,
        device: &wgpu::Device,
        layout: &wgpu::BindGroupLayout,
        capacity: usize,
    ) -> DrawUniformBuffer {
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_scene_actor_model_uniforms"),
            size: (capacity * self.stride) as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("stunt_scene_actor_model_bind_group"),
            layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                    buffer: &buffer,
                    offset: 0,
                    size: ModelUniform::BINDING_SIZE,
                }),
            }],
        });
        DrawUniformBuffer {
            buffer,
            bind_group,
            capacity,
        }
    }
}

/// What a new decode of an actor's lit shape asks of the model its slot holds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Refresh {
    /// The decode equals what the model holds.
    Keep,
    /// Only the vertices differ: the model's indices, nodes and slices still fit them.
    Rewrite,
    /// Another shape, or the decode's indices or nodes differ (welding and outlines can
    /// move them at equal counts): upload a new model.
    Upload,
}

/// The decode a lit model was uploaded from, less what the GPU keeps of it.
#[derive(Debug)]
struct LitLayout {
    shape_id: u16,
    vertices: Vec<SodVertex>,
    indices: Vec<u32>,
    nodes: Vec<SodNode>,
}

impl LitLayout {
    fn of(shape_id: u16, ir: &SodModelIr) -> Self {
        Self {
            shape_id,
            vertices: ir.vertices.clone(),
            indices: ir.indices.clone(),
            nodes: ir.nodes.clone(),
        }
    }

    /// What `ir`, shape `shape_id` decoded again, asks of a model uploaded from `self`.
    fn refresh(&self, shape_id: u16, ir: &SodModelIr) -> Refresh {
        if self.shape_id != shape_id
            || self.vertices.len() != ir.vertices.len()
            || self.indices != ir.indices
            || self.nodes != ir.nodes
        {
            Refresh::Upload
        } else if self.vertices == ir.vertices {
            Refresh::Keep
        } else {
            Refresh::Rewrite
        }
    }
}

/// The light and angle bank an actor's shape is decoded under.
type Pose = (ShadeLight, AngleBank);

/// An actor's shape decoded under the actor's own light and bank, with the decode last
/// uploaded.
#[derive(Debug)]
struct LitShape {
    pose: Pose,
    layout: LitLayout,
    model: GpuModel,
}

impl LitShape {
    /// Uploads `shape`, shape `shape_id` decoded under `pose` and outlined, as a model of its own.
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        shape_id: u16,
        pose: Pose,
        shape: &Outlined,
    ) -> Self {
        Self {
            pose,
            layout: LitLayout::of(shape_id, &shape.ir),
            model: GpuModel::from_outlined(device, queue, shape),
        }
    }
}

/// GPU renderer for the scene frames of one [`FilmScene`].
#[derive(Debug)]
pub(crate) struct SceneRenderer {
    shapes: HashMap<u16, GpuModel>,
    /// Every sprite image of the scene as a unit square ([`sprite_ir`]).
    images: HashMap<u16, GpuModel>,
    world: Option<GpuModel>,
    /// The actors' shape streams, decoded again under each actor's own light and bank.
    relit: RelitShapes,
    /// Each actor's shape decoded under its own light and bank, by actor index in the frame;
    /// `None` for an actor drawn under the scene's light at rest.
    lit: Vec<Option<LitShape>>,
    uniforms: DrawUniforms,
    model_layout: wgpu::BindGroupLayout,
    /// The prop runs bound before any world chunk binds its own, which hold no run, so a
    /// draw of the plane pipelines before the world's has its group; `None` without a plane.
    no_prop_runs: Option<wgpu::BindGroup>,
    prepared: Vec<PreparedDraw>,
    /// Where the world mesh holds each placement.
    placements: WorldPlacements,
    /// The frame's sprites the scenery walk places, in walk order, drawn after
    /// [`Self::prepared`].
    steps: Vec<WalkStep>,
    /// How long [`Self::new`] spent uploading the shapes and the world.
    upload_times: UploadTimes,
}

impl SceneRenderer {
    /// Uploads every shape and the world of `scene`.
    #[must_use]
    pub(crate) fn new(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipelines: &RenderPipelines,
        scene: &FilmScene,
    ) -> Self {
        let layout = &pipelines.model_bind_group_layout;
        // Shapes drawn per frame (actors and view-facing props such as the flat trees) take
        // their polygon outlines as line quads; the world mesh takes its props' outlines as a
        // line list over its own vertices, which quads would multiply about five times
        // (research/playone-exe/sod-vm-lines-spans.md section 8.11).
        let shapes_started = Instant::now();
        let shapes = scene
            .shapes()
            .map(|(id, ir)| (id, GpuModel::from_outlined(device, queue, &outlined(ir))))
            .collect();
        let images = scene
            .images()
            .map(|(id, image)| (id, GpuModel::from_ir(device, queue, &sprite_ir(image))))
            .collect();
        let shapes_time = shapes_started.elapsed();
        let world_started = Instant::now();
        let placements = scene.world().map_or_default(WorldPlacements::new);
        let mut world = scene.world().map(|w| {
            GpuModel::from_ir_outlined(device, queue, &w.ir, outlines_in_world, &placements.marks())
        });
        // The plane's shape word finds a world prop's shape in the world's prop runs.
        let prop_runs_layout = pipelines.prop_runs_layout.as_ref();
        if let Some((layout, (model, w))) = prop_runs_layout.zip(world.as_mut().zip(scene.world()))
        {
            model.attach_prop_runs(device, layout, &w.prop_runs);
        }
        let world_time = if world.is_some() {
            world_started.elapsed()
        } else {
            Duration::ZERO
        };
        // The placeholder bind group is allocated whether or not there is a world, so it is
        // outside the world's span.
        let no_prop_runs = prop_runs_layout.map(|layout| prop_runs_group(device, layout, &[]));
        Self {
            shapes,
            images,
            world,
            relit: scene.relit_shapes().clone(),
            lit: Vec::new(),
            uniforms: DrawUniforms::new(device),
            model_layout: layout.clone(),
            no_prop_runs,
            prepared: Vec::new(),
            placements,
            steps: Vec::new(),
            upload_times: UploadTimes {
                shapes: shapes_time,
                world: world_time,
            },
        }
    }

    /// How long [`Self::new`] spent uploading the shapes and the world.
    pub(crate) fn upload_times(&self) -> UploadTimes {
        self.upload_times
    }

    /// Uploads the camera and per-draw matrices for `frame` and selects visible meshes.
    ///
    /// The camera is `frame.view` unless `camera` overrides it (e.g. a free camera);
    /// an override does not change the per-actor LOD distances carried by the frame. Facing
    /// gates are tested against the eye of the camera that renders: the override's when
    /// there is one, otherwise `frame.view.eye`.
    /// Actors whose shape was not uploaded are skipped.
    pub(crate) fn prepare(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        camera_resources: &CameraGpuResources,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) {
        let mut authored = CameraController::default();
        authored.set_authored_transform(frame.view);
        let controller = camera.unwrap_or(&authored);
        let camera_uniform = controller.build_uniform_with_sky(frame.palette.sky);
        camera_resources.upload(queue, &camera_uniform);
        camera_resources.upload_look(queue, frame.palette.sky, controller);
        let rotation_proj = Mat4::from_cols_array(&camera_uniform.rotation_proj);

        self.prepared.clear();
        self.steps.clear();
        self.uniforms.clear();
        let eye = controller.eye_position();
        let mut world_slices = None;
        if frame.world
            && let Some(world) = &self.world
        {
            // The world's own matrix, and with the camera's the one its vertices reach clip
            // space by, in the shader's order: the cull sees what the draw would.
            let world_matrix = eye_relative_matrix(eye, &Mat4::IDENTITY.to_cols_array());
            let view_proj = rotation_proj * Mat4::from_cols_array(&world_matrix);
            let (ground, base, decals) = {
                let lod_view = CameraTransform {
                    eye: frame.view.eye,
                    target: frame.view.target,
                    lens: frame.lens,
                    ..CameraTransform::default()
                };
                world.collect_world_meshes(
                    eye,
                    Some(&lod_view),
                    view_proj,
                    camera_uniform.disc_depth_scale,
                )
            };
            let uniform = self.uniforms.push(&ModelUniform::new(world_matrix, 0));
            let untag =
                |tagged: &[(NodeId, GpuMeshSlice)]| tagged.iter().map(|&(_, m)| m).collect();
            self.prepared.push(PreparedDraw {
                target: Target::World { uniform },
                ground,
                base: untag(&base),
                decals: untag(&decals),
                shadow: false,
            });
            world_slices = Some((self.prepared.len() - 1, base, decals));
        }

        for prop in &frame.view_facing {
            let Some(model) = self.shapes.get(&prop.shape_id) else {
                continue;
            };
            // A prop whose box is off screen draws no pixel, so it is skipped before its
            // walk; the box is tested by the matrix its vertices reach clip space by.
            let model_matrix = eye_relative_matrix(eye, &prop.world_matrix);
            if !model.in_frustum(
                rotation_proj * Mat4::from_cols_array(&model_matrix),
                camera_uniform.disc_depth_scale,
            ) {
                continue;
            }
            let to_model = Mat4::from_cols_array(&prop.world_matrix).inverse();
            let local_eye = to_model.transform_point3(eye);
            let view = model_view(&to_model, frame);
            let meshes = model.collect_visible_meshes(
                prop.state_mask,
                prop.distance,
                local_eye,
                Some(&view),
            );
            if meshes.0.is_empty() && meshes.1.is_empty() {
                continue;
            }
            let shape_id = prop.shape_id;
            let uniform = ModelUniform::new(model_matrix, LAYER_PROP).with_shape(shape_id);
            self.push_draw(
                |uniform| Target::Shape { shape_id, uniform },
                &uniform,
                meshes,
            );
        }
        // Each slot's depth along the view axis, as `PLAYONE`'s entry sort compares actors: at
        // the slot's position, not the model matrix's lifted origin
        // (research/playone-exe/scene-walk-actors.md section 6).
        let back = controller.compute_view_matrix().row(2).truncate();
        let actor_depths: Vec<f32> = frame
            .actors
            .iter()
            .map(|a| (eye - Vec3::from_array(a.position)).dot(back))
            .collect();
        let mut actor_draws = Vec::new();
        self.lit.resize_with(frame.actors.len(), || None);
        for ((actor_index, actor), slot) in (0u32..).zip(&frame.actors).zip(0usize..) {
            // A slot drawn under the scene's light at rest keeps its model for the actor's next
            // turn.
            let lit = (actor.light != self.relit.light() || actor.bank != AngleBank::REST)
                && self.relight(
                    device,
                    queue,
                    slot,
                    actor.shape_id,
                    (actor.light, actor.bank),
                );
            let model = if lit {
                self.lit
                    .get(slot)
                    .and_then(Option::as_ref)
                    .map(|l| &l.model)
            } else {
                self.shapes.get(&actor.shape_id)
            };
            let Some(model) = model else {
                continue;
            };
            let to_model = Mat4::from_cols_array(&actor.world_matrix).inverse();
            let local_eye = to_model.transform_point3(eye);
            let view = model_view(&to_model, frame);
            let (base, decals) = model.collect_visible_meshes(
                actor.state_mask,
                actor.distance,
                local_eye,
                Some(&view),
            );
            // The shadow draw's facing gates test the flattened faces, as `PLAYONE`'s `REJ`
            // does, so it holds faces the eye-side lists lack (the view slot's, whose eye is
            // inside its shape).
            let shadow = actor.shadow_matrix.map(|matrix| {
                let relative = eye_relative_matrix(eye, &matrix);
                let (base, decals) = model.collect_shadow_meshes(
                    actor.state_mask,
                    actor.distance,
                    Mat4::from_cols_array(&relative),
                    Some(&view),
                );
                (relative, base.into_iter().chain(decals).collect::<Vec<_>>())
            });
            if base.is_empty()
                && decals.is_empty()
                && shadow.as_ref().is_none_or(|(_, m)| m.is_empty())
            {
                continue;
            }
            let layer = LAYER_FIRST_ACTOR + actor_index;
            // The shadow lies on the terrain, so all of it is a decal [I5]. PLAYONE's entry
            // sort (`0x1B88`) paints every shadow before every actor; here the depth test
            // keeps the actor in front of its shadow where the two overlap
            // (research/playone-exe/sod-vm-frame.md section 9.1).
            let shape_id = actor.shape_id;
            let target = |uniform| {
                if lit {
                    Target::Lit {
                        actor: slot,
                        uniform,
                    }
                } else {
                    Target::Shape { shape_id, uniform }
                }
            };
            if let Some((relative, meshes)) = shadow {
                let uniform = ModelUniform::shadow(relative, layer);
                self.push_draw(target, &uniform, (Vec::new(), meshes));
            }
            if actor.shadow_only {
                continue;
            }
            let uniform = ModelUniform::new(eye_relative_matrix(eye, &actor.world_matrix), layer);
            self.push_draw(target, &uniform, (base, decals));
            if let Some(&depth) = actor_depths.get(slot) {
                actor_draws.push((self.prepared.len() - 1, depth));
            }
        }

        // Sprites have no shadow: `PLAYONE` skips `OP_ANIMATE` in the shadow pass.
        let view = controller.compute_view_matrix();
        let mut placed = Vec::new();
        for sprite in &frame.sprites {
            let Some(model) = self.images.get(&sprite.image_id) else {
                continue;
            };
            let (base, decals) = model.collect_visible_meshes(0, 0.0, eye, None);
            let layer = LAYER_FIRST_ACTOR + u32::try_from(sprite.actor).unwrap_or(u32::MAX);
            let uniform = ModelUniform::new(
                eye_relative_matrix(eye, &billboard_matrix(&view, sprite)),
                layer,
            );
            let image_id = sprite.image_id;
            let draw = self.stage(
                |uniform| Target::Image { image_id, uniform },
                &uniform,
                (base, decals),
            );
            match (&sprite.after, actor_depths.get(sprite.actor)) {
                (Some(after), Some(&depth)) => {
                    let distance = (Vec3::from_array(sprite.centre) - eye).length();
                    placed.push((after.as_slice(), depth, distance, draw));
                }
                _ => self.prepared.push(draw),
            }
        }
        self.place_sprites(placed, world_slices, &actor_draws);
        self.uniforms.upload(device, queue, &self.model_layout);
    }

    /// Puts `placed`, the sprites the scenery walk places (each with the placements it draws
    /// after the sprite, its slot's view depth and its centre's distance from the eye), in
    /// [`Self::steps`] in walk order with the
    /// props drawn after each, and takes those props out of the world's draw, whose base and
    /// decal slices `world` gives with their nodes. Each of `actors` (an index into
    /// [`Self::prepared`] and the actor's view depth) nearer than a placed sprite's slot
    /// leaves [`Self::prepared`] for the step of the last such sprite.
    ///
    /// A sprite the walk draws earlier has more props after it, of two with as many the one
    /// whose centre is farther first; a prop goes after as many sprites as place it after
    /// them. That keeps the walk's order when the sprites' sets of props after them nest, as
    /// they do for sprites of one slot; for sprites of different slots it approximates it. When there is
    /// no world draw or its slices cannot be cut, the sprites are drawn as unplaced ones.
    #[expect(
        clippy::type_complexity,
        reason = "the world draw's index and its two tagged slice lists, as prepare collects them"
    )]
    fn place_sprites(
        &mut self,
        mut placed: Vec<(&[u32], f32, f32, PreparedDraw)>,
        world: Option<(
            usize,
            Vec<(NodeId, GpuMeshSlice)>,
            Vec<(NodeId, GpuMeshSlice)>,
        )>,
        actors: &[(usize, f32)],
    ) {
        if placed.is_empty() {
            return;
        }
        placed.sort_by(|a, b| b.0.len().cmp(&a.0.len()).then(b.2.total_cmp(&a.2)));
        let mut rank = vec![0usize; self.placements.spans.len()];
        for (after, _, _, _) in &placed {
            for &record in *after {
                if let Some(r) = rank.get_mut(record as usize) {
                    *r += 1;
                }
            }
        }
        let cut = world
            .zip(self.world.as_ref())
            .and_then(|((at, base, decals), model)| {
                let mut base_steps = vec![Vec::new(); placed.len()];
                let mut decal_steps = vec![Vec::new(); placed.len()];
                let cut = |node, start, end| model.cut(node, start, end);
                let base = self
                    .placements
                    .split(base, &rank, false, &mut base_steps, cut)?;
                let decals = self
                    .placements
                    .split(decals, &rank, true, &mut decal_steps, cut)?;
                Some((at, base, decals, base_steps.into_iter().zip(decal_steps)))
            });
        let Some((at, base, decals, props)) = cut else {
            self.prepared
                .extend(placed.into_iter().map(|(_, _, _, draw)| draw));
            return;
        };
        let Some(world) = self.prepared.get_mut(at) else {
            self.prepared
                .extend(placed.into_iter().map(|(_, _, _, draw)| draw));
            return;
        };
        world.base = base;
        world.decals = decals;
        let target = world.target;
        // Each actor goes after the last sprite in walk order whose slot is deeper than it.
        let depths: Vec<f32> = placed.iter().map(|&(_, depth, _, _)| depth).collect();
        let mut step_of: Vec<Option<usize>> = vec![None; self.prepared.len()];
        for &(index, depth) in actors {
            if let Some(slot) = step_of.get_mut(index) {
                *slot = depths.iter().rposition(|&sprite| depth < sprite);
            }
        }
        let mut moved: Vec<Vec<PreparedDraw>> = std::iter::repeat_with(Vec::new)
            .take(placed.len())
            .collect();
        let mut kept = Vec::with_capacity(self.prepared.len());
        for (draw, step) in self.prepared.drain(..).zip(step_of) {
            match step.and_then(|s| moved.get_mut(s)) {
                Some(step) => step.push(draw),
                None => kept.push(draw),
            }
        }
        self.prepared = kept;
        for (((_, _, _, sprite), (base, decals)), actors) in
            placed.into_iter().zip(props).zip(moved)
        {
            self.steps.push(WalkStep {
                sprites: vec![sprite],
                props: PreparedDraw {
                    target,
                    ground: Vec::new(),
                    base,
                    decals,
                    shadow: false,
                },
                actors,
            });
        }
    }

    /// Whether actor `slot`'s shape `shape_id` decoded under `pose` is in `self.lit`,
    /// decoding it first if not.
    ///
    /// The slot's model is kept while a new decode keeps its shape, indices and nodes
    /// ([`LitLayout::refresh`]): a new pose then rewrites its vertices, and only when they
    /// changed. False, with the slot cleared, when the scene keeps no stream for the shape or
    /// it fails to decode; the actor then draws the shape uploaded at start-up.
    fn relight(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        slot: usize,
        shape_id: u16,
        pose: Pose,
    ) -> bool {
        let Some(entry) = self.lit.get_mut(slot) else {
            return false;
        };
        if entry
            .as_ref()
            .is_some_and(|lit| lit.layout.shape_id == shape_id && lit.pose == pose)
        {
            return true;
        }
        let Some(ir) = self.relit.decode(shape_id, pose.0, pose.1) else {
            *entry = None;
            return false;
        };
        let shape = outlined(&ir);
        if let Some(lit) = entry.as_mut() {
            match lit.layout.refresh(shape_id, &shape.ir) {
                Refresh::Keep => {
                    lit.pose = pose;
                    return true;
                }
                Refresh::Rewrite if lit.model.rewrite_vertices(queue, &shape) => {
                    lit.pose = pose;
                    lit.layout.vertices = shape.ir.vertices;
                    return true;
                }
                Refresh::Rewrite | Refresh::Upload => {}
            }
        }
        *entry = Some(LitShape::upload(device, queue, shape_id, pose, &shape));
        true
    }

    /// Queues a draw of the target `target` names for the next per-draw uniform, filled with
    /// `uniform`, and its `(base, decals)` mesh slices through it.
    fn push_draw(
        &mut self,
        target: impl FnOnce(usize) -> Target,
        uniform: &ModelUniform,
        meshes: (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>),
    ) {
        let draw = self.stage(target, uniform, meshes);
        self.prepared.push(draw);
    }

    /// [`Self::push_draw`]'s draw, its uniform staged, without queueing it.
    fn stage(
        &mut self,
        target: impl FnOnce(usize) -> Target,
        uniform: &ModelUniform,
        (base, decals): (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>),
    ) -> PreparedDraw {
        let index = self.uniforms.push(uniform);
        let [_, shadow, ..] = uniform.layer;
        PreparedDraw {
            target: target(index),
            ground: Vec::new(),
            base,
            decals,
            shadow: shadow != 0,
        }
    }

    /// Encodes the draws chosen by the last [`Self::prepare`] into `rpass`.
    ///
    /// The pass must target the formats `pipelines` was built for.
    pub(crate) fn draw(
        &self,
        rpass: &mut wgpu::RenderPass<'_>,
        pipelines: &RenderPipelines,
        camera_resources: &CameraGpuResources,
        palette: &PaletteLut,
    ) {
        rpass.set_pipeline(&pipelines.sky_pipeline);
        rpass.set_bind_group(0, &camera_resources.bind_group, &[]);
        rpass.set_bind_group(1, &palette.bind_group, &[]);
        rpass.draw(0..3, 0..1);
        // Each world chunk binds its own runs as it draws ([`GpuModel::draw_slices`]); any
        // other model's vertices are no world prop's, so whichever runs are bound go unread.
        if let Some(runs) = &self.no_prop_runs {
            rpass.set_bind_group(PROP_RUNS_GROUP, runs, &[]);
        }

        // The world's flat ground first, each slice over what is there, then its outline:
        // a run of lines that follows is a slice of its own, so no outline covers it.
        let world_ground = self.prepared.iter().find_map(|draw| match draw.target {
            Target::World { uniform } if !draw.ground.is_empty() => {
                Some((self.world.as_ref()?, draw, self.uniforms.binding(uniform)?))
            }
            _ => None,
        });
        if let Some((world, draw, (bind_group, offset))) = world_ground {
            rpass.set_bind_group(2, bind_group, &[offset]);
            for slice in &draw.ground {
                let slices = std::slice::from_ref(slice);
                rpass.set_pipeline(&pipelines.ground_pipeline);
                world.draw_slices(rpass, slices);
                if slice.edge_count > 0 {
                    rpass.set_pipeline(&pipelines.ground_edge_pipeline);
                    world.draw_edges(rpass, slices);
                }
            }
        }

        rpass.set_bind_group(0, &camera_resources.bind_group, &[]);
        rpass.set_bind_group(1, &palette.bind_group, &[]);
        for decal_pass in [false, true] {
            for draw in &self.prepared {
                self.encode(rpass, pipelines, draw, decal_pass, &pipelines.base_pipeline);
            }
        }
        // Each placed sprite over everything drawn so far, then the props the scenery walk
        // draws after it and the actors nearer than it, depth-tested against the world.
        for step in &self.steps {
            for sprite in &step.sprites {
                self.encode(rpass, pipelines, sprite, false, &pipelines.sprite_pipeline);
            }
            for decal_pass in [false, true] {
                for draw in std::iter::once(&step.props).chain(&step.actors) {
                    self.encode(rpass, pipelines, draw, decal_pass, &pipelines.base_pipeline);
                }
            }
        }
    }

    /// The model, bind group and dynamic offset `target` draws through; `None` when the
    /// model or the uniform is missing.
    fn resolve(&self, target: Target) -> Option<(&GpuModel, &wgpu::BindGroup, u32)> {
        let (model, uniform) = match target {
            Target::World { uniform } => (self.world.as_ref()?, uniform),
            Target::Shape { shape_id, uniform } => (self.shapes.get(&shape_id)?, uniform),
            Target::Lit { actor, uniform } => (&self.lit.get(actor)?.as_ref()?.model, uniform),
            Target::Image { image_id, uniform } => (self.images.get(&image_id)?, uniform),
        };
        let (bind_group, offset) = self.uniforms.binding(uniform)?;
        Some((model, bind_group, offset))
    }

    /// Encodes `draw`'s decal slices when `decal_pass`, else its base slices through `base`,
    /// with the world's outlines after its slices.
    fn encode(
        &self,
        rpass: &mut wgpu::RenderPass<'_>,
        pipelines: &RenderPipelines,
        draw: &PreparedDraw,
        decal_pass: bool,
        base: &wgpu::RenderPipeline,
    ) {
        let meshes = if decal_pass { &draw.decals } else { &draw.base };
        if meshes.is_empty() {
            return;
        }
        let Some((model, bind_group, offset)) = self.resolve(draw.target) else {
            return;
        };
        rpass.set_bind_group(2, bind_group, &[offset]);
        let world = matches!(draw.target, Target::World { .. });
        if decal_pass {
            // A world decal slice's outline follows its own fill, so a later slice covers
            // it as it covers the fill: the decal pass writes no depth to hide it ([I5]).
            if world {
                for slice in meshes {
                    let slices = std::slice::from_ref(slice);
                    rpass.set_pipeline(&pipelines.decal_pipeline);
                    model.draw_slices(rpass, slices);
                    if slice.edge_count > 0 {
                        rpass.set_pipeline(&pipelines.edge_decal_pipeline);
                        model.draw_edges(rpass, slices);
                    }
                }
                return;
            }
            // A shadow is all decal, drawn through a pipeline that culls no faces.
            rpass.set_pipeline(if draw.shadow {
                &pipelines.shadow_pipeline
            } else {
                &pipelines.decal_pipeline
            });
            model.draw_slices(rpass, meshes);
            return;
        }
        rpass.set_pipeline(base);
        model.draw_slices(rpass, meshes);
        // Only the world carries edge buffers.
        if world {
            rpass.set_pipeline(&pipelines.edge_pipeline);
            model.draw_edges(rpass, meshes);
        }
    }
}

/// `frame`'s camera taken into a model's space by `to_model`, the inverse of its world
/// matrix, for the gates that test depth along the view axis.
fn model_view(to_model: &Mat4, frame: &SceneFrame) -> CameraTransform {
    CameraTransform {
        eye: to_model
            .transform_point3(Vec3::from_array(frame.view.eye))
            .to_array(),
        target: to_model
            .transform_point3(Vec3::from_array(frame.view.target))
            .to_array(),
        lens: frame.lens,
        ..CameraTransform::default()
    }
}

/// The matrix that draws [`sprite_ir`]'s unit square as `sprite`: facing the camera whose
/// view matrix is `view`, `size` across, centred on its centre.
///
/// The square lies in the view plane, so it is `size` wide and tall on screen at the
/// centre's depth, as `PLAYONE` blits it (`research/playone-exe/sod-animate.md`).
fn billboard_matrix(view: &Mat4, sprite: &SpriteDraw) -> [f32; 16] {
    let right = view.row(0).truncate() * sprite.size;
    let up = view.row(1).truncate() * sprite.size;
    let back = view.row(2).truncate();
    let centre = Vec3::from_array(sprite.centre);
    Mat4::from_cols(
        right.extend(0.0),
        up.extend(0.0),
        back.extend(0.0),
        centre.extend(1.0),
    )
    .to_cols_array()
}

/// `image` as a unit square in the `z = 0` plane, `x` right and `y` up from `-0.5` to `0.5`:
/// one quad per run of equal pixels, wound clockwise seen from `+z`, as the base pipeline
/// keeps, with index 0 left out as `PLAYONE`'s blitter skips it.
fn sprite_ir(image: &SpriteImage) -> SodModelIr {
    let mut ir = SodModelIr::new("SPRITE");
    let (width, height) = (f32::from(image.width), f32::from(image.height));
    for run in image.runs() {
        let x0 = f32::from(run.start) / width - 0.5;
        let x1 = f32::from(run.end) / width - 0.5;
        let top = 0.5 - f32::from(run.row) / height;
        let bottom = 0.5 - (f32::from(run.row) + 1.0) / height;
        let first = arena_index(ir.vertices.len());
        for [x, y] in [[x0, bottom], [x0, top], [x1, top], [x1, bottom]] {
            ir.vertices.push(SodVertex {
                position: [x, y, 0.0],
                normal: [0.0, 0.0, 1.0],
                palette_index: run.index,
                // Drawn art, not a lit surface: a lighting look leaves it as it is.
                flags: VERTEX_FLAG_PRESHADED,
                scenery_class: 0,
                decal_tie: 0,
            });
        }
        ir.indices
            .extend([0, 1, 2, 0, 2, 3].map(|corner| first + corner));
    }
    let root = ir.allocate_node(
        "SPRITE",
        None,
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    ir.allocate_node(
        "PIXELS",
        Some(root),
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: arena_index(ir.vertices.len()),
            index_offset: 0,
            index_count: arena_index(ir.indices.len()),
            is_decal: false,
        },
    );
    ir
}

/// Whether a world triangle with the corner `vertex` is outlined: a prop's filled polygon
/// ([`crate::outline::outlines`]), not terrain or ocean. Outlining terrain and ocean as well
/// scored lower on `LAND` and `BALLOON` (`work/2026-11/430_world-mesh-slivers/journal.md`).
fn outlines_in_world(vertex: &SodVertex) -> bool {
    crate::outline::outlines(vertex)
        && vertex.scenery_class != SCENERY_TERRAIN
        && vertex.scenery_class != SCENERY_OCEAN
}

#[cfg(test)]
mod tests {
    use super::{LitLayout, Refresh};
    use stunt_core::contracts::{NodeKind, SodModelIr, SodVertex, VisibilityCondition};

    /// Two triangles over four vertices, each vertex at palette index `colour`, drawn by
    /// `indices`.
    fn quad(colour: u8, indices: [u32; 6]) -> SodModelIr {
        let vertex = |x: f32, y: f32| SodVertex {
            position: [x, y, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: colour,
            flags: 0,
            scenery_class: 0,
            decal_tie: 0,
        };
        let mut ir = SodModelIr::new("QUAD");
        ir.vertices = vec![
            vertex(0.0, 0.0),
            vertex(1.0, 0.0),
            vertex(1.0, 1.0),
            vertex(0.0, 1.0),
        ];
        ir.indices = indices.to_vec();
        ir.allocate_node(
            "QUAD",
            None,
            Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 4,
                index_offset: 0,
                index_count: 6,
                is_decal: false,
            },
        );
        ir
    }

    const ONE_DIAGONAL: [u32; 6] = [0, 2, 1, 0, 3, 2];
    const OTHER_DIAGONAL: [u32; 6] = [0, 3, 1, 1, 3, 2];

    /// The same decode keeps the model, as the old renderer's one upload per shape did.
    #[test]
    fn an_unchanged_decode_keeps_the_model() {
        let layout = LitLayout::of(9, &quad(40, ONE_DIAGONAL));
        assert_eq!(layout.refresh(9, &quad(40, ONE_DIAGONAL)), Refresh::Keep);
    }

    /// New colours over the same indices and nodes rewrite the vertices in place.
    #[test]
    fn new_colours_over_the_same_indices_rewrite_the_vertices() {
        let layout = LitLayout::of(9, &quad(40, ONE_DIAGONAL));
        assert_eq!(layout.refresh(9, &quad(41, ONE_DIAGONAL)), Refresh::Rewrite);
    }

    /// Indices that differ at equal vertex and index counts, as welding by palette index and
    /// the outlines can make them, upload a new model rather than rebinding the old indices.
    #[test]
    fn other_indices_at_equal_counts_upload_a_new_model() {
        let layout = LitLayout::of(9, &quad(40, ONE_DIAGONAL));
        let moved = quad(41, OTHER_DIAGONAL);
        assert_eq!(moved.indices.len(), layout.indices.len());
        assert_eq!(moved.vertices.len(), layout.vertices.len());
        assert_eq!(layout.refresh(9, &moved), Refresh::Upload);
        assert_eq!(
            layout.refresh(9, &quad(40, OTHER_DIAGONAL)),
            Refresh::Upload,
            "equal vertices do not save other indices"
        );
    }

    /// Another shape in the slot uploads a new model.
    #[test]
    fn another_shape_uploads_a_new_model() {
        let layout = LitLayout::of(9, &quad(40, ONE_DIAGONAL));
        assert_eq!(layout.refresh(10, &quad(40, ONE_DIAGONAL)), Refresh::Upload);
    }

    use super::*;

    /// A slice of indices `start..end`, as an unsplit model's cut gives it.
    fn run(start: u32, end: u32) -> GpuMeshSlice {
        GpuMeshSlice {
            chunk: 0,
            vertex_offset: 0,
            index_offset: start,
            index_count: end - start,
            is_decal: false,
            edge_offset: 0,
            edge_count: 0,
        }
    }

    fn span(start: u32, end: u32) -> ArenaSpan {
        ArenaSpan { start, end }
    }

    /// A world whose base slice `0..30` holds three props, at `6..12`, `12..18` and
    /// `24..30`, and whose node 5 was made for the third alone.
    fn three_props() -> WorldPlacements {
        let spans = |base: ArenaSpan, nodes: ArenaSpan| MeshSpans {
            base,
            decal: ArenaSpan::default(),
            nodes,
        };
        WorldPlacements {
            base: Some((NodeId(0), span(0, 30))),
            decal: None,
            spans: vec![
                Some(spans(span(6, 12), ArenaSpan::default())),
                Some(spans(span(12, 18), ArenaSpan::default())),
                Some(spans(span(24, 30), span(5, 6))),
                None,
            ],
            owner: vec![None, None, None, None, None, Some(2)],
        }
    }

    #[test]
    fn props_after_a_sprite_leave_the_world_draw_for_its_step() {
        let world = three_props();
        let slices = vec![(NodeId(0), run(0, 30)), (NodeId(5), run(40, 43))];
        let mut steps = vec![Vec::new(), Vec::new()];
        // The second prop follows one sprite, the third both.
        let kept = world.split(slices, &[0, 1, 2, 0], false, &mut steps, |_, a, b| {
            Some(run(a, b))
        });
        assert_eq!(kept, Some(vec![run(0, 12), run(18, 24)]));
        assert_eq!(steps, [vec![run(12, 18)], vec![run(24, 30), run(40, 43)]]);
    }

    #[test]
    fn a_slice_no_prop_leaves_is_kept_whole_and_uncut() {
        let world = three_props();
        let mut steps = vec![Vec::new()];
        let kept = world.split(
            vec![(NodeId(0), run(0, 30))],
            &[0, 0, 0, 0],
            false,
            &mut steps,
            |_, _, _| None,
        );
        assert_eq!(kept, Some(vec![run(0, 30)]));
        assert!(steps[0].is_empty());
    }

    #[test]
    fn a_slice_the_model_cannot_cut_gives_no_split() {
        let world = three_props();
        let mut steps = vec![Vec::new()];
        let kept = world.split(
            vec![(NodeId(0), run(0, 30))],
            &[1, 0, 0, 0],
            false,
            &mut steps,
            |_, _, _| None,
        );
        assert_eq!(kept, None);
    }

    #[test]
    fn sprite_square_has_one_clockwise_quad_per_run() {
        // Row 0: two 5s then a 0; row 1: a 7 then two 0s.
        let image = SpriteImage {
            width: 3,
            height: 2,
            pixels: vec![5, 5, 0, 7, 0, 0],
        };
        let ir = sprite_ir(&image);
        assert_eq!(ir.vertices.len(), 8);
        assert_eq!(ir.indices.len(), 12);
        let corners: Vec<[f32; 3]> = ir.vertices.iter().map(|v| v.position).collect();
        let third = 1.0 / 3.0;
        assert_eq!(corners[0], [-0.5, 0.0, 0.0]);
        assert_eq!(corners[2], [2.0 * third - 0.5, 0.5, 0.0]);
        assert_eq!(ir.vertices[0].palette_index, 5);
        assert_eq!(ir.vertices[4].palette_index, 7);
        // Clockwise from +z: the z of (b - a) x (c - b) is negative.
        for tri in ir.indices.as_chunks::<3>().0 {
            let [a, b, c] = tri.map(|i| corners[i as usize]);
            let cross_z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
            assert!(cross_z < 0.0, "triangle {tri:?} winds counter-clockwise");
        }
        assert_eq!(ir.meshes().count(), 1);
    }

    #[test]
    fn billboard_faces_the_camera_at_the_sprite_centre() {
        // A camera at +z looking down -z: right is +x, up +y.
        let mut camera = CameraController::default();
        camera.set_authored_transform(stunt_core::scene::ViewCamera {
            eye: [0.0, 0.0, 10.0],
            target: [0.0; 3],
            fov_degrees: 60.0,
            roll_radians: 0.0,
        });
        let view = camera.compute_view_matrix();
        let sprite = SpriteDraw {
            image_id: 1,
            centre: [1.0, 2.0, 3.0],
            size: 4.0,
            actor: 0,
            after: None,
        };
        let m = Mat4::from_cols_array(&billboard_matrix(&view, &sprite));
        let top_right = m.transform_point3(Vec3::new(0.5, 0.5, 0.0));
        assert!((top_right - Vec3::new(3.0, 4.0, 3.0)).length() < 1e-5);
        let normal = m.transform_vector3(Vec3::Z);
        assert!(
            (normal - Vec3::Z).length() < 1e-5,
            "the square faces the eye"
        );
    }
}

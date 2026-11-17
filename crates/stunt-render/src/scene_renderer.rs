//! Draws a [`SceneFrame`] of a [`FilmScene`]: the world plus one draw per actor.
//!
//! Every shape is uploaded once. An actor whose light differs from the scene's
//! ([`stunt_core::scene::ActorDraw::light`]) draws its own copy of its shape decoded under that
//! light, since `OP_SHADES` bakes the light into the colours; the copy is kept while the actor
//! draws the same shape, and a new light rewrites its vertices only when their colours change.
//! Each draw, the world's included, gets its own per-draw uniform, a [`ModelUniform`] at its
//! own dynamic offset in one uniform buffer, so two actors sharing a shape render at their own
//! poses within one render pass. Its matrix is eye-relative ([`eye_relative_matrix`]): the
//! camera uniform carries no translation. [`SceneRenderer::prepare`] uploads every per-draw
//! uniform of a frame with one `Queue::write_buffer` before the pass is submitted, never one per
//! draw (`research/parity/lavapipe.md`).
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
//!
//! Complies with `[I1]` (frames arrive in right-handed metres) and `[I5]`.

use std::collections::HashMap;

use glam::{Mat4, Vec3};

use stunt_core::contracts::{
    CameraTransform, NodeKind, SCENERY_OCEAN, SCENERY_TERRAIN, SodModelIr, SodVertex,
    VERTEX_FLAG_LINE, VisibilityCondition,
};
use stunt_core::scene::{FilmScene, RelitShapes, SceneFrame, SpriteDraw};
use stunt_core::sod::ShadeLight;
use stunt_core::sprite::SpriteImage;

use crate::camera::{CameraController, CameraGpuResources, eye_relative_matrix};
use crate::mesh::{GpuMeshSlice, GpuModel};
use crate::outline::with_outlines;
use crate::palette::PaletteLut;
use crate::pipeline::{LAYER_FIRST_ACTOR, LAYER_PROP, ModelUniform, RenderPipelines};
use stunt_core::contracts::{SodNode, arena_index};

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

/// An actor's shape decoded under the actor's own light, with the decode last uploaded.
#[derive(Debug)]
struct LitShape {
    light: ShadeLight,
    layout: LitLayout,
    model: GpuModel,
}

impl LitShape {
    /// Uploads `ir`, shape `shape_id` decoded under `light`, as a model of its own.
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        shape_id: u16,
        light: ShadeLight,
        ir: &SodModelIr,
    ) -> Self {
        Self {
            light,
            layout: LitLayout::of(shape_id, ir),
            model: GpuModel::from_ir(device, queue, ir),
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
    /// The actors' shape streams, decoded again under each actor's own light.
    relit: RelitShapes,
    /// Each actor's shape decoded under its own light, by actor index in the frame; `None`
    /// for an actor drawn under the scene's light.
    lit: Vec<Option<LitShape>>,
    uniforms: DrawUniforms,
    model_layout: wgpu::BindGroupLayout,
    prepared: Vec<PreparedDraw>,
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
        // (research/playone-exe/sod-vm-generators.md section 8.11).
        let shapes = scene
            .shapes()
            .map(|(id, ir)| (id, GpuModel::from_ir(device, queue, &with_outlines(ir))))
            .collect();
        let images = scene
            .images()
            .map(|(id, image)| (id, GpuModel::from_ir(device, queue, &sprite_ir(image))))
            .collect();
        let world = scene
            .world()
            .map(|w| GpuModel::from_ir_outlined(device, queue, &w.ir, outlines_in_world));
        Self {
            shapes,
            images,
            world,
            relit: scene.relit_shapes().clone(),
            lit: Vec::new(),
            uniforms: DrawUniforms::new(device),
            model_layout: layout.clone(),
            prepared: Vec::new(),
        }
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
        let camera_uniform = controller.build_uniform();
        camera_resources.upload(queue, &camera_uniform);

        self.prepared.clear();
        self.uniforms.clear();
        let eye = controller.eye_position();
        if frame.world
            && let Some(world) = &self.world
        {
            // The world's own matrix, and with the camera's the one its vertices reach clip
            // space by, in the shader's order: the cull sees what the draw would.
            let world_matrix = eye_relative_matrix(eye, &Mat4::IDENTITY.to_cols_array());
            let view_proj = Mat4::from_cols_array(&camera_uniform.rotation_proj)
                * Mat4::from_cols_array(&world_matrix);
            let (ground, base, decals) = {
                let lod_view = CameraTransform {
                    eye: frame.view.eye,
                    target: frame.view.target,
                    lens: frame.lens,
                    ..CameraTransform::default()
                };
                world.collect_world_meshes(eye, Some(&lod_view), view_proj)
            };
            let uniform = self.uniforms.push(&ModelUniform::new(world_matrix, 0));
            self.prepared.push(PreparedDraw {
                target: Target::World { uniform },
                ground,
                base,
                decals,
                shadow: false,
            });
        }

        for prop in &frame.view_facing {
            let Some(model) = self.shapes.get(&prop.shape_id) else {
                continue;
            };
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
            let uniform =
                ModelUniform::new(eye_relative_matrix(eye, &prop.world_matrix), LAYER_PROP);
            let shape_id = prop.shape_id;
            self.push_draw(
                |uniform| Target::Shape { shape_id, uniform },
                &uniform,
                meshes,
            );
        }
        self.lit.resize_with(frame.actors.len(), || None);
        for ((actor_index, actor), slot) in (0u32..).zip(&frame.actors).zip(0usize..) {
            // A slot drawn under the scene's light keeps its model for the actor's next turn.
            let lit = actor.light != self.relit.light()
                && self.relight(device, queue, slot, actor.shape_id, actor.light);
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
            if base.is_empty() && decals.is_empty() {
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
            if let Some(shadow_matrix) = actor.shadow_matrix {
                let uniform = ModelUniform::shadow(eye_relative_matrix(eye, &shadow_matrix), layer);
                let shadow = base.iter().chain(&decals).copied().collect();
                self.push_draw(target, &uniform, (Vec::new(), shadow));
            }
            let uniform = ModelUniform::new(eye_relative_matrix(eye, &actor.world_matrix), layer);
            self.push_draw(target, &uniform, (base, decals));
        }

        // Sprites have no shadow: `PLAYONE` skips `OP_ANIMATE` in the shadow pass.
        let view = controller.compute_view_matrix();
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
            self.push_draw(
                |uniform| Target::Image { image_id, uniform },
                &uniform,
                (base, decals),
            );
        }
        self.uniforms.upload(device, queue, &self.model_layout);
    }

    /// Whether actor `slot`'s shape `shape_id` lit by `light` is in `self.lit`, decoding it
    /// first if not.
    ///
    /// The slot's model is kept while a new decode keeps its shape, indices and nodes
    /// ([`LitLayout::refresh`]): a new light then rewrites its vertices, and only when they
    /// changed. False, with the slot cleared, when the scene keeps no stream for the shape or
    /// it fails to decode; the actor then draws the shape uploaded at start-up.
    fn relight(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        slot: usize,
        shape_id: u16,
        light: ShadeLight,
    ) -> bool {
        let Some(entry) = self.lit.get_mut(slot) else {
            return false;
        };
        if entry
            .as_ref()
            .is_some_and(|lit| lit.layout.shape_id == shape_id && lit.light == light)
        {
            return true;
        }
        let Some(ir) = self.relit.decode(shape_id, light) else {
            *entry = None;
            return false;
        };
        let ir = with_outlines(&ir);
        if let Some(lit) = entry.as_mut() {
            match lit.layout.refresh(shape_id, &ir) {
                Refresh::Keep => {
                    lit.light = light;
                    return true;
                }
                Refresh::Rewrite if lit.model.rewrite_vertices(queue, &ir) => {
                    lit.light = light;
                    lit.layout.vertices = ir.vertices;
                    return true;
                }
                Refresh::Rewrite | Refresh::Upload => {}
            }
        }
        *entry = Some(LitShape::upload(device, queue, shape_id, light, &ir));
        true
    }

    /// Queues a draw of the target `target` names for the next per-draw uniform, filled with
    /// `uniform`, and its `(base, decals)` mesh slices through it.
    fn push_draw(
        &mut self,
        target: impl FnOnce(usize) -> Target,
        uniform: &ModelUniform,
        (base, decals): (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>),
    ) {
        let index = self.uniforms.push(uniform);
        let [_, shadow, ..] = uniform.layer;
        self.prepared.push(PreparedDraw {
            target: target(index),
            ground: Vec::new(),
            base,
            decals,
            shadow: shadow != 0,
        });
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

        for decal_pass in [false, true] {
            rpass.set_pipeline(if decal_pass {
                &pipelines.decal_pipeline
            } else {
                &pipelines.base_pipeline
            });
            rpass.set_bind_group(0, &camera_resources.bind_group, &[]);
            rpass.set_bind_group(1, &palette.bind_group, &[]);
            for draw in &self.prepared {
                let meshes = if decal_pass { &draw.decals } else { &draw.base };
                if meshes.is_empty() {
                    continue;
                }
                // A shadow is all decal, so only the decal pass switches pipelines.
                if decal_pass {
                    rpass.set_pipeline(if draw.shadow {
                        &pipelines.shadow_pipeline
                    } else {
                        &pipelines.decal_pipeline
                    });
                }
                let (model, bind_group, offset) = match draw.target {
                    Target::World { uniform } => {
                        match self.world.as_ref().zip(self.uniforms.binding(uniform)) {
                            Some((w, (bind_group, offset))) => (w, bind_group, offset),
                            None => continue,
                        }
                    }
                    Target::Shape { shape_id, uniform } => {
                        match self
                            .shapes
                            .get(&shape_id)
                            .zip(self.uniforms.binding(uniform))
                        {
                            Some((m, (bind_group, offset))) => (m, bind_group, offset),
                            None => continue,
                        }
                    }
                    Target::Lit { actor, uniform } => {
                        match self
                            .lit
                            .get(actor)
                            .and_then(Option::as_ref)
                            .zip(self.uniforms.binding(uniform))
                        {
                            Some((lit, (bind_group, offset))) => (&lit.model, bind_group, offset),
                            None => continue,
                        }
                    }
                    Target::Image { image_id, uniform } => {
                        match self
                            .images
                            .get(&image_id)
                            .zip(self.uniforms.binding(uniform))
                        {
                            Some((m, (bind_group, offset))) => (m, bind_group, offset),
                            None => continue,
                        }
                    }
                };
                rpass.set_bind_group(2, bind_group, &[offset]);
                // A world decal slice's outline follows its own fill, so a later slice covers
                // it as it covers the fill: the decal pass writes no depth to hide it ([I5]).
                if decal_pass && matches!(draw.target, Target::World { .. }) {
                    for slice in meshes {
                        let slices = std::slice::from_ref(slice);
                        rpass.set_pipeline(&pipelines.decal_pipeline);
                        model.draw_slices(rpass, slices);
                        if slice.edge_count > 0 {
                            rpass.set_pipeline(&pipelines.edge_decal_pipeline);
                            model.draw_edges(rpass, slices);
                        }
                    }
                    continue;
                }
                model.draw_slices(rpass, meshes);
                // Only the world carries edge buffers; the next draw sets its own pipeline
                // back, as the decal pass does per draw and the base pass needs only here.
                if matches!(draw.target, Target::World { .. }) {
                    rpass.set_pipeline(if decal_pass {
                        &pipelines.edge_decal_pipeline
                    } else {
                        &pipelines.edge_pipeline
                    });
                    model.draw_edges(rpass, meshes);
                    if !decal_pass {
                        rpass.set_pipeline(&pipelines.base_pipeline);
                    }
                }
            }
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
                flags: 0,
                scenery_class: 0,
                _padding: 0,
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

/// Whether a world triangle with the corner `vertex` is outlined: a prop's filled polygon,
/// not a line, terrain or ocean. Outlining terrain and ocean as well scored lower on `LAND`
/// and `BALLOON` (`work/2026-11/430_world-mesh-slivers/journal.md`).
fn outlines_in_world(vertex: &SodVertex) -> bool {
    vertex.flags & VERTEX_FLAG_LINE == 0
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
            _padding: 0,
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

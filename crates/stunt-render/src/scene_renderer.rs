//! Draws a [`SceneFrame`] of a [`FilmScene`]: the world plus one draw per actor.
//!
//! Every shape is uploaded once. Each actor draw gets its own model-matrix slot (a 64-byte
//! uniform buffer and bind group), grown on demand during [`SceneRenderer::prepare`], so
//! two actors sharing a shape render at their own poses within one render pass. Slots are
//! filled with `Queue::write_buffer` before the pass is submitted, never between draws.
//!
//! Frame use is two-phase because a render pass borrows its bind groups: call
//! [`SceneRenderer::prepare`] (uploads camera and matrices, may allocate slots), then
//! [`SceneRenderer::draw`] inside the pass. Opaque base meshes of every draw precede the
//! decal meshes of every draw per `[I5]`.
//!
//! Complies with `[I1]` (frames arrive in right-handed metres) and `[I5]`.

use std::collections::HashMap;

use stunt_core::scene::{FilmScene, SceneFrame};

use crate::camera::{CameraController, CameraGpuResources};
use crate::mesh::{GpuMeshSlice, GpuModel};
use crate::palette::PaletteLut;
use crate::pipeline::{LAYER_FIRST_ACTOR, ModelUniform, RenderPipelines};

/// Which uploaded model a prepared draw uses.
#[derive(Clone, Copy, Debug)]
enum Target {
    /// The static world, drawn with its own identity bind group.
    World,
    /// An actor shape drawn through the model-matrix slot with this index.
    Shape { shape_id: u16, slot: usize },
}

/// One draw ready to encode: visible base and decal slices of a target.
#[derive(Debug)]
struct PreparedDraw {
    target: Target,
    base: Vec<GpuMeshSlice>,
    decals: Vec<GpuMeshSlice>,
}

/// A per-draw model matrix: uniform buffer plus its bind group.
#[derive(Debug)]
struct MatrixSlot {
    buffer: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
}

/// GPU renderer for the scene frames of one [`FilmScene`].
#[derive(Debug)]
pub struct SceneRenderer {
    shapes: HashMap<u16, GpuModel>,
    world: Option<GpuModel>,
    slots: Vec<MatrixSlot>,
    model_layout: wgpu::BindGroupLayout,
    prepared: Vec<PreparedDraw>,
}

impl SceneRenderer {
    /// Uploads every shape and the world of `scene`; the world keeps an identity matrix.
    #[must_use]
    pub fn new(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipelines: &RenderPipelines,
        scene: &FilmScene,
    ) -> Self {
        let layout = &pipelines.model_bind_group_layout;
        let shapes = scene
            .shapes()
            .map(|(id, ir)| (id, GpuModel::from_ir(device, queue, layout, ir)))
            .collect();
        let world = scene
            .world()
            .map(|w| GpuModel::from_ir(device, queue, layout, &w.ir));
        Self {
            shapes,
            world,
            slots: Vec::new(),
            model_layout: layout.clone(),
            prepared: Vec::new(),
        }
    }

    /// Uploads the camera and per-draw matrices for `frame` and selects visible meshes.
    ///
    /// The camera is `frame.camera` unless `camera` overrides it (e.g. a free camera);
    /// an override does not change the per-actor LOD distances carried by the frame.
    /// Actors whose shape was not uploaded are skipped.
    pub fn prepare(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        camera_resources: &CameraGpuResources,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) {
        let uniform = if let Some(camera) = camera {
            camera.build_uniform()
        } else {
            let mut authored = CameraController::default();
            authored.set_authored_transform(frame.camera);
            authored.build_uniform()
        };
        camera_resources.upload(queue, &uniform);

        self.prepared.clear();
        if frame.world
            && let Some(world) = &self.world
        {
            let (base, decals) = world.collect_visible_meshes(0, 0.0);
            self.prepared.push(PreparedDraw {
                target: Target::World,
                base,
                decals,
            });
        }

        let mut slot = 0;
        for (actor_index, actor) in frame.actors.iter().enumerate() {
            let Some(model) = self.shapes.get(&actor.shape_id) else {
                continue;
            };
            let (base, decals) = model.collect_visible_meshes(actor.state_mask, actor.distance);
            if base.is_empty() && decals.is_empty() {
                continue;
            }
            if slot == self.slots.len() {
                self.slots.push(Self::new_slot(device, &self.model_layout));
            }
            queue.write_buffer(
                &self.slots[slot].buffer,
                0,
                bytemuck::bytes_of(&ModelUniform::new(
                    actor.world_matrix,
                    LAYER_FIRST_ACTOR + actor_index as u32,
                )),
            );
            self.prepared.push(PreparedDraw {
                target: Target::Shape {
                    shape_id: actor.shape_id,
                    slot,
                },
                base,
                decals,
            });
            slot += 1;
        }
    }

    /// Encodes the draws chosen by the last [`Self::prepare`] into `rpass`.
    ///
    /// The pass must target the formats `pipelines` was built for.
    pub fn draw(
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
                let (model, bind_group) = match draw.target {
                    Target::World => match &self.world {
                        Some(w) => (w, &w.model_bind_group),
                        None => continue,
                    },
                    Target::Shape { shape_id, slot } => match self.shapes.get(&shape_id) {
                        Some(m) => (m, &self.slots[slot].bind_group),
                        None => continue,
                    },
                };
                rpass.set_bind_group(2, bind_group, &[]);
                rpass.set_vertex_buffer(0, model.vertex_buffer.slice(..));
                rpass.set_index_buffer(model.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
                for mesh in meshes {
                    rpass.draw_indexed(
                        mesh.index_offset..(mesh.index_offset + mesh.index_count),
                        mesh.vertex_offset,
                        0..1,
                    );
                }
            }
        }
    }

    fn new_slot(device: &wgpu::Device, layout: &wgpu::BindGroupLayout) -> MatrixSlot {
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_scene_actor_model_uniform"),
            size: std::mem::size_of::<ModelUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("stunt_scene_actor_model_bind_group"),
            layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: buffer.as_entire_binding(),
            }],
        });
        MatrixSlot { buffer, bind_group }
    }
}

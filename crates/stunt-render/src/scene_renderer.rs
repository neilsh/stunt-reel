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
//! decal meshes of every draw per `[I5]`, which write no depth, so a later decal covers an
//! earlier one wherever both pass against the base. An actor that casts a shadow gets a second draw of
//! its shape, flattened onto the ground and filled in palette index 0, which lies on the
//! terrain and so goes in the decal pass whole, through a pipeline that culls no faces.
//!
//! A sprite (`OP_ANIMATE`, [`SpriteDraw`]) is its image uploaded once as a unit square of
//! one quad per run of equal pixels, index 0 left out, drawn through a slot whose matrix
//! turns the square to face the camera at the sprite's centre and size, in its actor's layer.
//!
//! Complies with `[I1]` (frames arrive in right-handed metres) and `[I5]`.

use std::collections::HashMap;

use glam::{Mat4, Vec3};

use stunt_core::contracts::{
    CameraTransform, NodeKind, SCENERY_OCEAN, SCENERY_TERRAIN, SodModelIr, SodVertex,
    VERTEX_FLAG_LINE, VisibilityCondition,
};
use stunt_core::scene::{FilmScene, SceneFrame, SpriteDraw};
use stunt_core::sprite::SpriteImage;

use crate::camera::{CameraController, CameraGpuResources};
use crate::mesh::{GpuMeshSlice, GpuModel};
use crate::outline::with_outlines;
use crate::palette::PaletteLut;
use crate::pipeline::{LAYER_FIRST_ACTOR, LAYER_PROP, ModelUniform, RenderPipelines};
use stunt_core::contracts::arena_index;

/// Which uploaded model a prepared draw uses.
#[derive(Clone, Copy, Debug)]
enum Target {
    /// The static world, drawn with its own identity bind group.
    World,
    /// An actor shape drawn through the model-matrix slot with this index.
    Shape { shape_id: u16, slot: usize },
    /// A sprite's image drawn through the model-matrix slot with this index.
    Image { image_id: u16, slot: usize },
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

/// A per-draw model matrix: uniform buffer plus its bind group.
#[derive(Debug)]
struct MatrixSlot {
    buffer: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
}

/// GPU renderer for the scene frames of one [`FilmScene`].
#[derive(Debug)]
pub(crate) struct SceneRenderer {
    shapes: HashMap<u16, GpuModel>,
    /// Every sprite image of the scene as a unit square ([`sprite_ir`]).
    images: HashMap<u16, GpuModel>,
    world: Option<GpuModel>,
    slots: Vec<MatrixSlot>,
    model_layout: wgpu::BindGroupLayout,
    prepared: Vec<PreparedDraw>,
}

impl SceneRenderer {
    /// Uploads every shape and the world of `scene`; the world keeps an identity matrix.
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
        // (research/playone-exe/sod-vm.md section 8.11).
        let shapes = scene
            .shapes()
            .map(|(id, ir)| {
                (
                    id,
                    GpuModel::from_ir(device, queue, layout, &with_outlines(ir)),
                )
            })
            .collect();
        let images = scene
            .images()
            .map(|(id, image)| {
                (
                    id,
                    GpuModel::from_ir(device, queue, layout, &sprite_ir(image)),
                )
            })
            .collect();
        let world = scene
            .world()
            .map(|w| GpuModel::from_ir_outlined(device, queue, layout, &w.ir, outlines_in_world));
        Self {
            shapes,
            images,
            world,
            slots: Vec::new(),
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
        camera_resources.upload(queue, &controller.build_uniform());

        self.prepared.clear();
        let eye = camera.map_or_else(
            || Vec3::from_array(frame.view.eye),
            CameraController::eye_position,
        );
        if frame.world
            && let Some(world) = &self.world
        {
            let (ground, base, decals) = {
                let lod_view = CameraTransform {
                    eye: frame.view.eye,
                    target: frame.view.target,
                    lens: frame.lens,
                    ..CameraTransform::default()
                };
                world.collect_world_meshes(eye, Some(&lod_view))
            };
            self.prepared.push(PreparedDraw {
                target: Target::World,
                ground,
                base,
                decals,
                shadow: false,
            });
        }

        let mut slot = 0;
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
            let uniform = ModelUniform::new(prop.world_matrix, LAYER_PROP);
            let shape_id = prop.shape_id;
            self.push_draw(
                device,
                queue,
                |slot| Target::Shape { shape_id, slot },
                &mut slot,
                &uniform,
                meshes,
            );
        }
        for (actor_index, actor) in (0u32..).zip(&frame.actors) {
            let Some(model) = self.shapes.get(&actor.shape_id) else {
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
            // (research/playone-exe/sod-vm.md section 9.1).
            if let Some(shadow_matrix) = actor.shadow_matrix {
                let uniform = ModelUniform::shadow(shadow_matrix, layer);
                let shadow = base.iter().chain(&decals).copied().collect();
                let shape_id = actor.shape_id;
                self.push_draw(
                    device,
                    queue,
                    |slot| Target::Shape { shape_id, slot },
                    &mut slot,
                    &uniform,
                    (Vec::new(), shadow),
                );
            }
            let uniform = ModelUniform::new(actor.world_matrix, layer);
            let shape_id = actor.shape_id;
            self.push_draw(
                device,
                queue,
                |slot| Target::Shape { shape_id, slot },
                &mut slot,
                &uniform,
                (base, decals),
            );
        }

        // Sprites have no shadow: `PLAYONE` skips `OP_ANIMATE` in the shadow pass.
        let view = controller.compute_view_matrix();
        for sprite in &frame.sprites {
            let Some(model) = self.images.get(&sprite.image_id) else {
                continue;
            };
            let (base, decals) = model.collect_visible_meshes(0, 0.0, eye, None);
            let layer = LAYER_FIRST_ACTOR + u32::try_from(sprite.actor).unwrap_or(u32::MAX);
            let uniform = ModelUniform::new(billboard_matrix(&view, sprite), layer);
            let image_id = sprite.image_id;
            self.push_draw(
                device,
                queue,
                |slot| Target::Image { image_id, slot },
                &mut slot,
                &uniform,
                (base, decals),
            );
        }
    }

    /// Queues a draw of the target `target` names for the next model-matrix slot, its
    /// `(base, decals)` slices through that slot, filled with `uniform`.
    fn push_draw(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        target: impl FnOnce(usize) -> Target,
        slot: &mut usize,
        uniform: &ModelUniform,
        (base, decals): (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>),
    ) {
        if *slot == self.slots.len() {
            self.slots.push(Self::new_slot(device, &self.model_layout));
        }
        let Some(model_slot) = self.slots.get(*slot) else {
            return;
        };
        queue.write_buffer(&model_slot.buffer, 0, bytemuck::bytes_of(uniform));
        let [_, shadow, ..] = uniform.layer;
        self.prepared.push(PreparedDraw {
            target: target(*slot),
            ground: Vec::new(),
            base,
            decals,
            shadow: shadow != 0,
        });
        *slot += 1;
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
        let world_ground = self.world.as_ref().zip(
            self.prepared
                .iter()
                .find(|d| matches!(d.target, Target::World) && !d.ground.is_empty()),
        );
        if let Some((world, draw)) = world_ground {
            rpass.set_bind_group(2, &world.model_bind_group, &[]);
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
                let (model, bind_group) = match draw.target {
                    Target::World => match &self.world {
                        Some(w) => (w, &w.model_bind_group),
                        None => continue,
                    },
                    Target::Shape { shape_id, slot } => {
                        match self.shapes.get(&shape_id).zip(self.slots.get(slot)) {
                            Some((m, model_slot)) => (m, &model_slot.bind_group),
                            None => continue,
                        }
                    }
                    Target::Image { image_id, slot } => {
                        match self.images.get(&image_id).zip(self.slots.get(slot)) {
                            Some((m, model_slot)) => (m, &model_slot.bind_group),
                            None => continue,
                        }
                    }
                };
                rpass.set_bind_group(2, bind_group, &[]);
                // A world decal slice's outline follows its own fill, so a later slice covers
                // it as it covers the fill: the decal pass writes no depth to hide it ([I5]).
                if decal_pass && matches!(draw.target, Target::World) {
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
                if matches!(draw.target, Target::World) {
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

    fn new_slot(device: &wgpu::Device, layout: &wgpu::BindGroupLayout) -> MatrixSlot {
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_scene_actor_model_uniform"),
            size: size_of::<ModelUniform>() as u64,
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

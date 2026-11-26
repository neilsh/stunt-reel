//! Dual-Pipeline Depth-Bias Presentation Pipeline Architecture.
//!
//! Complies with Architectural Invariants:
//! - `[I3]` VGA Mode 13h palette index color mapping and flat shading.
//! - `[I5]` Ordered decal pass: `GreaterEqual` under reversed depth, no depth write, hardware
//!   depth bias toward the viewer (`constant: 2, slope_scale: 2.0, clamp: 0.0`).

use stunt_core::contracts::SodVertex;

use crate::renderer::Look;

pub use stunt_core::frame::{
    LAYER_FIRST_ACTOR, LAYER_NONE, LAYER_OCEAN, LAYER_OVERLAY, LAYER_PROP, LAYER_TERRAIN,
};

/// Format of the optional plane target: two words per pixel, `layer << 8 | unlit palette index`
/// then the pixel's shape word (`RenderedPage::shapes`).
pub(crate) const PLANE_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rg32Uint;

/// Bind group index of the world's prop runs in the plane pipelines (`prop_runs` in
/// `mode13h.wgsl`).
pub(crate) const PROP_RUNS_GROUP: u32 = 3;

/// Bytes of one prop run in the [`PROP_RUNS_GROUP`] buffer: `first`, `end` and the shape word.
pub(crate) const PROP_RUN_SIZE: u64 = 12;

/// GPU uniform buffer structure for per-model transformation matrix matching WGSL `@group(2) @binding(0)`.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub(crate) struct ModelUniform {
    /// 4x4 column-major model-to-eye-relative matrix: the model's world matrix with the eye's
    /// translation taken off (`camera::eye_relative_matrix`).
    pub(crate) model_matrix: [f32; 16],
    /// Base layer id (first word) written to the plane target, added to the vertex's scenery
    /// class (zero except for world vertices); the second word is nonzero for a shadow draw,
    /// which fills every polygon with palette index 0; the third is the shape word the plane
    /// target keeps (`shape id + 1`, zero for no shape); the last is padding.
    pub(crate) layer: [u32; 4],
}

impl ModelUniform {
    /// The size of one uniform, which every `@group(2)` binding shows.
    pub(crate) const BINDING_SIZE: Option<wgpu::BufferSize> =
        wgpu::BufferSize::new(size_of::<Self>() as u64);

    /// A uniform drawing with `model_matrix` into `layer`, in no shape's pixels.
    #[must_use]
    pub(crate) fn new(model_matrix: [f32; 16], layer: u32) -> Self {
        Self {
            model_matrix,
            layer: [layer, 0, 0, 0],
        }
    }

    /// This uniform marking its pixels in the plane target as shape `shape_id`'s.
    #[must_use]
    pub(crate) fn with_shape(mut self, shape_id: u16) -> Self {
        self.layer[2] = u32::from(shape_id) + 1;
        self
    }

    /// A uniform drawing a ground shadow with `model_matrix` into `layer`: every polygon
    /// flat in palette index 0 and `OP_PERFDISK` discs skipped, as PLAYONE draws one with
    /// `work:0x806C` set (`research/playone-exe/sod-vm-frame.md` section 9.1,
    /// `research/playone-exe/sod-vm-generators.md` section 8.8).
    #[must_use]
    pub(crate) fn shadow(model_matrix: [f32; 16], layer: u32) -> Self {
        Self {
            model_matrix,
            layer: [layer, 1, 0, 0],
        }
    }
}

impl Default for ModelUniform {
    fn default() -> Self {
        Self::new(glam::Mat4::IDENTITY.to_cols_array(), 0)
    }
}

/// The `[I5]` decal pass's constant depth bias, toward the viewer: two steps of the
/// `Depth24Plus` buffer (ADR 0046's magnitude, its sign flipped by reversed depth;
/// `docs/adr/0054-depth-is-reversed-and-infinite.md`).
const DECAL_DEPTH_BIAS_CONSTANT: i32 = 2;
/// The `[I5]` decal pass's slope-scaled depth bias, toward the viewer: two pixels of the decal
/// triangle's own depth gradient.
const DECAL_DEPTH_BIAS_SLOPE_SCALE: f32 = 2.0;

/// Dual presentation pipelines separating base solid geometry from coplanar decals.
#[derive(Debug)]
pub(crate) struct RenderPipelines {
    /// The world's flat-ground pipeline: `Always` depth compare with depth write, so each
    /// slice paints over the last as `PLAYONE` paints the ground (`stunt_core::world::GROUND_NODE`).
    pub(crate) ground_pipeline: wgpu::RenderPipeline,
    /// Line-list pipeline for the outlines of the world's flat-ground slices, compared like
    /// [`Self::ground_pipeline`].
    pub(crate) ground_edge_pipeline: wgpu::RenderPipeline,
    /// Base mesh pipeline with zero depth bias and `Greater` depth compare (depth is reversed:
    /// nearer is larger).
    pub(crate) base_pipeline: wgpu::RenderPipeline,
    /// The base pipeline with neither depth test nor depth write, for an `OP_ANIMATE` sprite
    /// drawn at its place in the scenery walk: over everything drawn before it, under
    /// whatever is drawn after (`research/playone-exe/scene-walk-actors.md`).
    pub(crate) sprite_pipeline: wgpu::RenderPipeline,
    /// Decal mesh pipeline conforming to `[I5]`: hardware depth bias, `GreaterEqual` compare and
    /// no depth write, so decals drawn in stream order cover the earlier ones on their base.
    pub(crate) decal_pipeline: wgpu::RenderPipeline,
    /// The decal pipeline without back-face culling, for an actor's ground shadow: its
    /// faces are flattened onto the ground, so a face's winding there no longer says whether
    /// it faces the eye, and culling dropped every face wound downward (a wing's underside)
    /// and broke the shadow into specks.
    pub(crate) shadow_pipeline: wgpu::RenderPipeline,
    /// Line-list pipeline for the world mesh's polygon outlines (`GpuModel::draw_edges`),
    /// with the base depth test. Lines are not culled, since they have no winding.
    pub(crate) edge_pipeline: wgpu::RenderPipeline,
    /// The edge pipeline with the decal depth test, for the outlines of decal slices. wgpu
    /// allows depth bias only on triangles, so it compares `GreaterEqual` without the `[I5]`
    /// bias.
    pub(crate) edge_decal_pipeline: wgpu::RenderPipeline,
    /// Fullscreen pipeline that paints the sky bands behind all geometry.
    pub(crate) sky_pipeline: wgpu::RenderPipeline,
    /// Solid-black fullscreen pipeline used to paint `[I6]` letterbox bars.
    pub(crate) bar_pipeline: wgpu::RenderPipeline,
    /// Bind group layout for `@group(2) @binding(0)` (`ModelUniform`).
    pub(crate) model_bind_group_layout: wgpu::BindGroupLayout,
    /// Bind group layout for [`PROP_RUNS_GROUP`] (the world's prop runs, `fs_main_plane`), which
    /// only pipelines with a plane target carry; `None` without one.
    pub(crate) prop_runs_layout: Option<wgpu::BindGroupLayout>,
}

impl RenderPipelines {
    /// Returns the vertex buffer layout for zero-copy upload of `SodVertex`.
    pub(crate) fn vertex_buffer_layout() -> wgpu::VertexBufferLayout<'static> {
        // Assert compile-time layout compatibility with Invariant [I2] / Seam 3
        const _: () = assert!(
            size_of::<SodVertex>() == 28,
            "SodVertex is a 28-byte vertex"
        );
        const _: () = assert!(align_of::<SodVertex>() == 4, "SodVertex is 4-byte aligned");

        const ATTRIBUTES: [wgpu::VertexAttribute; 3] = [
            // Location 0: position [x, y, z] in metric meters (12 bytes)
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Float32x3,
                offset: 0,
                shader_location: 0,
            },
            // Location 1: normal [nx, ny, nz] (12 bytes)
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Float32x3,
                offset: 12,
                shader_location: 1,
            },
            // Location 2: packed attributes (palette_index, flags, scenery_class, decal_tie) (4 bytes)
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Uint8x4,
                offset: 24,
                shader_location: 2,
            },
        ];

        wgpu::VertexBufferLayout {
            array_stride: size_of::<SodVertex>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &ATTRIBUTES,
        }
    }

    /// Returns the layout of the second vertex stream: each vertex's apex
    /// (`outline::Outlined`) at location 3.
    pub(crate) fn apex_buffer_layout() -> wgpu::VertexBufferLayout<'static> {
        const ATTRIBUTES: [wgpu::VertexAttribute; 1] = [wgpu::VertexAttribute {
            format: wgpu::VertexFormat::Float32x3,
            offset: 0,
            shader_location: 3,
        }];
        wgpu::VertexBufferLayout {
            array_stride: size_of::<[f32; 3]>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &ATTRIBUTES,
        }
    }

    /// Creates the bind group layout for [`PROP_RUNS_GROUP`]: the world's prop runs as one
    /// read-only storage buffer of `[first, end, shape word]` `u32` triples, which the
    /// fragment stage searches.
    pub(crate) fn create_prop_runs_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("stunt_prop_runs_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Storage { read_only: true },
                    has_dynamic_offset: false,
                    min_binding_size: wgpu::BufferSize::new(PROP_RUN_SIZE),
                },
                count: None,
            }],
        })
    }

    /// Creates the bind group layout for the per-model uniform (`@group(2)`): one
    /// [`ModelUniform`] at a dynamic offset, so every bind passes one offset (`&[0]` for a
    /// buffer that holds a single uniform).
    pub(crate) fn create_model_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("stunt_model_uniform_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: true,
                    min_binding_size: ModelUniform::BINDING_SIZE,
                },
                count: None,
            }],
        })
    }

    /// Compiles shaders and instantiates both base and decal render pipelines.
    pub(crate) fn new(
        device: &wgpu::Device,
        color_format: wgpu::TextureFormat,
        depth_format: wgpu::TextureFormat,
        camera_layout: &wgpu::BindGroupLayout,
        palette_layout: &wgpu::BindGroupLayout,
        look: Look,
    ) -> Self {
        Self::build(
            device,
            color_format,
            None,
            depth_format,
            camera_layout,
            palette_layout,
            look,
        )
    }

    /// Like [`Self::new`], but every pass using these pipelines must carry a second colour
    /// attachment of `PLANE_FORMAT` that receives `layer << 8 | palette index` and the shape word per pixel.
    pub(crate) fn new_with_plane(
        device: &wgpu::Device,
        color_format: wgpu::TextureFormat,
        depth_format: wgpu::TextureFormat,
        camera_layout: &wgpu::BindGroupLayout,
        palette_layout: &wgpu::BindGroupLayout,
        look: Look,
    ) -> Self {
        Self::build(
            device,
            color_format,
            Some(PLANE_FORMAT),
            depth_format,
            camera_layout,
            palette_layout,
            look,
        )
    }

    fn build(
        device: &wgpu::Device,
        color_format: wgpu::TextureFormat,
        plane_format: Option<wgpu::TextureFormat>,
        depth_format: wgpu::TextureFormat,
        camera_layout: &wgpu::BindGroupLayout,
        palette_layout: &wgpu::BindGroupLayout,
        look: Look,
    ) -> Self {
        let fragment_entry = if plane_format.is_some() {
            "fs_main_plane"
        } else {
            "fs_main"
        };
        // The modern look draws the scene through entry points of its own and keeps the sky and
        // the bars (`fs_sky`, `bars.wgsl`) of the parity look.
        let (scene_vertex, scene_edge_vertex, scene_fragment) = match look {
            Look::Mode13h => ("vs_main", "vs_edge", fragment_entry),
            Look::Modern if plane_format.is_some() => {
                ("vs_modern", "vs_modern_edge", "fs_modern_plane")
            }
            Look::Modern => ("vs_modern", "vs_modern_edge", "fs_modern"),
        };
        let sky_fragment_entry = if plane_format.is_some() {
            "fs_sky_plane"
        } else {
            "fs_sky"
        };
        let model_bind_group_layout = Self::create_model_bind_group_layout(device);
        // The plane's shape word looks world props up in their runs; without a plane nothing
        // reads them.
        let prop_runs_layout = plane_format.map(|_| Self::create_prop_runs_layout(device));

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("stunt_mode13h_pipeline_layout"),
            bind_group_layouts: &[
                Some(camera_layout),
                Some(palette_layout),
                Some(&model_bind_group_layout),
                prop_runs_layout.as_ref(),
            ],
            immediate_size: 0,
        });

        let shader_module =
            device.create_shader_module(wgpu::include_wgsl!("shaders/mode13h.wgsl"));
        let vertex_buffers = [
            Some(Self::vertex_buffer_layout()),
            Some(Self::apex_buffer_layout()),
        ];
        let targets = color_targets(color_format, plane_format);

        let base_depth_stencil = depth_stencil(
            depth_format,
            true,
            wgpu::CompareFunction::Greater,
            wgpu::DepthBiasState::default(),
        );

        // Decal geometry depth stencil state: Invariant [I5] hardware depth bias.
        // A decal is coplanar with the surface it sits on, so it has to be nudged toward the
        // viewer to win that tie. Depth is reversed (nearer is larger), so the bias toward the
        // viewer is positive; under the standard depth it was negative, and a bias away from the
        // viewer hid decals (work/2026-10/parity-log/log.md, 2026-10-23). Decals write no depth,
        // so each is tested against the base geometry's depth, not other decals', and a later
        // coplanar decal covers an earlier one, as PLAYONE's painter does. The values are
        // in docs/adr/0054-depth-is-reversed-and-infinite.md.
        let decal_depth_stencil = depth_stencil(
            depth_format,
            false,
            wgpu::CompareFunction::GreaterEqual,
            wgpu::DepthBiasState {
                constant: DECAL_DEPTH_BIAS_CONSTANT,
                slope_scale: DECAL_DEPTH_BIAS_SLOPE_SCALE,
                clamp: 0.0,
            },
        );

        let primitive = primitive_state(wgpu::PrimitiveTopology::TriangleList);

        // PLAYONE culls back faces. The models wind clockwise for their outward faces, so the
        // `Ccw` default treated every interior wall as front-facing; culling the true back faces
        // raised CTRY 0.7733 -> 0.7808 and INTRO 0.7175 -> 0.7224 (work/2026-10/parity-log/log.md,
        // 2026-10-24). The two-sided flag (`SodVertex::flags` bit 1) is not decoded yet, so it
        // cannot exempt a polygon here.
        let model_primitive = wgpu::PrimitiveState {
            front_face: wgpu::FrontFace::Cw,
            cull_mode: Some(wgpu::Face::Back),
            ..primitive
        };

        let ground_depth_stencil = wgpu::DepthStencilState {
            depth_compare: Some(wgpu::CompareFunction::Always),
            ..base_depth_stencil.clone()
        };
        let edge_decal_depth_stencil = wgpu::DepthStencilState {
            bias: wgpu::DepthBiasState::default(),
            ..decal_depth_stencil.clone()
        };
        // The bars and the sky ignore depth entirely; both must still match the pass's format.
        let overlay_depth_stencil = depth_stencil(
            depth_format,
            false,
            wgpu::CompareFunction::Always,
            wgpu::DepthBiasState::default(),
        );

        // The line lists draw through `vs_edge`, which clips them to a band around the view
        // (`EDGE_CLIP_BAND` in mode13h.wgsl); triangles are clipped to the view already.
        let scene_pipeline = |label: &str,
                              primitive: wgpu::PrimitiveState,
                              depth_stencil: wgpu::DepthStencilState| {
            let entry = if primitive.topology == wgpu::PrimitiveTopology::LineList {
                scene_edge_vertex
            } else {
                scene_vertex
            };
            create_pipeline(
                device,
                label,
                Some(&pipeline_layout),
                vertex_state(&shader_module, entry, &vertex_buffers),
                fragment_state(&shader_module, scene_fragment, &targets),
                primitive,
                depth_stencil,
            )
        };

        let ground_pipeline = scene_pipeline(
            "stunt_mode13h_ground_pipeline",
            model_primitive,
            ground_depth_stencil.clone(),
        );
        let base_pipeline = scene_pipeline(
            "stunt_mode13h_base_pipeline",
            model_primitive,
            base_depth_stencil.clone(),
        );
        let sprite_pipeline = scene_pipeline(
            "stunt_mode13h_sprite_pipeline",
            model_primitive,
            wgpu::DepthStencilState {
                depth_write_enabled: Some(false),
                depth_compare: Some(wgpu::CompareFunction::Always),
                ..base_depth_stencil.clone()
            },
        );
        let decal_pipeline = scene_pipeline(
            "stunt_mode13h_decal_pipeline",
            model_primitive,
            decal_depth_stencil.clone(),
        );

        let edge_primitive = primitive_state(wgpu::PrimitiveTopology::LineList);
        let ground_edge_pipeline = scene_pipeline(
            "stunt_ground_edge_pipeline",
            edge_primitive,
            ground_depth_stencil,
        );
        let edge_pipeline =
            scene_pipeline("stunt_edge_pipeline", edge_primitive, base_depth_stencil);
        let edge_decal_pipeline = scene_pipeline(
            "stunt_edge_decal_pipeline",
            edge_primitive,
            edge_decal_depth_stencil,
        );

        let shadow_pipeline = scene_pipeline(
            "stunt_mode13h_shadow_pipeline",
            primitive,
            decal_depth_stencil,
        );

        // Letterbox bars: no vertex data, no bind groups, constant black output.
        let bar_shader = device.create_shader_module(wgpu::include_wgsl!("shaders/bars.wgsl"));
        let bar_pipeline = create_pipeline(
            device,
            "stunt_letterbox_bar_pipeline",
            None,
            vertex_state(&bar_shader, "vs_main", &[]),
            fragment_state(&bar_shader, fragment_entry, &targets),
            primitive,
            overlay_depth_stencil.clone(),
        );

        // Sky: first draw of the pass, ignores and never writes depth. It needs no model matrix.
        let sky_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("stunt_sky_pipeline_layout"),
            bind_group_layouts: &[Some(camera_layout), Some(palette_layout)],
            immediate_size: 0,
        });
        let sky_pipeline = create_pipeline(
            device,
            "stunt_sky_pipeline",
            Some(&sky_layout),
            vertex_state(&shader_module, "vs_sky", &[]),
            fragment_state(&shader_module, sky_fragment_entry, &targets),
            primitive,
            overlay_depth_stencil,
        );

        Self {
            ground_pipeline,
            ground_edge_pipeline,
            base_pipeline,
            sprite_pipeline,
            decal_pipeline,
            shadow_pipeline,
            edge_pipeline,
            edge_decal_pipeline,
            sky_pipeline,
            bar_pipeline,
            model_bind_group_layout,
            prop_runs_layout,
        }
    }
}

/// The colour target of every pipeline: the colour attachment, then the plane when the pass
/// carries one. Mode 13h flat rendering writes opaque colours, so neither state blends.
fn color_targets(
    color_format: wgpu::TextureFormat,
    plane_format: Option<wgpu::TextureFormat>,
) -> Vec<Option<wgpu::ColorTargetState>> {
    let mut targets = vec![Some(wgpu::ColorTargetState {
        format: color_format,
        blend: None,
        write_mask: wgpu::ColorWrites::ALL,
    })];
    if let Some(format) = plane_format {
        targets.push(Some(wgpu::ColorTargetState {
            format,
            blend: None,
            write_mask: wgpu::ColorWrites::ALL,
        }));
    }
    targets
}

/// A depth-stencil state over `format` that writes depth when `depth_write_enabled` and
/// compares with `depth_compare`, biased by `bias`.
fn depth_stencil(
    format: wgpu::TextureFormat,
    depth_write_enabled: bool,
    depth_compare: wgpu::CompareFunction,
    bias: wgpu::DepthBiasState,
) -> wgpu::DepthStencilState {
    wgpu::DepthStencilState {
        format,
        depth_write_enabled: Some(depth_write_enabled),
        depth_compare: Some(depth_compare),
        stencil: wgpu::StencilState::default(),
        bias,
    }
}

/// The primitive state of *topology* with counter-clockwise front faces and no culling, the
/// base each pipeline's variant starts from.
fn primitive_state(topology: wgpu::PrimitiveTopology) -> wgpu::PrimitiveState {
    wgpu::PrimitiveState {
        topology,
        strip_index_format: None,
        front_face: wgpu::FrontFace::Ccw,
        cull_mode: None,
        unclipped_depth: false,
        polygon_mode: wgpu::PolygonMode::Fill,
        conservative: false,
    }
}

/// The vertex stage of `entry_point` in `shader` over `buffers`.
fn vertex_state<'a>(
    shader: &'a wgpu::ShaderModule,
    entry_point: &'a str,
    buffers: &'a [Option<wgpu::VertexBufferLayout<'a>>],
) -> wgpu::VertexState<'a> {
    wgpu::VertexState {
        module: shader,
        entry_point: Some(entry_point),
        compilation_options: wgpu::PipelineCompilationOptions::default(),
        buffers,
    }
}

/// The fragment stage of `entry_point` in `shader` writing `targets`.
fn fragment_state<'a>(
    shader: &'a wgpu::ShaderModule,
    entry_point: &'a str,
    targets: &'a [Option<wgpu::ColorTargetState>],
) -> wgpu::FragmentState<'a> {
    wgpu::FragmentState {
        module: shader,
        entry_point: Some(entry_point),
        compilation_options: wgpu::PipelineCompilationOptions::default(),
        targets,
    }
}

/// Creates one render pipeline over *layout*, with the multisample, multiview and cache defaults
/// every pipeline here shares.
fn create_pipeline<'a>(
    device: &wgpu::Device,
    label: &'a str,
    layout: Option<&'a wgpu::PipelineLayout>,
    vertex: wgpu::VertexState<'a>,
    fragment: wgpu::FragmentState<'a>,
    primitive: wgpu::PrimitiveState,
    depth_stencil: wgpu::DepthStencilState,
) -> wgpu::RenderPipeline {
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(label),
        layout,
        vertex,
        fragment: Some(fragment),
        primitive,
        depth_stencil: Some(depth_stencil),
        multisample: wgpu::MultisampleState::default(),
        multiview_mask: None,
        cache: None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_uniform_size() {
        assert_eq!(size_of::<ModelUniform>(), 80);
    }

    #[test]
    fn test_vertex_buffer_layout_stride_and_offsets() {
        let layout = RenderPipelines::vertex_buffer_layout();
        assert_eq!(layout.array_stride, 28);
        assert_eq!(layout.attributes.len(), 3);
        assert_eq!(layout.attributes[0].offset, 0);
        assert_eq!(layout.attributes[1].offset, 12);
        assert_eq!(layout.attributes[2].offset, 24);
    }
}

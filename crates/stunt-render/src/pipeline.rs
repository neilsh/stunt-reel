//! Dual-Pipeline Depth-Bias Presentation Pipeline Architecture.
//!
//! Complies with Architectural Invariants:
//! - `[I3]` VGA Mode 13h palette index color mapping and flat shading.
//! - `[I5]` Hardware depth bias decal pass (`constant: 2, slope_scale: 2.0, clamp: 0.0`).

use stunt_core::contracts::SodVertex;

/// GPU uniform buffer structure for per-model transformation matrix matching WGSL `@group(2) @binding(0)`.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct ModelUniform {
    /// 4x4 column-major affine model-to-world transform matrix.
    pub model_matrix: [f32; 16],
}

impl Default for ModelUniform {
    fn default() -> Self {
        Self {
            model_matrix: glam::Mat4::IDENTITY.to_cols_array(),
        }
    }
}

/// Dual presentation pipelines separating base solid geometry from coplanar decals.
#[derive(Debug)]
pub struct RenderPipelines {
    /// Base mesh pipeline with zero depth bias and `Less` depth compare.
    pub base_pipeline: wgpu::RenderPipeline,
    /// Decal mesh pipeline conforming to `[I5]` with hardware depth bias and `LessEqual` compare.
    pub decal_pipeline: wgpu::RenderPipeline,
    /// Common pipeline layout shared across base and decal passes.
    pub pipeline_layout: wgpu::PipelineLayout,
    /// Bind group layout for `@group(2) @binding(0)` (ModelUniform).
    pub model_bind_group_layout: wgpu::BindGroupLayout,
    /// Common shader module compiled from `mode13h.wgsl`.
    pub shader_module: wgpu::ShaderModule,
}

impl RenderPipelines {
    /// Returns the vertex buffer layout for zero-copy upload of `SodVertex`.
    pub fn vertex_buffer_layout() -> wgpu::VertexBufferLayout<'static> {
        // Assert compile-time layout compatibility with Invariant [I2] / Seam 3
        const _: () = assert!(std::mem::size_of::<SodVertex>() == 28);
        const _: () = assert!(std::mem::align_of::<SodVertex>() == 4);

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
            // Location 2: packed attributes (palette_index, flags, pad0, pad1) (4 bytes)
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Uint8x4,
                offset: 24,
                shader_location: 2,
            },
        ];

        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<SodVertex>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &ATTRIBUTES,
        }
    }

    /// Creates the bind group layout for per-model uniform buffer (`@group(2)`).
    pub fn create_model_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("stunt_model_uniform_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        })
    }

    /// Compiles shaders and instantiates both base and decal render pipelines.
    pub fn new(
        device: &wgpu::Device,
        color_format: wgpu::TextureFormat,
        depth_format: wgpu::TextureFormat,
        camera_layout: &wgpu::BindGroupLayout,
        palette_layout: &wgpu::BindGroupLayout,
    ) -> Self {
        let model_bind_group_layout = Self::create_model_bind_group_layout(device);

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("stunt_mode13h_pipeline_layout"),
            bind_group_layouts: &[camera_layout, palette_layout, &model_bind_group_layout],
            push_constant_ranges: &[],
        });

        let shader_module =
            device.create_shader_module(wgpu::include_wgsl!("shaders/mode13h.wgsl"));
        let vertex_layout = Self::vertex_buffer_layout();

        // Base geometry depth stencil state: normal depth test, zero bias
        let base_depth_stencil = wgpu::DepthStencilState {
            format: depth_format,
            depth_write_enabled: true,
            depth_compare: wgpu::CompareFunction::Less,
            stencil: wgpu::StencilState::default(),
            bias: wgpu::DepthBiasState {
                constant: 0,
                slope_scale: 0.0,
                clamp: 0.0,
            },
        };

        // Decal geometry depth stencil state: Invariant [I5] hardware depth bias
        let decal_depth_stencil = wgpu::DepthStencilState {
            format: depth_format,
            depth_write_enabled: true,
            depth_compare: wgpu::CompareFunction::LessEqual,
            stencil: wgpu::StencilState::default(),
            bias: wgpu::DepthBiasState {
                constant: 2,
                slope_scale: 2.0,
                clamp: 0.0,
            },
        };

        let primitive = wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            strip_index_format: None,
            front_face: wgpu::FrontFace::Ccw,
            cull_mode: None, // No backface culling to support authentic two-sided facets
            unclipped_depth: false,
            polygon_mode: wgpu::PolygonMode::Fill,
            conservative: false,
        };

        let targets = [Some(wgpu::ColorTargetState {
            format: color_format,
            blend: None, // Mode 13h opaque flat rendering
            write_mask: wgpu::ColorWrites::ALL,
        })];

        let base_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("stunt_mode13h_base_pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader_module,
                entry_point: Some("vs_main"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                buffers: std::slice::from_ref(&vertex_layout),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader_module,
                entry_point: Some("fs_main"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                targets: &targets,
            }),
            primitive,
            depth_stencil: Some(base_depth_stencil),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        let decal_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("stunt_mode13h_decal_pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader_module,
                entry_point: Some("vs_main"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                buffers: std::slice::from_ref(&vertex_layout),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader_module,
                entry_point: Some("fs_main"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                targets: &targets,
            }),
            primitive,
            depth_stencil: Some(decal_depth_stencil),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        Self {
            base_pipeline,
            decal_pipeline,
            pipeline_layout,
            model_bind_group_layout,
            shader_module,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_uniform_size() {
        assert_eq!(std::mem::size_of::<ModelUniform>(), 64);
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

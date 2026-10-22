//! Headless Offscreen Renderer and Framebuffer Capture.
//!
//! Complies with Architectural Invariants:
//! - `[I6]` Headless 320x240 offscreen rendering target for automated parity verification.
//! - `[I3]` VGA Mode 13h palette index color mapping with zero bilinear filtering bleed.
//! - `[I5]` Hardware depth bias pass for coplanar decals.

use crate::camera::{CameraController, CameraGpuResources};
use crate::mesh::{GpuMeshSlice, GpuModel};
use crate::palette::PaletteLut;
use crate::pipeline::RenderPipelines;
use crate::scene_renderer::SceneRenderer;
use std::fmt;
use stunt_core::contracts::get_palette_rgb_float;
use stunt_core::scene::SceneFrame;

/// Headless rendering error types.
#[derive(Debug)]
pub enum HeadlessError {
    /// No compatible GPU adapter found.
    NoAdapterAvailable,
    /// Failed to request logical device.
    DeviceRequestFailed(String),
    /// Buffer readback mapping failed.
    BufferReadbackFailed(String),
    /// Image encoding failed.
    ImageSaveFailed(String),
}

impl fmt::Display for HeadlessError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoAdapterAvailable => write!(f, "No compatible GPU adapter found on this system"),
            Self::DeviceRequestFailed(err) => write!(f, "Failed to initialize wgpu device: {err}"),
            Self::BufferReadbackFailed(err) => write!(f, "Failed to map readback buffer: {err}"),
            Self::ImageSaveFailed(err) => write!(f, "Failed to save frame image: {err}"),
        }
    }
}

impl std::error::Error for HeadlessError {}

/// Headless offscreen renderer configured for 320x240 4:3 presentation.
#[derive(Debug)]
pub struct HeadlessRenderer {
    /// Logical GPU device.
    pub device: wgpu::Device,
    /// Command execution queue.
    pub queue: wgpu::Queue,
    /// Compiled presentation pipelines (base and decal).
    pub pipelines: RenderPipelines,
    /// Palette LUT texture and bind group.
    pub palette_lut: PaletteLut,
    /// Camera uniform buffer and bind group.
    pub camera_resources: CameraGpuResources,
    /// Offscreen color texture target (320x240 Rgba8Unorm).
    pub color_texture: wgpu::Texture,
    /// Offscreen color texture view.
    pub color_view: wgpu::TextureView,
    /// Offscreen depth texture (320x240 Depth24Plus).
    pub depth_texture: wgpu::Texture,
    /// Offscreen depth texture view.
    pub depth_view: wgpu::TextureView,
    /// Staging buffer for reading rendered pixels back to CPU memory.
    pub readback_buffer: wgpu::Buffer,
    /// Framebuffer width (320).
    pub width: u32,
    /// Framebuffer height (240).
    pub height: u32,
}

impl HeadlessRenderer {
    /// Base offscreen framebuffer width.
    pub const DEFAULT_WIDTH: u32 = 320;
    /// Base offscreen framebuffer height (4:3 aspect correction).
    pub const DEFAULT_HEIGHT: u32 = 240;
    /// Color format for offscreen framebuffers.
    pub const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
    /// Depth format for offscreen framebuffers.
    pub const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24Plus;

    /// Attempts to instantiate a headless offscreen renderer.
    pub fn new() -> Result<Self, HeadlessError> {
        Self::with_dimensions(Self::DEFAULT_WIDTH, Self::DEFAULT_HEIGHT)
    }

    /// Instantiates headless renderer with custom dimensions.
    pub fn with_dimensions(width: u32, height: u32) -> Result<Self, HeadlessError> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::all(),
            flags: wgpu::InstanceFlags::default(),
            ..Default::default()
        });

        // First attempt standard high-performance adapter, fallback to software adapter
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: None,
            force_fallback_adapter: false,
        }))
        .or_else(|| {
            pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::LowPower,
                compatible_surface: None,
                force_fallback_adapter: true,
            }))
        })
        .ok_or(HeadlessError::NoAdapterAvailable)?;

        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("stunt_headless_device"),
                required_features: wgpu::Features::empty(),
                required_limits:
                    wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits()),
                memory_hints: wgpu::MemoryHints::Performance,
            },
            None,
        ))
        .map_err(|e| HeadlessError::DeviceRequestFailed(e.to_string()))?;

        let camera_resources = CameraGpuResources::new(&device);
        let palette_lut = PaletteLut::new(&device, &queue);

        let pipelines = RenderPipelines::new(
            &device,
            Self::COLOR_FORMAT,
            Self::DEPTH_FORMAT,
            &camera_resources.bind_group_layout,
            &palette_lut.bind_group_layout,
        );

        let color_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_offscreen_color_target"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: Self::COLOR_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let color_view = color_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let depth_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_offscreen_depth_target"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: Self::DEPTH_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let depth_view = depth_texture.create_view(&wgpu::TextureViewDescriptor::default());

        // Readback buffer (320 * 4 = 1280 bytes/row, cleanly aligned to 256)
        let bytes_per_row = width * 4;
        let buffer_size = (bytes_per_row * height) as u64;

        let readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_offscreen_readback_buffer"),
            size: buffer_size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        Ok(Self {
            device,
            queue,
            pipelines,
            palette_lut,
            camera_resources,
            color_texture,
            color_view,
            depth_texture,
            depth_view,
            readback_buffer,
            width,
            height,
        })
    }

    /// Renders a scene containing one or more models and captures the resulting RGBA8 framebuffer.
    pub fn render_frame(
        &mut self,
        camera: &CameraController,
        models: &[(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice])],
        clear_palette_index: Option<u8>,
    ) -> Result<Vec<u8>, HeadlessError> {
        // Upload camera uniform
        let camera_uniform = camera.build_uniform();
        self.camera_resources.upload(&self.queue, &camera_uniform);

        self.capture(clear_palette_index, |this, rpass| {
            // Pass 1: Solid base geometry with zero depth bias
            rpass.set_pipeline(&this.pipelines.base_pipeline);
            rpass.set_bind_group(0, &this.camera_resources.bind_group, &[]);
            rpass.set_bind_group(1, &this.palette_lut.bind_group, &[]);
            for (model, base_meshes, _) in models {
                if base_meshes.is_empty() {
                    continue;
                }
                rpass.set_bind_group(2, &model.model_bind_group, &[]);
                rpass.set_vertex_buffer(0, model.vertex_buffer.slice(..));
                rpass.set_index_buffer(model.index_buffer.slice(..), wgpu::IndexFormat::Uint32);

                for mesh in *base_meshes {
                    rpass.draw_indexed(
                        mesh.index_offset..(mesh.index_offset + mesh.index_count),
                        mesh.vertex_offset,
                        0..1,
                    );
                }
            }

            // Pass 2: Invariant [I5] coplanar decals with hardware depth bias
            rpass.set_pipeline(&this.pipelines.decal_pipeline);
            rpass.set_bind_group(0, &this.camera_resources.bind_group, &[]);
            rpass.set_bind_group(1, &this.palette_lut.bind_group, &[]);

            for (model, _, decal_meshes) in models {
                if decal_meshes.is_empty() {
                    continue;
                }
                rpass.set_bind_group(2, &model.model_bind_group, &[]);
                rpass.set_vertex_buffer(0, model.vertex_buffer.slice(..));
                rpass.set_index_buffer(model.index_buffer.slice(..), wgpu::IndexFormat::Uint32);

                for mesh in *decal_meshes {
                    rpass.draw_indexed(
                        mesh.index_offset..(mesh.index_offset + mesh.index_count),
                        mesh.vertex_offset,
                        0..1,
                    );
                }
            }
        })
    }

    /// Renders one scene frame through `scene` and captures the RGBA8 framebuffer.
    ///
    /// `camera` overrides `frame.camera` when given (e.g. a free camera).
    pub fn render_scene(
        &mut self,
        scene: &mut SceneRenderer,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
        clear_palette_index: Option<u8>,
    ) -> Result<Vec<u8>, HeadlessError> {
        scene.prepare(
            &self.device,
            &self.queue,
            &self.camera_resources,
            frame,
            camera,
        );
        let scene = &*scene;
        self.capture(clear_palette_index, |this, rpass| {
            scene.draw(
                rpass,
                &this.pipelines,
                &this.camera_resources,
                &this.palette_lut,
            );
        })
    }

    /// Clears the offscreen targets, runs `draw` inside the render pass, and reads back RGBA8.
    fn capture(
        &self,
        clear_palette_index: Option<u8>,
        draw: impl FnOnce(&Self, &mut wgpu::RenderPass<'_>),
    ) -> Result<Vec<u8>, HeadlessError> {
        // Clear color determined by palette or default sky blue
        let clear_color = if let Some(pal_idx) = clear_palette_index {
            let (r, g, b) = get_palette_rgb_float(pal_idx);
            wgpu::Color {
                r: r as f64,
                g: g as f64,
                b: b as f64,
                a: 1.0,
            }
        } else {
            // Authentic Mode 13h daytime horizon sky blue (Palette index 180)
            let (r, g, b) = get_palette_rgb_float(180);
            wgpu::Color {
                r: r as f64,
                g: g as f64,
                b: b as f64,
                a: 1.0,
            }
        };

        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("stunt_headless_render_encoder"),
            });

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_headless_render_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.color_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(clear_color),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });

            draw(self, &mut rpass);
        }

        // Copy rendered color target to CPU readback buffer
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.color_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.readback_buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.width * 4),
                    rows_per_image: Some(self.height),
                },
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );

        self.queue.submit(Some(encoder.finish()));

        // Map buffer and read bytes
        let buffer_slice = self.readback_buffer.slice(..);
        let (sender, receiver) = std::sync::mpsc::channel();
        buffer_slice.map_async(wgpu::MapMode::Read, move |res| {
            let _ = sender.send(res);
        });

        self.device.poll(wgpu::Maintain::Wait);

        receiver
            .recv()
            .map_err(|e| HeadlessError::BufferReadbackFailed(e.to_string()))?
            .map_err(|e| HeadlessError::BufferReadbackFailed(e.to_string()))?;

        let mapped = buffer_slice.get_mapped_range();
        let pixel_bytes = mapped.to_vec();
        drop(mapped);
        self.readback_buffer.unmap();

        Ok(pixel_bytes)
    }

    /// Renders and saves a captured frame as a PNG file.
    pub fn render_to_png(
        &mut self,
        camera: &CameraController,
        models: &[(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice])],
        clear_palette_index: Option<u8>,
        path: impl AsRef<std::path::Path>,
    ) -> Result<(), HeadlessError> {
        let bytes = self.render_frame(camera, models, clear_palette_index)?;
        let img = image::RgbaImage::from_raw(self.width, self.height, bytes).ok_or_else(|| {
            HeadlessError::ImageSaveFailed(
                "Failed to construct RgbaImage from raw bytes".to_string(),
            )
        })?;
        img.save(path.as_ref())
            .map_err(|e| HeadlessError::ImageSaveFailed(e.to_string()))?;
        Ok(())
    }
}

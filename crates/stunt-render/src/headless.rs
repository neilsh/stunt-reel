//! Headless Offscreen Renderer and Framebuffer Capture.
//!
//! Complies with Architectural Invariants:
//! - `[I6]` Headless 320x240 offscreen rendering target for automated parity verification.
//! - `[I3]` VGA Mode 13h palette index color mapping with zero bilinear filtering bleed.
//! - `[I5]` Hardware depth bias pass for coplanar decals.

use crate::camera::{CameraController, CameraGpuResources};
use crate::palette::PaletteLut;
use crate::pipeline::{PLANE_FORMAT, RenderPipelines};
use crate::scene_renderer::SceneRenderer;
use stunt_core::scene::SceneFrame;

/// Headless rendering error types.
#[derive(Debug, thiserror::Error)]
pub enum HeadlessError {
    /// No compatible GPU adapter found.
    #[error("No compatible GPU adapter found on this system")]
    NoAdapterAvailable,
    /// Failed to request logical device.
    #[error("Failed to initialize wgpu device: {0}")]
    DeviceRequestFailed(String),
    /// Buffer readback mapping failed.
    #[error("Failed to map readback buffer: {0}")]
    BufferReadbackFailed(String),
}

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
    /// Staging buffer for reading rendered pixels back to CPU memory; each row is
    /// padded to a multiple of [`wgpu::COPY_BYTES_PER_ROW_ALIGNMENT`] bytes.
    pub readback_buffer: wgpu::Buffer,
    /// Offscreen plane target (`layer << 8 | palette index`, `R32Uint`).
    pub plane_texture: wgpu::Texture,
    /// Offscreen plane texture view.
    pub plane_view: wgpu::TextureView,
    /// Staging buffer for reading the plane target back.
    pub plane_readback_buffer: wgpu::Buffer,
    /// Framebuffer width (320).
    pub width: u32,
    /// Framebuffer height (240).
    pub height: u32,
    /// Bytes per row in the readback buffers: `width * 4` rounded up to
    /// `wgpu::COPY_BYTES_PER_ROW_ALIGNMENT`. The padding is stripped on readback, so any
    /// width works.
    padded_row_bytes: u32,
    /// When set, the 3D scene is drawn into the top this-many rows only, with the vertical
    /// focal scale kept, as `PLAYONE.EXE` does above its button bar. `None` fills the target.
    pub viewport_rows: Option<u32>,
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

        let pipelines = RenderPipelines::new_with_plane(
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

        let plane_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_offscreen_plane_target"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: PLANE_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let plane_view = plane_texture.create_view(&wgpu::TextureViewDescriptor::default());

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

        // Texture-to-buffer copies need a 256-byte row pitch; 320 * 4 = 1280 already is one.
        let padded_row_bytes = (width * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buffer_size = u64::from(padded_row_bytes) * u64::from(height);

        let readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_offscreen_readback_buffer"),
            size: buffer_size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        let plane_readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_offscreen_plane_readback_buffer"),
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
            plane_texture,
            plane_view,
            plane_readback_buffer,
            width,
            height,
            padded_row_bytes,
            viewport_rows: None,
        })
    }

    /// Renders one scene frame through `scene` and captures the RGBA8 framebuffer.
    ///
    /// `camera` overrides `frame.camera` when given (e.g. a free camera). The palette,
    /// clear colour included, is the film palette for `frame.palette`.
    pub fn render_scene(
        &mut self,
        scene: &mut SceneRenderer,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
        clear_palette_index: Option<u8>,
    ) -> Result<Vec<u8>, HeadlessError> {
        self.render_scene_with_plane(scene, frame, camera, clear_palette_index)
            .map(|(rgba, _plane)| rgba)
    }

    /// Like [`Self::render_scene`], and also returns the plane: one `u32` per pixel,
    /// `layer << 8 | unlit palette index`, where uncovered pixels are the clear index on
    /// [`crate::pipeline::LAYER_NONE`].
    pub fn render_scene_with_plane(
        &mut self,
        scene: &mut SceneRenderer,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
        clear_palette_index: Option<u8>,
    ) -> Result<(Vec<u8>, Vec<u32>), HeadlessError> {
        self.palette_lut.set_controls(&self.queue, frame.palette);
        let squeezed = self.viewport_rows.map(|rows| {
            let mut controller = CameraController::default();
            controller.set_authored_transform(frame.camera);
            controller.projection_y_scale = self.height as f32 / rows.max(1) as f32;
            controller
        });
        scene.prepare(
            &self.device,
            &self.queue,
            &self.camera_resources,
            frame,
            camera.or(squeezed.as_ref()),
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
    ) -> Result<(Vec<u8>, Vec<u32>), HeadlessError> {
        // Clear color from the loaded palette: the given index, or daytime horizon sky
        // blue (palette index 180).
        let (r, g, b) = self
            .palette_lut
            .rgb_float(clear_palette_index.unwrap_or(180));
        let clear_color = wgpu::Color {
            r: r as f64,
            g: g as f64,
            b: b as f64,
            a: 1.0,
        };

        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("stunt_headless_render_encoder"),
            });

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_headless_render_pass"),
                color_attachments: &[
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.color_view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(clear_color),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.plane_view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color {
                                r: f64::from(clear_palette_index.unwrap_or(180)),
                                g: 0.0,
                                b: 0.0,
                                a: 0.0,
                            }),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                ],
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

            if let Some(rows) = self.viewport_rows {
                rpass.set_viewport(0.0, 0.0, self.width as f32, rows as f32, 0.0, 1.0);
            }
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
                    bytes_per_row: Some(self.padded_row_bytes),
                    rows_per_image: Some(self.height),
                },
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );

        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.plane_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.plane_readback_buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.padded_row_bytes),
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

        let pixel_bytes = self.read_back(&self.readback_buffer)?;
        let plane = self
            .read_back(&self.plane_readback_buffer)?
            .as_chunks::<4>()
            .0
            .iter()
            .map(|word| u32::from_le_bytes(*word))
            .collect();

        Ok((pixel_bytes, plane))
    }

    /// Maps `buffer`, copies its rows out without the pitch padding, and unmaps it.
    fn read_back(&self, buffer: &wgpu::Buffer) -> Result<Vec<u8>, HeadlessError> {
        let buffer_slice = buffer.slice(..);
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
        let row_bytes = self.width as usize * 4;
        let bytes = mapped
            .chunks_exact(self.padded_row_bytes as usize)
            .flat_map(|row| &row[..row_bytes])
            .copied()
            .collect();
        drop(mapped);
        buffer.unmap();
        Ok(bytes)
    }
}
